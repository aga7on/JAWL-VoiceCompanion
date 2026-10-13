"""Bounded GigaAM partial lane; final transcripts still use UtteranceBuffer.

Raw-PCM worker output has no acknowledged reset/correlation. A different
capture/utterance reaps the owned child before starting another. Real-model
warm-start latency of this correctness boundary still requires measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import queue
import subprocess
import threading
import time
from .owned_pipe import spawn_owned_pipe
from typing import Any

SR = 16000
MAX_PCM_BYTES = 48 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_TEXT_CHARS = 4000
MAX_QUEUED_CHUNKS = 8


@dataclass
class _StreamRun:
    process: Any
    scope_id: str
    session_id: str
    generation: int
    cancel: threading.Event | None
    stop: threading.Event = field(default_factory=threading.Event)
    audio: queue.Queue = field(default_factory=lambda: queue.Queue(MAX_QUEUED_CHUNKS))
    threads: list[threading.Thread] = field(default_factory=list)
    failed: bool = False


class StreamingASRBridge:
    def __init__(self, executable: str, model: str, *, backend: str = "gigaam",
                 step_ms: int = 500, final_on_silence_ms: int = 800,
                 idle_seconds: float = 45.0) -> None:
        self.executable, self.model, self.backend = str(executable), str(model), str(backend)
        self.step_ms = max(200, min(int(step_ms), 3000))
        self.final_on_silence_ms = max(0, min(int(final_on_silence_ms), 5000))
        self.idle_seconds = max(10.0, min(float(idle_seconds), 600.0))
        self._lifecycle = threading.RLock()
        self._lock = threading.Lock()
        self._run: _StreamRun | None = None
        self._process: subprocess.Popen | None = None
        self._generation = 0
        self._failed = self._closed = False
        self._clear_state()

    def _clear_state(self) -> None:
        self.utterance_id = 0
        self.partial_text = self.final_text = ""
        self.last_partial_at = self.last_audio_at = 0.0
        self.silence_ms = self.fed_seconds = self.split_seconds = 0.0

    @property
    def disabled(self) -> bool:
        return self._failed or self._closed

    def _ensure_started(self, scope_id: str = "legacy", session_id: str = "legacy",
                        cancel_event: threading.Event | None = None) -> bool:
        with self._lifecycle:
            if self.disabled or (cancel_event is not None and cancel_event.is_set()):
                return False
            previous = self._run
            if previous is not None:
                if ((previous.scope_id, previous.session_id) == (scope_id, session_id)
                        and previous.cancel is cancel_event and not previous.stop.is_set()
                        and previous.process.poll() is None):
                    return True
                if not self._stop_run(previous):
                    return False
                if self._failed:
                    return False  # An explicit reset, not a feed loop, retries failures.
            try:
                process = spawn_owned_pipe(
                    [self.executable, "--backend", self.backend, "-m", self.model,
                     "--stream", "--stream-json", "--stream-step", str(self.step_ms),
                     "--stream-final-on-silence-ms", str(self.final_on_silence_ms)],
                    bufsize=0,
                )
            except OSError:
                self._failed = True
                return False
            with self._lock:
                self._generation += 1
                run = _StreamRun(process, scope_id, session_id, self._generation, cancel_event)
                self._run, self._process = run, process
                self._clear_state()
                self.last_audio_at = time.monotonic()
            try:
                for target in (self._read_loop, self._write_loop, self._watch_loop):
                    worker = threading.Thread(target=target, args=(run,), daemon=True,
                                              name="streaming-asr")
                    worker.start()
                    run.threads.append(worker)
            except RuntimeError:
                run.failed = True
                self._stop_run(run)
                self._failed = True
                return False
            return True

    def _stop_run(self, run: _StreamRun) -> bool:
        """Lifecycle lock held: detach state before waking stale readers."""
        with self._lock:
            if self._run is not run:
                return run.process.poll() is not None
            run.stop.set()
            self._run = None
            self._clear_state()
        process = run.process
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None or getattr(process, 'cleanup_pending', False):
                    # Fail closed: retain the child for a later reap attempt.
                    with self._lock:
                        self._run, self._process = run, process
                        self._failed = True
                    return False
        for worker in run.threads:
            if worker is not threading.current_thread():
                worker.join(timeout=0.2)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        while True:
            try:
                run.audio.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            self._process = None  # Reap completed, not just a detached reader.
            self._failed = run.failed
        return True

    def close(self) -> None:
        with self._lifecycle:
            self._closed = True
            if self._run is not None:
                self._stop_run(self._run)

    def reset_utterance(self, *, scope_id: str | None = None,
                        session_id: str | None = None) -> None:
        with self._lifecycle:
            run = self._run
            if run is not None:
                if ((scope_id is not None and run.scope_id != scope_id)
                        or (session_id is not None and run.session_id != session_id)):
                    return
                if not self._stop_run(run):
                    return
            with self._lock:
                self._clear_state()
                self._failed = False

    def discard_scope(self, scope_id: str) -> dict[str, Any]:
        self.reset_utterance(scope_id=scope_id)
        return {"status": "discarded", "scope_id": scope_id}

    def _watch_loop(self, run: _StreamRun) -> None:
        while not run.stop.wait(0.05):
            with self._lock:
                if self._run is not run:
                    return
                idle = time.monotonic() - self.last_audio_at >= self.idle_seconds
            if idle or (run.cancel is not None and run.cancel.is_set()):
                break
        while not self._lifecycle.acquire(timeout=0.05):
            with self._lock:
                if self._run is not run:
                    return
        try:
            if self._run is run:
                self._stop_run(run)
        finally:
            self._lifecycle.release()

    def feed(self, pcm16: bytes, sample_rate: int = SR, channels: int = 1, *,
             scope_id: str = "legacy", session_id: str = "legacy",
             cancel_event: threading.Event | None = None) -> bool:
        if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) > MAX_PCM_BYTES or len(pcm16) % 2:
            raise ValueError("streaming PCM must be non-empty even bytes, at most 48 KiB")
        if (isinstance(sample_rate, bool) or not isinstance(sample_rate, int)
                or not 8000 <= sample_rate <= 192000 or isinstance(channels, bool)
                or not isinstance(channels, int) or not 1 <= channels <= 8
                or len(pcm16) % (2 * channels)):
            raise ValueError("invalid streaming audio format")
        for identity in (scope_id, session_id):
            if not isinstance(identity, str) or not identity or len(identity) > 200:
                raise ValueError("invalid streaming scope/session identity")
        mono = self._to_mono16k(pcm16, sample_rate, channels)
        if not mono or len(mono) > MAX_PCM_BYTES * 2:
            raise ValueError("resampled streaming chunk exceeds byte limit")
        with self._lifecycle:
            if not self._ensure_started(scope_id, session_id, cancel_event):
                return False
            run = self._run
            if run.stop.is_set() or (cancel_event is not None and cancel_event.is_set()):
                self._stop_run(run)
                return False
            try:
                run.audio.put_nowait(mono)
            except queue.Full:
                run.failed = True
                self._stop_run(run)
                return False
            with self._lock:
                self.last_audio_at = time.monotonic()
            return True

    def _write_loop(self, run: _StreamRun) -> None:
        try:
            while not run.stop.is_set():
                try:
                    mono = run.audio.get(timeout=0.05)
                except queue.Empty:
                    continue
                sent = 0
                while sent < len(mono) and not run.stop.is_set():
                    count = run.process.stdin.write(mono[sent:])
                    if not count:
                        raise OSError("streaming worker input closed")
                    sent += count
                with self._lock:
                    if self._run is run:
                        self.fed_seconds += sent / 2 / SR
        except (OSError, ValueError):
            with self._lock:
                if self._run is run and not run.stop.is_set():
                    run.failed = True
                    run.stop.set()

    @staticmethod
    def _to_mono16k(pcm16: bytes, sample_rate: int, channels: int) -> bytes:
        if sample_rate == SR and channels == 1:
            return pcm16
        import numpy as np
        samples = np.frombuffer(pcm16, dtype="<i2")
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype("<i2")
        if sample_rate != SR and len(samples):
            n = int(len(samples) * SR / sample_rate)
            samples = np.interp(np.linspace(0, len(samples) - 1, n),
                                np.arange(len(samples)), samples).astype("<i2")
        return samples.tobytes()

    def _read_loop(self, run: _StreamRun) -> None:
        try:
            while not run.stop.is_set():
                raw = run.process.stdout.readline(MAX_EVENT_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_EVENT_BYTES:
                    run.failed = True
                    break
                try:
                    event = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError, RecursionError):
                    continue
                self._apply_event(event, run)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                if self._run is run and not run.stop.is_set():
                    run.failed = True
                    run.stop.set()

    def _apply_event(self, event: Any, run: _StreamRun | None = None) -> None:
        if not isinstance(event, dict):
            return
        kind, text = event.get("type"), event.get("text", "")
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
            return
        t1 = event.get("t1", 0.0)
        if isinstance(t1, bool) or not isinstance(t1, (int, float)):
            return
        try:
            if not math.isfinite(t1) or t1 < 0:
                return
        except OverflowError:
            return
        utterance = event.get("utterance_id", 0)
        if isinstance(utterance, bool) or not isinstance(utterance, int) or not 0 <= utterance <= 2**31 - 1:
            return
        with self._lock:
            if run is not None and (self._run is not run or run.stop.is_set()
                                    or (run.cancel is not None and run.cancel.is_set())):
                return
            if kind == "partial" and text.strip():
                self.partial_text = text.strip()
                self.last_partial_at = time.monotonic()
                self.split_seconds = float(t1)
                self.silence_ms = max(0.0, (self.fed_seconds - t1) * 1000)
            elif kind == "final":
                self.utterance_id = utterance or self.utterance_id
                if text.strip():
                    self.final_text = self.partial_text = text.strip()
            elif kind == "silence":
                self.silence_ms = max(0.0, (self.fed_seconds - self.split_seconds) * 1000)

    def snapshot(self, *, scope_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        with self._lifecycle:
            run = self._run
            if run is not None and run.cancel is not None and run.cancel.is_set():
                self._stop_run(run)
                run = self._run
            with self._lock:
                matches = run is None or ((scope_id is None or run.scope_id == scope_id)
                                         and (session_id is None or run.session_id == session_id))
                if not matches or (run is None and (scope_id is not None or session_id is not None)):
                    return {"active": False, "text": "", "final_text": "", "silence_ms": 0.0,
                            "utterance_id": 0, "scope_id": None, "session_id": None,
                            "generation": self._generation}
                silence = max(self.silence_ms, (self.fed_seconds - self.split_seconds) * 1000)
                return {"active": run is not None and not self.disabled and not run.stop.is_set(),
                        "text": self.partial_text, "final_text": self.final_text,
                        "silence_ms": round(silence, 1), "utterance_id": self.utterance_id,
                        "scope_id": run.scope_id if run else None,
                        "session_id": run.session_id if run else None, "generation": self._generation}


__all__ = ["StreamingASRBridge", "SR"]
