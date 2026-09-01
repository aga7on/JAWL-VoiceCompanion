"""Small subprocess client for the optional VoiceMem JSON-lines sidecar."""

from __future__ import annotations

import json
import base64
import os
import queue
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from typing import Any, Iterable
from uuid import uuid4


class VoiceMemUnavailable(ConnectionError):
    """Raised when the optional sidecar cannot answer a bounded request."""


class VoiceMemProcessClient:
    """Lazily run one VoiceMem process and correlate its JSON-lines replies."""

    def __init__(
        self,
        python_executable: str | Path = sys.executable,
        *,
        runner: str | Path | None = None,
        args: Iterable[str] = (),
        timeout_seconds: float = 5.0,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self.python_executable = str(python_executable)
        self.runner = str(runner or root / "services" / "voicemem_sidecar.py")
        self.args = tuple(str(item) for item in args)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 30.0))
        self._process: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._lock = Lock()
        self._reader: Thread | None = None
        self._status = "not_started"

    def feed_partial(self, text: str, *, ended: bool = False, session_id: str = "local") -> list[dict[str, Any]]:
        request_id = str(uuid4())
        request = {
            "schema_version": 1,
            "request_id": request_id,
            "type": "feed_partial",
            "session_id": str(session_id or "local")[:200],
            "text": str(text or "")[:12_000],
            "ended": ended,
        }
        return self._request(request, request_id)

    def feed_audio(
        self,
        pcm16: bytes,
        *,
        sample_rate: int = 16000,
        session_id: str = "local",
    ) -> list[dict[str, Any]]:
        if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) > 48 * 1024 or len(pcm16) % 2:
            raise ValueError("pcm16 must be non-empty, even-sized and at most 48 KiB")
        request_id = str(uuid4())
        request = {
            "schema_version": 1,
            "request_id": request_id,
            "type": "feed_audio",
            "session_id": str(session_id or "local")[:200],
            "sample_rate": int(sample_rate),
            "channels": 1,
            "pcm16_base64": base64.b64encode(pcm16).decode("ascii"),
        }
        return self._request(request, request_id)

    def end_audio(self, *, session_id: str = "local") -> list[dict[str, Any]]:
        request_id = str(uuid4())
        return self._request({
            "schema_version": 1,
            "request_id": request_id,
            "type": "end_audio",
            "session_id": str(session_id or "local")[:200],
        }, request_id)

    def health(self) -> dict[str, Any]:
        request_id = str(uuid4())
        replies = self._request({"type": "health", "request_id": request_id}, request_id)
        return replies[0] if replies else {"type": "health", "status": "degraded"}

    def close(self) -> None:
        process = self._process
        reader = self._reader
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            finally:
                process.wait(timeout=2)
        if reader is not None:
            reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        self._status = "stopped"

    def _request(self, payload: dict[str, Any], request_id: str) -> list[dict[str, Any]]:
        with self._lock:
            try:
                process = self._ensure_process()
                if process.stdin is None:
                    raise VoiceMemUnavailable("VoiceMem sidecar stdin is unavailable")
                process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                process.stdin.flush()
                return self._read_until_complete(request_id)
            except (OSError, BrokenPipeError, VoiceMemUnavailable):
                self._status = "degraded"
                raise VoiceMemUnavailable("VoiceMem sidecar is unavailable")

    def _ensure_process(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            [self.python_executable, self.runner, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self._process = process
        self._status = "running"
        result_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._queue = result_queue
        self._reader = Thread(target=self._read_stdout, args=(process, result_queue), daemon=True)
        self._reader.start()
        return process

    def _read_stdout(
        self,
        process: subprocess.Popen[bytes],
        result_queue: queue.Queue[dict[str, Any] | None],
    ) -> None:
        assert process.stdout is not None
        try:
            for raw in iter(process.stdout.readline, b""):
                try:
                    item = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(item, dict):
                    result_queue.put(item)
        finally:
            result_queue.put(None)

    def _read_until_complete(self, request_id: str) -> list[dict[str, Any]]:
        deadline = monotonic() + self.timeout_seconds
        events: list[dict[str, Any]] = []
        while monotonic() < deadline:
            try:
                item = self._queue.get(timeout=max(0.01, deadline - monotonic()))
            except queue.Empty as exc:
                raise VoiceMemUnavailable("VoiceMem sidecar timed out") from exc
            if item is None:
                raise VoiceMemUnavailable("VoiceMem sidecar stopped")
            if item.get("request_id") != request_id:
                continue
            if item.get("type") == "request_complete":
                return events
            events.append(item)
        raise VoiceMemUnavailable("VoiceMem sidecar timed out")
