"""Streaming ASR bridge: CrispASR (GigaAM) subprocess behind the voice lane.

The bridge feeds browser PCM chunks into a persistent ``crispasr --stream
--stream-json`` process and keeps the latest partial transcript / silence
timing. The adaptive turn policy consumes its snapshots; the canonical final
transcript still comes from the high-quality ASR worker (Qwen3-ASR) via
``/api/voice/end``.

Lifecycle: lazily started on the first audio chunk, closed after
``idle_seconds`` without audio. Fail-soft: any spawn/read error disables the
bridge and the caller falls back to the previous draft path.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any

SR = 16000


class StreamingASRBridge:
    def __init__(
        self,
        executable: str,
        model: str,
        *,
        backend: str = "gigaam",
        step_ms: int = 500,
        final_on_silence_ms: int = 800,
        idle_seconds: float = 45.0,
    ) -> None:
        self.executable = str(executable)
        self.model = str(model)
        self.backend = str(backend)
        self.step_ms = max(200, min(int(step_ms), 3000))
        self.final_on_silence_ms = max(0, min(int(final_on_silence_ms), 5000))
        self.idle_seconds = max(10.0, float(idle_seconds))
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._idle_thread: threading.Thread | None = None
        self._failed = False
        # state
        self.utterance_id = 0
        self.partial_text = ""
        self.final_text = ""
        self.last_partial_at = 0.0
        self.last_audio_at = 0.0
        self.silence_ms = 0.0
        self.fed_seconds = 0.0
        self.split_seconds = 0.0

    # -- lifecycle ---------------------------------------------------------

    @property
    def disabled(self) -> bool:
        return self._failed

    def _ensure_started(self) -> bool:
        if self._failed:
            return False
        if self._process is not None and self._process.poll() is None:
            return True
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return True
            try:
                self._process = subprocess.Popen(
                    [
                        self.executable,
                        "--backend", self.backend,
                        "-m", self.model,
                        "--stream", "--stream-json",
                        "--stream-step", str(self.step_ms),
                        "--stream-final-on-silence-ms", str(self.final_on_silence_ms),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
            except OSError:
                self._failed = True
                return False
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
            self._idle_thread.start()
            return True

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def _idle_loop(self) -> None:
        while True:
            time.sleep(5.0)
            if self._process is None:
                return
            if time.monotonic() - self.last_audio_at > self.idle_seconds:
                self.reset_utterance()
                self.close()
                return

    # -- io ----------------------------------------------------------------

    def feed(self, pcm16: bytes, sample_rate: int = SR, channels: int = 1) -> None:
        """Feed s16le PCM; performs naive downmix/resample when needed."""
        if self._failed or not pcm16:
            return
        if not self._ensure_started():
            return
        mono = self._to_mono16k(pcm16, sample_rate, channels)
        if not mono:
            return
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return
        try:
            process.stdin.write(mono)
            process.stdin.flush()
            now = time.monotonic()
            with self._lock:
                self.last_audio_at = now
                self.fed_seconds += len(mono) / 2 / SR
        except (OSError, ValueError):
            self._failed = True

    @staticmethod
    def _to_mono16k(pcm16: bytes, sample_rate: int, channels: int) -> bytes:
        import numpy as np  # local import: bridge stays optional

        samples = np.frombuffer(pcm16, dtype="<i2")
        if channels > 1:
            samples = samples[: len(samples) - len(samples) % channels]
            samples = samples.reshape(-1, channels).mean(axis=1).astype("<i2")
        if sample_rate != SR and sample_rate > 0:
            n = int(len(samples) * SR / sample_rate)
            idx = np.linspace(0, len(samples) - 1, n) if n > 0 else []
            samples = np.interp(idx, np.arange(len(samples)), samples).astype("<i2")
        return samples.tobytes()

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for raw in process.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._apply_event(event)
        except (OSError, ValueError):
            pass
        finally:
            self._failed = True

    def _apply_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        now = time.monotonic()
        with self._lock:
            if kind == "partial":
                text = str(event.get("text") or "").strip()
                if text:
                    self.partial_text = text
                    self.last_partial_at = now
                    t1 = float(event.get("t1") or 0.0)
                    self.split_seconds = t1
                    self.silence_ms = max(0.0, (self.fed_seconds - t1) * 1000.0)
            elif kind == "final":
                self.utterance_id = int(event.get("utterance_id") or self.utterance_id)
                final = str(event.get("text") or "").strip()
                if final:
                    self.final_text = final
                    self.partial_text = final
            elif kind == "silence":
                self.silence_ms = max(0.0, (self.fed_seconds - self.split_seconds) * 1000.0)

    # -- snapshots ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            silence = self.silence_ms
            if self.fed_seconds > self.split_seconds:
                silence = max(silence, (self.fed_seconds - self.split_seconds) * 1000.0)
            return {
                "active": self._process is not None and not self._failed,
                "text": self.partial_text,
                "final_text": self.final_text,
                "silence_ms": round(silence, 1),
                "utterance_id": self.utterance_id,
            }

    def reset_utterance(self) -> None:
        with self._lock:
            self.partial_text = ""
            self.final_text = ""
            self.split_seconds = self.fed_seconds
            self.silence_ms = 0.0


__all__ = ["StreamingASRBridge", "SR"]
