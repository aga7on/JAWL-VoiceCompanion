"""Bounded external ASR adapter and final-utterance audio buffer.

The local llama.cpp audio endpoint is a transcription API, not a guaranteed
streaming partial-ASR API.  Keep that distinction explicit: VoiceMem remains
the default streaming path, while this module provides an opt-in final
utterance bridge for providers such as Qwen3-ASR.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
import wave
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


MAX_ASR_AUDIO_BYTES = 8 * 1024 * 1024
MAX_UTTERANCE_BYTES = 4 * 1024 * 1024
MAX_ASR_TEXT_CHARS = 12_000
MAX_ASR_SESSIONS = 8
SESSION_TTL_SECONDS = 120.0
DEFAULT_TRANSCRIPTION_PROMPT = "Transcribe the audio exactly as spoken."


class ASRUnavailable(ConnectionError):
    """The selected ASR provider is unavailable or returned an invalid reply."""


def _transcription_url(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("ASR endpoint is required")
    if endpoint.endswith("/audio/transcriptions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return f"{endpoint}/audio/transcriptions"
    return f"{endpoint}/v1/audio/transcriptions"


def _health_url(transcription_url: str) -> str:
    marker = "/v1/"
    root = transcription_url.split(marker, 1)[0] if marker in transcription_url else transcription_url.rsplit("/audio/transcriptions", 1)[0]
    return f"{root}/health"


class OpenAICompatibleASRClient:
    """Minimal dependency-free client for OpenAI-compatible audio endpoints."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str = "",
        timeout_seconds: float = 30.0,
        max_audio_bytes: int = MAX_ASR_AUDIO_BYTES,
        prompt: str = DEFAULT_TRANSCRIPTION_PROMPT,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = _transcription_url(endpoint)
        self.model = str(model or "").strip()
        if not self.model:
            raise ValueError("ASR model is required")
        self.api_key = str(api_key or "")
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 180.0))
        self.max_audio_bytes = max(64 * 1024, min(int(max_audio_bytes), MAX_ASR_AUDIO_BYTES))
        self.prompt = str(prompt or "").strip()[:1200]
        self._opener = opener

    def health(self) -> dict[str, Any]:
        request = Request(_health_url(self.endpoint), method="GET")
        try:
            with self._opener(request, timeout=min(self.timeout_seconds, 10.0)) as response:
                payload = json.loads(response.read(16 * 1024).decode("utf-8"))
        except (HTTPError, URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return {"status": "offline", "mode": "final_utterance"}
        status = payload.get("status") if isinstance(payload, dict) else None
        return {
            "status": "online" if status == "ok" else "degraded",
            "mode": "final_utterance",
            "model": self.model,
        }

    def transcribe(self, wav_bytes: bytes, *, filename: str = "utterance.wav") -> str:
        if not isinstance(wav_bytes, bytes) or not wav_bytes or len(wav_bytes) > self.max_audio_bytes:
            raise ValueError("ASR WAV must be non-empty and within the configured byte limit")
        boundary = f"----JAWLVoiceCompanion{uuid4().hex}"
        body = self._multipart(boundary, wav_bytes, filename)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(128 * 1024).decode("utf-8"))
        except HTTPError as exc:
            raise ASRUnavailable(f"ASR endpoint returned HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise ASRUnavailable("ASR endpoint is unavailable") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ASRUnavailable("ASR endpoint returned invalid JSON") from exc
        text = self._extract_text(payload)
        if not text:
            raise ASRUnavailable("ASR endpoint returned empty text")
        return text[:MAX_ASR_TEXT_CHARS]

    def _multipart(self, boundary: str, wav_bytes: bytes, filename: str) -> bytes:
        safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", str(filename or "utterance.wav"))[:80] or "utterance.wav"
        delimiter = f"--{boundary}".encode("ascii")
        chunks = [
            delimiter + b"\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n",
            self.model.encode("utf-8") + b"\r\n",
        ]
        if self.prompt:
            chunks.extend([
                delimiter + b"\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\n",
                self.prompt.encode("utf-8") + b"\r\n",
            ])
        chunks.extend([
            delimiter + b"\r\n",
            (
                f'Content-Disposition: form-data; name="file"; filename="{safe_filename}"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("ascii"),
            wav_bytes,
            b"\r\n" + delimiter + b"--\r\n",
        ])
        return b"".join(chunks)

    @staticmethod
    def _extract_text(payload: Any) -> str:
        text = ""
        if isinstance(payload, dict):
            direct = payload.get("text")
            if isinstance(direct, str):
                text = direct
            else:
                choices = payload.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    message = choices[0].get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        text = message["content"]
        text = re.sub(r"^\s*language\s+[A-Za-z-]+\s*", "", text, flags=re.IGNORECASE)
        return text.replace("<asr_text>", "").replace("</asr_text>", "").strip()


@dataclass
class _AudioSession:
    sample_rate: int
    channels: int
    data: bytearray
    touched_at: float


class ExternalASRService:
    """Collect bounded PCM16 sessions and transcribe only on explicit end."""

    def __init__(
        self,
        provider: OpenAICompatibleASRClient,
        *,
        max_utterance_bytes: int = MAX_UTTERANCE_BYTES,
        session_ttl_seconds: float = SESSION_TTL_SECONDS,
    ) -> None:
        self.provider = provider
        self.max_utterance_bytes = max(32 * 1024, min(int(max_utterance_bytes), MAX_UTTERANCE_BYTES)) & ~1
        self.session_ttl_seconds = max(10.0, min(float(session_ttl_seconds), 600.0))
        self._sessions: dict[str, _AudioSession] = {}
        self._lock = threading.RLock()

    def feed_audio(self, pcm16: bytes, *, sample_rate: int, channels: int, session_id: str) -> dict[str, Any]:
        self._validate_audio(pcm16, sample_rate, channels)
        session = str(session_id or "local")[:200]
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            current = self._sessions.get(session)
            if current is None:
                if len(self._sessions) >= MAX_ASR_SESSIONS:
                    raise ValueError("ASR session limit reached")
                current = _AudioSession(int(sample_rate), int(channels), bytearray(), now)
                self._sessions[session] = current
            if (current.sample_rate, current.channels) != (int(sample_rate), int(channels)):
                raise ValueError("audio format cannot change during an ASR utterance")
            if len(current.data) + len(pcm16) > self.max_utterance_bytes:
                self._sessions.pop(session, None)
                raise ValueError("ASR utterance exceeds configured byte limit")
            current.data.extend(pcm16)
            current.touched_at = now
            return {
                "status": "buffered",
                "mode": "final_utterance",
                "bytes": len(current.data),
                "sample_rate": current.sample_rate,
                "channels": current.channels,
                "raw_audio_persisted": False,
            }

    def finish(self, session_id: str) -> dict[str, Any]:
        session = str(session_id or "local")[:200]
        with self._lock:
            current = self._sessions.pop(session, None)
        if current is None or not current.data:
            return {"status": "empty", "text": "", "raw_audio_persisted": False}
        wav_bytes = self._wav(current)
        text = self.provider.transcribe(wav_bytes)
        return {
            "status": "transcribed",
            "text": text[:MAX_ASR_TEXT_CHARS],
            "bytes": len(current.data),
            "raw_audio_persisted": False,
        }

    def health(self) -> dict[str, Any]:
        result = self.provider.health()
        return {"configured": True, **result, "active_sessions": self.state()["active_sessions"]}

    def state(self) -> dict[str, Any]:
        with self._lock:
            self._expire(time.monotonic())
            return {
                "configured": True,
                "mode": "final_utterance",
                "active_sessions": len(self._sessions),
                "buffered_bytes": sum(len(item.data) for item in self._sessions.values()),
                "max_utterance_bytes": self.max_utterance_bytes,
                "raw_audio_persisted": False,
            }

    def close(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _expire(self, now: float) -> None:
        expired = [key for key, item in self._sessions.items() if now - item.touched_at > self.session_ttl_seconds]
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


__all__ = [
    "ASRUnavailable",
    "DEFAULT_TRANSCRIPTION_PROMPT",
    "ExternalASRService",
    "OpenAICompatibleASRClient",
]
