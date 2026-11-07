"""Unit tests for Windows WASAPI Process-Tree Loopback Python bridge and router integration."""

from __future__ import annotations

import io
from pathlib import Path
import queue
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from jawl_voicecompanion.app_audio_router import (
    AppAudioRouter,
    AppAudioSession,
    MODE_ALL,
    MODE_ALL_EXCEPT_SELF,
    MODE_TARGET_APP,
)
from jawl_voicecompanion.process_loopback import (
    ProcessLoopbackBridge,
    ProcessLoopbackError,
)


class _MockStdin:
    def __init__(self) -> None:
        self.written = bytearray()
        self.flushed = False
        self.closed = False

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


class _MockStdout:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n)

    def close(self) -> None:
        self.closed = True


class _StreamingStdout:
    def __init__(self) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self.closed = False

    def feed(self, chunk: bytes) -> None:
        self._queue.put(chunk)

    def close_feed(self) -> None:
        self._queue.put(None)

    def read(self, n: int = -1) -> bytes:
        if self.closed:
            return b""
        try:
            item = self._queue.get(timeout=0.5)
            if item is None:
                return b""
            return item
        except queue.Empty:
            return b""

    def close(self) -> None:
        self.closed = True
        self._queue.put(None)


class _MockStderr:
    def __init__(self, text: str = "") -> None:
        self._stream = io.BytesIO(text.encode("utf-8"))
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        return self._stream.read(n)

    def close(self) -> None:
        self.closed = True


class _MockSubprocess:
    def __init__(
        self,
        stdout_obj: Any,
        stderr_text: str = "",
        poll_code: int | None = None,
    ) -> None:
        self.stdin = _MockStdin()
        self.stdout = stdout_obj
        self.stderr = _MockStderr(stderr_text)
        self._poll_code = poll_code
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self) -> int | None:
        return self._poll_code

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        self._poll_code = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self._poll_code = 0

    def kill(self) -> None:
        self.killed = True
        self._poll_code = 1


def test_binary_resolution_default_found() -> None:
    bridge = ProcessLoopbackBridge()
    assert bridge.executable is not None
    # If compiled binary is present in runtime/bin, is_file() will be True
    expected = ProcessLoopbackBridge.find_default_executable()
    assert bridge.executable == expected


def test_missing_binary_raises_process_loopback_error(tmp_path: Path) -> None:
    missing_bin = tmp_path / "nonexistent_loopback.exe"
    bridge = ProcessLoopbackBridge(executable=missing_bin)
    with pytest.raises(ProcessLoopbackError) as exc_info:
        bridge.start(pid=1234)
    assert "executable not found" in str(exc_info.value)
    assert not bridge.running


def test_invalid_pid_rejected() -> None:
    bridge = ProcessLoopbackBridge()
    with pytest.raises(ValueError):
        bridge.start(pid=-1)
    with pytest.raises(ValueError):
        bridge.start(pid=0)
    with pytest.raises(ValueError):
        bridge.start(pid=True)  # type: ignore[arg-type]


def test_mock_subprocess_valid_handshake_and_audio_delivery(tmp_path: Path) -> None:
    dummy_exe = tmp_path / "process-loopback.exe"
    dummy_exe.touch()

    # Handshake (8 bytes) + 2 chunks of 4096 bytes raw PCM16 stereo (4 bytes/frame)
    chunk1 = b"\x01\x00\x02\x00" * 1024
    chunk2 = b"\x03\x00\x04\x00" * 1024
    payload = ProcessLoopbackBridge.HANDSHAKE + chunk1 + chunk2

    mock_proc = _MockSubprocess(_MockStdout(payload), stderr_text="ready 44100 2 s16le\n")

    delivered_chunks: list[tuple[bytes, int, int]] = []
    finished = threading.Event()

    def consumer(data: bytes, rate: int, channels: int) -> None:
        delivered_chunks.append((data, rate, channels))
        if len(delivered_chunks) >= 2:
            finished.set()

    bridge = ProcessLoopbackBridge(executable=dummy_exe, spawn=lambda *args, **kwargs: mock_proc)
    state = bridge.start(pid=4321, consumer=consumer)

    assert state["pid"] == 4321
    assert state["sample_rate"] == 44100
    assert state["channels"] == 2

    finished.wait(timeout=2.0)
    assert len(delivered_chunks) == 2
    assert delivered_chunks[0] == (chunk1, 44100, 2)
    assert delivered_chunks[1] == (chunk2, 44100, 2)

    st = bridge.state()
    assert st["bytes_captured"] == 8192
    assert st["chunks_captured"] == 2
    assert st["last_error"] is None

    bridge.stop()
    assert not bridge.running


def test_mock_subprocess_queue_when_consumer_none(tmp_path: Path) -> None:
    dummy_exe = tmp_path / "process-loopback.exe"
    dummy_exe.touch()

    chunk = b"\x0a\x00\x0b\x00" * 1024
    payload = ProcessLoopbackBridge.HANDSHAKE + chunk
    mock_proc = _MockSubprocess(_MockStdout(payload), stderr_text="ready 44100 2 s16le\n")

    bridge = ProcessLoopbackBridge(executable=dummy_exe, spawn=lambda *args, **kwargs: mock_proc)
    bridge.start(pid=9999, consumer=None)

    received = bridge.get_chunk(timeout=2.0)
    assert received == chunk
    bridge.stop()


def test_invalid_handshake_raises_error(tmp_path: Path) -> None:
    dummy_exe = tmp_path / "process-loopback.exe"
    dummy_exe.touch()

    bad_payload = b"BADMAGIC" + b"\x00" * 100
    mock_proc = _MockSubprocess(
        _MockStdout(bad_payload),
        stderr_text="activation failed\n",
    )

    bridge = ProcessLoopbackBridge(executable=dummy_exe, spawn=lambda *args, **kwargs: mock_proc)
    with pytest.raises(ProcessLoopbackError) as exc_info:
        bridge.start(pid=5555)

    err_text = str(exc_info.value)
    assert "Process loopback handshake failed" in err_text
    assert "BADMAGIC" in err_text
    assert "activation failed" in err_text
    assert not bridge.running


def test_premature_eof_raises_error(tmp_path: Path) -> None:
    dummy_exe = tmp_path / "process-loopback.exe"
    dummy_exe.touch()

    # Subprocess writes only 3 bytes then EOF
    short_payload = b"JAW"
    mock_proc = _MockSubprocess(
        _MockStdout(short_payload),
        stderr_text="target unavailable\n",
    )

    bridge = ProcessLoopbackBridge(executable=dummy_exe, spawn=lambda *args, **kwargs: mock_proc)
    with pytest.raises(ProcessLoopbackError) as exc_info:
        bridge.start(pid=1111)

    err_text = str(exc_info.value)
    assert "Process loopback handshake failed" in err_text
    assert "target unavailable" in err_text
    assert not bridge.running


def test_graceful_shutdown_sends_q(tmp_path: Path) -> None:
    dummy_exe = tmp_path / "process-loopback.exe"
    dummy_exe.touch()

    pipe = _StreamingStdout()
    pipe.feed(ProcessLoopbackBridge.HANDSHAKE)

    mock_proc = _MockSubprocess(pipe, stderr_text="ready 44100 2 s16le\n")
    bridge = ProcessLoopbackBridge(executable=dummy_exe, spawn=lambda *args, **kwargs: mock_proc)

    bridge.start(pid=8888)
    assert bridge.running

    stop_state = bridge.stop(timeout=1.0)
    assert mock_proc.stdin.written == b"q"
    assert mock_proc.stdin.flushed is True
    assert mock_proc.stdin.closed is True
    assert not stop_state["running"]
    assert not bridge.running


def test_app_audio_router_mode_all_except_self_falls_back_to_maxwell() -> None:
    router = AppAudioRouter(mode=MODE_ALL_EXCEPT_SELF)
    assert router.create_or_get_process_loopback() is None
    assert router.is_using_process_loopback() is False

    cap_source = router.resolve_capture_source()
    assert cap_source["backend"] == "system_loopback"
    assert cap_source["device_name"] == "Game-Audeze Maxwell"
    assert cap_source["isolated"] is False
    assert router.state()["using_process_loopback"] is False


def test_app_audio_router_target_app_without_pid_falls_back_to_maxwell() -> None:
    router = AppAudioRouter(mode=MODE_TARGET_APP, target_app=None, target_pid=None)
    assert router.create_or_get_process_loopback() is None

    cap_source = router.resolve_capture_source()
    assert cap_source["backend"] == "system_loopback"
    assert cap_source["device_name"] == "Game-Audeze Maxwell"
    assert cap_source["isolated"] is False


def test_app_audio_router_target_app_session_integration(tmp_path: Path) -> None:
    dummy_exe = tmp_path / "process-loopback.exe"
    dummy_exe.touch()

    router = AppAudioRouter(
        mode=MODE_TARGET_APP,
        target_app="discord.exe",
        target_pid=6543,
    )

    # 1. Create or get process loopback
    bridge = router.create_or_get_process_loopback(executable=dummy_exe)
    assert bridge is not None
    assert isinstance(bridge, ProcessLoopbackBridge)
    assert router.get_process_loopback() is bridge

    # 2. Check resolve_capture_source reflects target app capture
    cap_source = router.resolve_capture_source()
    assert cap_source["backend"] == "process_loopback"
    assert cap_source["target_pid"] == 6543
    assert cap_source["isolated"] is False  # configured is not yet running
    assert cap_source["fallback_device"] == "Game-Audeze Maxwell"

    # 3. Simulate active capture with mock
    pipe = _StreamingStdout()
    pipe.feed(ProcessLoopbackBridge.HANDSHAKE)
    mock_proc = _MockSubprocess(pipe)
    bridge._spawn = lambda *args, **kwargs: mock_proc

    res = router.start_process_loopback(pid=6543)
    assert res is not None
    assert router.is_using_process_loopback() is True
    assert router.resolve_capture_source()["isolated"] is True

    st = router.state()
    assert st["using_process_loopback"] is True
    assert st["capture_semantics"] == "isolated_process_tree_loopback"
    assert st["process_loopback"]["pid"] == 6543

    # 4. Filter and attribute attributes to target app when process loopback is active
    allow, sess, reason = router.filter_and_attribute()
    assert allow is True
    assert sess is not None
    assert sess.pid == 6543
    assert reason == "target_app_match"

    # 5. Switching mode away from MODE_TARGET_APP automatically stops and detaches bridge
    router.set_mode(MODE_ALL_EXCEPT_SELF)
    assert router.is_using_process_loopback() is False
    assert router.get_process_loopback() is None
    assert router.state()["capture_semantics"] == "mixed_output_loopback_not_separate_app_streams"
    assert router.resolve_capture_source()["backend"] == "system_loopback"
