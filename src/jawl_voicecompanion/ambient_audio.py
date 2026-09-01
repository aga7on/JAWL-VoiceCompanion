"""System-audio to isolated VoiceMem/ambient-memory bridge."""

from __future__ import annotations

from array import array
import sys
from threading import RLock
from typing import Any

from .ambient_memory import AmbientMemoryBuffer
from .voicemem_client import VoiceMemUnavailable


class AmbientAudioASRBridge:
    """Consume loopback PCM without entering the microphone conversation path."""

    def __init__(
        self,
        voice_mem: Any,
        memory: AmbientMemoryBuffer,
        *,
        target_sample_rate: int = 16000,
        max_feed_bytes: int = 48 * 1024,
    ) -> None:
        if not hasattr(voice_mem, "feed_audio") or not hasattr(voice_mem, "end_audio"):
            raise TypeError("ambient ASR client must provide feed_audio and end_audio")
        if not isinstance(memory, AmbientMemoryBuffer):
            raise TypeError("ambient memory buffer is required")
        self.voice_mem = voice_mem
        self.memory = memory
        self.target_sample_rate = max(8000, min(int(target_sample_rate), 96000))
        self.max_feed_bytes = max(2048, min(int(max_feed_bytes), 48 * 1024)) & ~1
        self._lock = RLock()
        self._chunks = 0
        self._transcripts = 0
        self._dropped_events = 0
        self._last_error: str | None = None

    def consume(self, pcm16: bytes, sample_rate: int, channels: int, session_id: str) -> dict[str, Any]:
        try:
            converted = self._to_target_pcm(pcm16, sample_rate, channels, self.target_sample_rate)
            if not converted:
                return {"status": "ignored", "reason": "audio_chunk_empty"}
            events: list[dict[str, Any]] = []
            for start in range(0, len(converted), self.max_feed_bytes):
                chunk = converted[start : start + self.max_feed_bytes]
                events.extend(self.voice_mem.feed_audio(
                    chunk,
                    sample_rate=self.target_sample_rate,
                    session_id=self._session(session_id),
                ))
            ingested = self._ingest_final_events(events, session_id)
            with self._lock:
                self._chunks += 1
                self._last_error = None
            return {"status": "accepted", "events": len(events), "ingested": ingested}
        except Exception as exc:
            with self._lock:
                self._last_error = self._safe_error(exc)
            return {"status": "degraded", "error": self._last_error}

    def flush(self, session_id: str) -> dict[str, Any]:
        try:
            events = self.voice_mem.end_audio(session_id=self._session(session_id))
            ingested = self._ingest_final_events(events, session_id)
            with self._lock:
                self._last_error = None
            return {"status": "flushed", "events": len(events), "ingested": ingested}
        except Exception as exc:
            with self._lock:
                self._last_error = self._safe_error(exc)
            return {"status": "degraded", "error": self._last_error}

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "target_sample_rate": self.target_sample_rate,
                "max_feed_bytes": self.max_feed_bytes,
                "chunks": self._chunks,
                "transcripts": self._transcripts,
                "dropped_events": self._dropped_events,
                "last_error": self._last_error,
                "raw_audio_persisted": False,
                "conversation_turns_emitted": 0,
            }

    def _ingest_final_events(self, events: list[dict[str, Any]], session_id: str) -> int:
        count = 0
        for event in events:
            if not isinstance(event, dict) or event.get("type") != "VOICE_TURN":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or not str(payload.get("text") or "").strip():
                continue
            result = self.memory.ingest_system_audio(
                str(payload["text"]),
                confidence=payload.get("confidence", 0.7),
                event_id=str(event.get("event_id") or "") or None,
                session_id=self._session(session_id),
            )
            if result.get("status") == "retained":
                count += 1
                with self._lock:
                    self._transcripts += 1
            elif result.get("status") not in {"duplicate", "disabled"}:
                with self._lock:
                    self._dropped_events += 1
        return count

    @staticmethod
    def _to_target_pcm(pcm16: bytes, sample_rate: int, channels: int, target_sample_rate: int) -> bytes:
        if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) % 2:
            raise ValueError("ambient audio must be non-empty PCM16")
        if isinstance(sample_rate, bool) or not 8000 <= int(sample_rate) <= 96000:
            raise ValueError("ambient sample rate is unsupported")
        if isinstance(channels, bool) or not 1 <= int(channels) <= 2:
            raise ValueError("ambient channels must be 1 or 2")
        samples = array("h")
        samples.frombytes(pcm16)
        if sys.byteorder != "little":
            samples.byteswap()
        if channels == 2:
            mono = array("h", ((samples[index] + samples[index + 1]) // 2 for index in range(0, len(samples) - 1, 2)))
        else:
            mono = samples
        if int(sample_rate) == target_sample_rate:
            result = mono
        else:
            source_rate = int(sample_rate)
            count = max(1, int(len(mono) * target_sample_rate / source_rate))
            result = array("h")
            for index in range(count):
                source = index * source_rate / target_sample_rate
                left = min(int(source), len(mono) - 1)
                right = min(left + 1, len(mono) - 1)
                result.append(round(mono[left] + (mono[right] - mono[left]) * (source - left)))
        if sys.byteorder != "little":
            result.byteswap()
        return result.tobytes()

    @staticmethod
    def _session(session_id: str) -> str:
        return "ambient-audio:" + str(session_id or "ambient")[:160]

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, VoiceMemUnavailable):
            return "voicemem_unavailable"
        return f"{type(exc).__name__}: {str(exc)[:160]}"[:200]


__all__ = ["AmbientAudioASRBridge"]
