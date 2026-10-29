"""Bounded per-session utterance buffer for the canonical GigaAM ASR.

GigaAM (crispasr, file mode) is the **only** ASR engine in this product (owner
decision 2026-09-21): the OpenAI-compatible provider path
(``--asr-url``/``--asr-model``, Qwen3-ASR and whisper backends) and its
"fallback" lane were removed, because GigaAM already won the head-to-head
(0.58 s vs 1.19 s on the same clip, more accurate Russian) and the fallback
pointed at a server the daily profile never starts.

What remains here is not a model client: this is the bounded PCM16 buffer the
browser voice lane and the ambient bridge fill, plus the WAV packaging the
canonical transcriber consumes once per utterance.
"""

from __future__ import annotations

import io
import threading
import time
import wave
from dataclasses import dataclass
from typing import Any, Callable

MAX_UTTERANCE_BYTES = 4 * 1024 * 1024
MAX_ASR_TEXT_CHARS = 12_000
MAX_ASR_SESSIONS = 8
SESSION_TTL_SECONDS = 120.0


@dataclass
class _AudioSession:
    sample_rate: int
    channels: int
    data: bytearray
    touched_at: float
    cancel: _ASRCancellation


class _ASRCancellation(threading.Event):
    """Per-utterance cancellation, optionally linked to a capture lease."""

    def __init__(self, parent: threading.Event | None = None) -> None:
        super().__init__()
        self.parent = parent

    def is_set(self) -> bool:
        return super().is_set() or (self.parent is not None and self.parent.is_set())


class UtteranceBuffer:
    """Collect bounded PCM16 sessions and transcribe them with GigaAM on end."""

    def __init__(
        self,
        transcriber: Any | None = None,
        *,
        max_utterance_bytes: int = MAX_UTTERANCE_BYTES,
        session_ttl_seconds: float = SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # ``transcriber`` is the canonical GigaAM batch transcriber
        # (giga_final.CrispASRFileTranscriber). There is deliberately no second
        # engine and no provider fallback behind it.
        self.transcriber = transcriber
        self.max_utterance_bytes = max(32 * 1024, min(int(max_utterance_bytes), MAX_UTTERANCE_BYTES)) & ~1
        self.session_ttl_seconds = max(10.0, min(float(session_ttl_seconds), 600.0))
        self._clock = clock
        self._sessions: dict[tuple[str, str], _AudioSession] = {}
        self._inflight: dict[tuple[str, str], _ASRCancellation] = {}
        self._closed = False
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        return self.transcriber is not None

    @staticmethod
    def _key(session_id: str, scope_id: str = "") -> tuple[str, str]:
        return str(scope_id)[:200], str(session_id or "local")[:200]

    def feed_audio(
        self, pcm16: bytes, *, sample_rate: int, channels: int, session_id: str,
        scope_id: str = "", cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        self._validate_audio(pcm16, sample_rate, channels)
        session = self._key(session_id, scope_id)
        now = self._clock()
        with self._lock:
            if self._closed:
                raise ValueError("ASR buffer is closed")
            if cancel_event is not None and cancel_event.is_set():
                raise ValueError("ASR capture is cancelled")
            self._expire(now)
            if session in self._inflight:
                raise ValueError("ASR utterance is still processing")
            current = self._sessions.get(session)
            if current is None:
                if len(self._sessions) + len(self._inflight) >= MAX_ASR_SESSIONS:
                    raise ValueError("ASR session limit reached")
                current = _AudioSession(
                    int(sample_rate), int(channels), bytearray(), now, _ASRCancellation(cancel_event),
                )
                self._sessions[session] = current
            if current.cancel.is_set():
                self._sessions.pop(session, None)
                raise ValueError("ASR capture is cancelled")
            if (current.sample_rate, current.channels) != (int(sample_rate), int(channels)):
                raise ValueError("audio format cannot change during an ASR utterance")
            if len(current.data) + len(pcm16) > self.max_utterance_bytes:
                self._sessions.pop(session, None)
                raise ValueError("ASR utterance exceeds configured byte limit")
            current.data.extend(pcm16)
            current.touched_at = now
            return {
                "status": "buffered",
                "mode": "gigaam_final",
                "bytes": len(current.data),
                "sample_rate": current.sample_rate,
                "channels": current.channels,
                "raw_audio_persisted": False,
            }

    def finish(
        self, session_id: str, *, scope_id: str = "", analyze_delivery: bool = False,
    ) -> dict[str, Any]:
        """Transcribe the buffered utterance with GigaAM and clear the session.

        Explicit by design: a missing transcriber or a transcriber failure is
        reported as ``unavailable``/``failed`` instead of being masked by a
        second engine.
        """
        session = self._key(session_id, scope_id)
        with self._lock:
            current = self._sessions.pop(session, None)
            if current is not None and current.data:
                self._inflight[session] = current.cancel
        if current is None or not current.data:
            return {"status": "empty", "text": "", "raw_audio_persisted": False}
        try:
            if current.cancel.is_set():
                return self._cancelled(current)
            if self.transcriber is None:
                return {
                    "status": "unavailable", "text": "", "bytes": len(current.data),
                    "error": "GigaAM transcriber is not configured", "raw_audio_persisted": False,
                }
            try:
                text = str(self.transcriber.transcribe(self._wav(current), cancel_event=current.cancel) or "").strip()
            except Exception as exc:  # noqa: BLE001 - the caller reports the failure
                if current.cancel.is_set():
                    return self._cancelled(current)
                return {
                    "status": "failed", "text": "", "bytes": len(current.data),
                    "error": f"{type(exc).__name__}: {exc}"[:300], "raw_audio_persisted": False,
                }
            if current.cancel.is_set():
                return self._cancelled(current)
        finally:
            with self._lock:
                self._inflight.pop(session, None)
        if not text:
            return {"status": "no_speech", "text": "", "bytes": len(current.data), "raw_audio_persisted": False}
        result = {
            "status": "transcribed",
            "text": text[:MAX_ASR_TEXT_CHARS],
            "bytes": len(current.data),
            "raw_audio_persisted": False,
        }
        if analyze_delivery:
            # Ambient loopback callers keep the default off; only the direct
            # microphone turn opts in, so external media is not attributed to
            # the user's vocal delivery.
            try:
                from .voice_delivery import analyze_voice_delivery
                delivery = analyze_voice_delivery(
                    bytes(current.data), current.sample_rate, current.channels,
                    observed_monotonic=current.touched_at,
                )
            except Exception:  # noqa: BLE001 - optional measurements cannot break ASR
                delivery = None
            if delivery is not None:
                result["voice_delivery"] = delivery
        return result

    def finish_microphone(self, session_id: str, *, scope_id: str = "") -> dict[str, Any]:
        """Finish a direct-mic turn and attach optional objective voice cues."""
        return self.finish(session_id, scope_id=scope_id, analyze_delivery=True)

    @staticmethod
    def _cancelled(current: _AudioSession) -> dict[str, Any]:
        return {"status": "cancelled", "text": "", "bytes": len(current.data), "raw_audio_persisted": False}

    def to_wav(self, session_id: str, *, scope_id: str = "") -> bytes | None:
        """Peek the buffered utterance as WAV bytes without clearing it."""
        session = self._key(session_id, scope_id)
        with self._lock:
            current = self._sessions.get(session)
            if current is None or not current.data:
                return None
            return self._wav(current)

    def discard(self, session_id: str, *, scope_id: str = "") -> dict[str, Any]:
        """Drop buffered PCM and cancel only this utterance's active process."""
        session = self._key(session_id, scope_id)
        with self._lock:
            current = self._sessions.pop(session, None)
            cancel = self._inflight.get(session)
            if cancel is not None:
                cancel.set()
        return {
            "status": "cancelled" if cancel is not None else "discarded" if current is not None else "empty",
            "bytes": len(current.data) if current is not None else 0,
            "raw_audio_persisted": False,
        }

    def discard_scope(self, scope_id: str) -> dict[str, Any]:
        """Release one capture owner without touching microphone/ambient peers."""
        scope = str(scope_id)[:200]
        with self._lock:
            keys = [key for key in self._sessions if key[0] == scope]
            for key in keys:
                self._sessions.pop(key)
            cancelled = 0
            for key, cancel in self._inflight.items():
                if key[0] == scope:
                    cancel.set()
                    cancelled += 1
        return {"status": "cancelled", "discarded_sessions": len(keys), "cancelled_transcriptions": cancelled}

    def health(self) -> dict[str, Any]:
        state = self.state()
        return {
            "configured": self.configured,
            "status": "ok" if self.configured else "not_configured",
            "engine": "gigaam",
            "mode": "gigaam_final",
            **state,
        }

    def state(self) -> dict[str, Any]:
        with self._lock:
            self._expire(self._clock())
            return {
                "active_sessions": len(self._sessions),
                "inflight_transcriptions": len(self._inflight),
                "buffered_bytes": sum(len(item.data) for item in self._sessions.values()),
                "max_utterance_bytes": self.max_utterance_bytes,
                "raw_audio_persisted": False,
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._sessions.clear()
            for cancel in self._inflight.values():
                cancel.set()

    def _expire(self, now: float) -> None:
        expired = [
            key for key, item in self._sessions.items()
            if item.cancel.is_set() or now - item.touched_at > self.session_ttl_seconds
        ]
        for key in expired:
            self._sessions.pop(key, None)

    @staticmethod
    def _validate_audio(pcm16: bytes, sample_rate: int, channels: int) -> None:
        if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) % 2:
            raise ValueError("audio must be non-empty PCM16")
        if isinstance(sample_rate, bool) or not 8000 <= int(sample_rate) <= 96000:
            raise ValueError("sample_rate must be between 8000 and 96000")
        if isinstance(channels, bool) or not 1 <= int(channels) <= 2:
            raise ValueError("channels must be 1 or 2")

    @staticmethod
    def _wav(session: _AudioSession) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(session.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(session.sample_rate)
            wav_file.writeframes(session.data)
        return output.getvalue()


__all__ = ["MAX_UTTERANCE_BYTES", "UtteranceBuffer"]
