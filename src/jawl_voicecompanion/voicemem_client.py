"""Small subprocess client for the optional VoiceMem JSON-lines sidecar."""

from __future__ import annotations

import json
import base64
import os
import queue
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Any, Iterable
from uuid import uuid4


class VoiceMemUnavailable(ConnectionError):
    """Raised when the optional sidecar cannot answer a bounded request."""


@dataclass(frozen=True)
class _QueuedPartial:
    text: str
    ended: bool
    session_id: str


class VoiceMemProcessClient:
    """Lazily run one VoiceMem process and correlate its JSON-lines replies."""

    def __init__(
        self,
        python_executable: str | Path = sys.executable,
        *,
        runner: str | Path | None = None,
        args: Iterable[str] = (),
        timeout_seconds: float = 30.0,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self.python_executable = str(python_executable)
        self.runner = str(runner or root / "services" / "voicemem_sidecar.py")
        self.args = tuple(str(item) for item in args)
        # VoiceMem loads local E5/ASR/VAD lazily. A first real request can be
        # materially slower than a warmed turn, so a five-second default
        # would report a healthy sidecar as degraded during model startup.
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))
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

    def warmup(self, *, kind: str = "text") -> list[dict[str, Any]]:
        """Explicitly load VoiceMem's text or audio models before capture."""
        if kind not in {"text", "audio"}:
            raise ValueError("VoiceMem warmup kind must be text or audio")
        request_id = str(uuid4())
        return self._request({
            "schema_version": 1,
            "request_id": request_id,
            "type": "warmup",
            "kind": kind,
        }, request_id)

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
        result = replies[0] if replies else {"type": "health", "status": "degraded"}
        return {**result, "process": self.state()}

    def state(self) -> dict[str, Any]:
        """Return bounded process state without starting the sidecar."""
        with self._lock:
            process = self._process
            running = process is not None and process.poll() is None
            if process is not None and not running and self._status == "running":
                self._status = "degraded"
            return {
                "status": self._status,
                "running": running,
                "pid": process.pid if running else None,
            }

    def close(self) -> None:
        with self._lock:
            process = self._process
            reader = self._reader
            self._process = None
            self._reader = None
            self._status = "stopped"
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

    def abort(self) -> None:
        """Best-effort interrupt for a request running in another thread."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
        except OSError:
            pass

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
            with self._lock:
                if self._process is process and process.poll() is not None and self._status == "running":
                    self._status = "degraded"

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


class VoiceMemAsyncIngest:
    """Bounded background sink for non-critical VoiceMem memory updates."""

    def __init__(self, client: VoiceMemProcessClient, *, max_queue: int = 16) -> None:
        if not isinstance(client, VoiceMemProcessClient):
            raise TypeError("VoiceMemAsyncIngest requires a VoiceMemProcessClient")
        self.client = client
        self.max_queue = max(1, min(int(max_queue), 128))
        self._queue: queue.Queue[_QueuedPartial | None] = queue.Queue(maxsize=self.max_queue)
        self._lock = Lock()
        self._closed = False
        self._accepted = 0
        self._completed = 0
        self._failed = 0
        self._dropped = 0
        self._last_error: str | None = None
        self._thread = Thread(target=self._run, name="voicemem-memory-ingest", daemon=True)
        self._thread.start()

    def enqueue_partial(self, text: str, *, ended: bool = True, session_id: str = "local") -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("VoiceMem background text must be non-empty")
        if not isinstance(ended, bool):
            raise ValueError("ended must be boolean")
        item = _QueuedPartial(text[:12_000], ended, str(session_id or "local")[:200])
        with self._lock:
            if self._closed:
                self._dropped += 1
                return {"status": "dropped", "reason": "worker_closed", "queue_size": self._queue.qsize()}
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self._dropped += 1
                return {"status": "dropped", "reason": "queue_full", "queue_size": self._queue.qsize()}
            self._accepted += 1
            return {"status": "queued", "queue_size": self._queue.qsize()}

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "closed" if self._closed else ("running" if self._thread.is_alive() else "degraded"),
                "queue_size": self._queue.qsize(),
                "max_queue": self.max_queue,
                "accepted": self._accepted,
                "completed": self._completed,
                "failed": self._failed,
                "dropped": self._dropped,
                "last_error": self._last_error,
            }

    def wait_idle(self, timeout_seconds: float = 5.0) -> bool:
        """Wait for queued work in profiles/tests without exposing it to HTTP."""
        deadline = monotonic() + max(0.0, min(float(timeout_seconds), 120.0))
        while monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self, *, timeout_seconds: float = 2.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._queue.task_done()
                    self._dropped += 1
            self._queue.put_nowait(None)
        self._thread.join(timeout=max(0.1, min(float(timeout_seconds), 10.0)))
        if self._thread.is_alive():
            self.client.abort()
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                try:
                    self.client.feed_partial(item.text, ended=item.ended, session_id=item.session_id)
                except Exception as exc:  # noqa: BLE001 - state reports provider failure
                    with self._lock:
                        self._failed += 1
                        self._last_error = f"{type(exc).__name__}: {str(exc)[:160]}"[:200]
                else:
                    with self._lock:
                        self._completed += 1
                        self._last_error = None
            finally:
                self._queue.task_done()
