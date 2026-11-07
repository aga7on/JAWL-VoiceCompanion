"""Capture source switching must not silently substitute mixed system audio."""

import os
from pathlib import Path
import subprocess
import sys
import io
import queue
import threading
import time
from types import SimpleNamespace

import pytest

from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge, AmbientAudioService
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer
from jawl_voicecompanion.app_audio_router import AppAudioRouter


class Capture:
    session_id = "ambient-audio"

    def __init__(self, *args, **kwargs):
        self.running = False
        self.pid = args[1] if len(args) > 1 else None

    def start(self):
        self.running = True
        return self.state()

    def stop(self):
        self.running = False
        return self.state()

    def state(self):
        return {"running": self.running, "pid": self.pid}


def test_switch_restarts_and_reports_actual_capture(monkeypatch):
    import jawl_voicecompanion.ambient_audio as audio
    import psutil

    class Process:
        def __init__(self, pid):
            self.pid = pid
        def parents(self):
            return []
        def children(self, recursive=False):
            return []
        def name(self):
            return "player.exe"

    monkeypatch.setattr(psutil, "Process", Process)
    monkeypatch.setattr(audio, "ProcessAudioLoopback", Capture)
    router = AppAudioRouter()
    client = SimpleNamespace(feed_audio=lambda *a, **k: [], end_audio=lambda *a, **k: [])
    bridge = AmbientAudioASRBridge(client, AmbientMemoryBuffer(enabled=True), app_router=router)
    system = Capture()
    service = AmbientAudioService(bridge, capture=system)
    service.start()
    state = service.select_source(991234)
    assert not system.running
    assert state["capture"]["running"]
    assert state["capture"]["pid"] == 991234
    assert router.is_using_process_loopback()
    state = service.select_source(None)
    assert state["capture"]["running"]
    assert service.capture is system
    assert not router.is_using_process_loopback()
    with pytest.raises(ValueError, match="companion"):
        service.select_source(os.getpid())
    service.stop()


@pytest.mark.skipif(os.name != "nt", reason="Windows process loopback")
def test_real_helper_starts_for_owned_process_without_playback():
    helper = Path(__file__).resolve().parents[1] / "runtime/bin/process-loopback/process-loopback.exe"
    if not helper.is_file():
        pytest.skip("native helper is not built")
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                              creationflags=subprocess.CREATE_NO_WINDOW)
    # The target is this test process's child; use the capture directly. The
    # service deliberately refuses its own descendants in the real profile.
    from jawl_voicecompanion.system_audio import ProcessAudioLoopback
    capture = ProcessAudioLoopback(lambda *args: None, target.pid, helper=helper)
    try:
        state = capture.start()
        assert state["running"]
        assert state["pid"] == target.pid
    finally:
        capture.stop()
        target.terminate()
        target.wait(timeout=5)


def test_failed_process_start_does_not_resume_system_capture(monkeypatch):
    import jawl_voicecompanion.ambient_audio as audio
    import psutil

    class Process:
        def __init__(self, pid):
            self.pid = pid
        def parents(self):
            return []
        def children(self, recursive=False):
            return []
        def name(self):
            return "player.exe"

    class FailedCapture(Capture):
        def start(self):
            raise RuntimeError("capture failed")

    monkeypatch.setattr(psutil, "Process", Process)
    monkeypatch.setattr(audio, "ProcessAudioLoopback", FailedCapture)
    router = AppAudioRouter()
    client = SimpleNamespace(feed_audio=lambda *a, **k: [], end_audio=lambda *a, **k: [])
    bridge = AmbientAudioASRBridge(client, AmbientMemoryBuffer(enabled=True), app_router=router)
    system = Capture()
    service = AmbientAudioService(bridge, capture=system)
    service.start()
    with pytest.raises(RuntimeError, match="capture failed"):
        service.select_source(991234)
    assert not system.running
    assert not service.capture.running
    assert not router.resolve_capture_source()["isolated"]


def test_source_switch_waits_for_old_process_consumer_after_helper_exits():
    from jawl_voicecompanion.system_audio import ProcessAudioLoopback

    class ExitedProcess:
        def poll(self): return 0
        def wait(self, timeout=None): return 0

    entered, release = threading.Event(), threading.Event()
    def blocked_callback():
        entered.set()
        release.wait(8)

    worker = threading.Thread(target=blocked_callback, daemon=True)
    worker.start()
    assert entered.wait(1)
    capture = ProcessAudioLoopback(lambda *args: None, 1234, helper="unused")
    capture._process = ExitedProcess()
    capture._worker = worker
    router = AppAudioRouter()
    router.attach_process_loopback(capture)
    bridge = AmbientAudioASRBridge(
        SimpleNamespace(feed_audio=lambda *a, **k: [], end_audio=lambda *a, **k: []),
        AmbientMemoryBuffer(enabled=True), app_router=router,
    )
    service = AmbientAudioService(bridge, capture=capture)
    system = Capture()
    service._system_capture = system
    try:
        assert not capture.running and capture.state()["consumer_alive"]
        with pytest.raises(RuntimeError, match="still stopping"):
            service.select_source(None)
        assert service.capture is capture
        assert capture.state()["stopping"] and capture.state()["consumer_alive"]
    finally:
        release.set()
        worker.join(2)
    service.select_source(None)
    assert service.capture is system


def test_process_loopback_timestamps_pipe_receipt():
    from jawl_voicecompanion.system_audio import ProcessAudioLoopback
    capture = ProcessAudioLoopback(lambda *args: None, 1234, helper="unused")
    capture._queue = queue.Queue(maxsize=2)
    process = SimpleNamespace(stdout=io.BytesIO(b"JAWLPCM1" + b"\x01\x00\x02\x00"))
    before = time.monotonic()
    capture._read(process)
    after = time.monotonic()
    chunk = capture._queue.get_nowait()
    assert chunk.data == b"\x01\x00\x02\x00"
    assert before <= chunk.captured_monotonic <= after
    assert chunk.timestamp_source == "host_pipe_receipt_monotonic"
    assert capture.state()["timestamp_source"] == "host_pipe_receipt_monotonic"


def test_process_consumer_delivers_capture_time_and_sequence_gap():
    from jawl_voicecompanion.system_audio import ProcessAudioLoopback, _Chunk

    received, finished = [], threading.Event()
    def consume(data, rate, channels, session_id, *, captured_at=None, discontinuity=False):
        received.append((data, captured_at, discontinuity))
        if len(received) == 2:
            finished.set()

    capture = ProcessAudioLoopback(consume, 1234, helper="unused")
    capture._queue = queue.Queue(maxsize=2)
    stamp = time.monotonic() - 4
    capture._queue.put(_Chunk(b"\x01\x00\x01\x00", 44100, 2, stamp, 1))
    capture._queue.put(_Chunk(b"\x03\x00\x03\x00", 44100, 2, stamp + 0.1, 3))
    worker = threading.Thread(target=capture._consume, daemon=True)
    worker.start()
    try:
        assert finished.wait(1)
        assert [row[1] for row in received] == [stamp, stamp + 0.1]
        assert [row[2] for row in received] == [False, True]
    finally:
        capture._stop.set()
        worker.join(2)


def test_process_capture_overflow_reports_gap_after_blocked_consumer():
    from jawl_voicecompanion.system_audio import ProcessAudioLoopback

    first_entered, release, dropped_seen = threading.Event(), threading.Event(), threading.Event()
    second_seen, allow_next, third_seen = threading.Event(), threading.Event(), threading.Event()
    received = []
    def consume(data, rate, channels, session_id, *, captured_at=None, discontinuity=False):
        received.append((data, discontinuity))
        if len(received) == 1:
            first_entered.set()
            release.wait(3)
        elif len(received) == 2:
            second_seen.set()
        elif len(received) == 3:
            third_seen.set()

    class Pipe:
        calls = 0
        def read(self, size):
            self.calls += 1
            if self.calls == 1: return b"JAWLPCM1"
            if self.calls == 2: return b"\x01\x00\x01\x00"
            if self.calls == 3:
                assert first_entered.wait(2)
                return b"\x02\x00\x02\x00"
            if self.calls == 4: return b"\x03\x00\x03\x00"
            if self.calls == 5:
                dropped_seen.set()
                assert allow_next.wait(3)
                return b"\x04\x00\x04\x00"
            return b""

    capture = ProcessAudioLoopback(consume, 1234, helper="unused", queue_size=1)
    capture._queue = queue.Queue(maxsize=1)
    reader = threading.Thread(target=capture._read, args=(SimpleNamespace(stdout=Pipe()),), daemon=True)
    worker = threading.Thread(target=capture._consume, daemon=True)
    worker.start()
    reader.start()
    try:
        assert dropped_seen.wait(2)
        assert capture.state()["dropped_chunks"] == 1
        release.set()
        assert second_seen.wait(2)
        allow_next.set()
        assert third_seen.wait(2)
        assert [item[0][0] for item in received] == [1, 2, 4]
        assert [item[1] for item in received] == [False, False, True]
    finally:
        release.set()
        allow_next.set()
        capture._stop.set()
        reader.join(2)
        worker.join(2)
