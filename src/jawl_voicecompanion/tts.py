"""Small, replaceable and cancellable TTS boundary."""

from __future__ import annotations

import io
import json
import re
import threading
import wave
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_TTS_CHARS = 4_000
MAX_AUDIO_BYTES = 8 * 1024 * 1024


class TTSUnavailable(ConnectionError):
    """The selected TTS provider is not available or returned invalid audio."""


class TTSCancelled(RuntimeError):
    """A newer speech request superseded this synthesis."""


class TTSProvider(Protocol):
    def synthesize(
        self, text: str, *, voice: str | None = None, speed: float = 1.0,
        cancel_event: threading.Event | None = None,
    ) -> bytes: ...


def split_sentences(text: str, max_chars: int = 500) -> list[str]:
    """Split bounded display text while retaining punctuation for TTS."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    pieces = [part.strip() for part in re.split(r"(?<=[.!?。！？…])\s+", clean) if part.strip()]
    result: list[str] = []
    for piece in pieces:
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars + 1)
            cut = cut if cut > 0 else max_chars
            result.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            result.append(piece)
    return result


class CozyVoiceHttpClient:
    """Adapter for the local CozyVoice ``rest_api.py`` wrapper."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 120.0, max_audio_bytes: int = MAX_AUDIO_BYTES):
        self.base_url = str(base_url).rstrip("/")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self.max_audio_bytes = max(64 * 1024, min(int(max_audio_bytes), MAX_AUDIO_BYTES))

    def health(self) -> dict[str, Any]:
        try:
            request = Request(f"{self.base_url}/health", method="GET")
            with urlopen(request, timeout=min(self.timeout_seconds, 10.0)) as response:
                value = json.loads(response.read(16 * 1024).decode("utf-8"))
            return value if isinstance(value, dict) else {"status": "degraded"}
        except (OSError, ValueError, json.JSONDecodeError):
            return {"status": "offline"}

    def synthesize(
        self, text: str, *, voice: str | None = None, speed: float = 1.0,
        cancel_event: threading.Event | None = None,
    ) -> bytes:
        text = str(text or "").strip()
        if not text or len(text) > MAX_TTS_CHARS:
            raise ValueError("TTS text must be non-empty and at most 4000 characters")
        speed = float(speed)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0")
        chunks = [self._request_sentence(part, voice, speed, cancel_event) for part in split_sentences(text)]
        if not chunks:
            raise ValueError("TTS text contains no speakable sentence")
        return _merge_wav(chunks, self.max_audio_bytes)

    def _request_sentence(self, text: str, voice: str | None, speed: float, cancel_event: threading.Event | None) -> bytes:
        _check_cancel(cancel_event)
        payload: dict[str, Any] = {"text": text, "speed": speed, "stream": False}
        if voice:
            payload["voice"] = str(voice)[:120]
        request = Request(
            f"{self.base_url}/tts",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = bytearray()
                while True:
                    _check_cancel(cancel_event)
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > self.max_audio_bytes:
                        raise TTSUnavailable("TTS audio exceeds configured limit")
                return bytes(data)
        except TTSCancelled:
            raise
        except (HTTPError, URLError, OSError) as exc:
            raise TTSUnavailable("CozyVoice request failed") from exc


class TTSService:
    """Latest-request-wins coordinator around a provider."""

    def __init__(self, provider: TTSProvider):
        self.provider = provider
        self._lock = threading.Lock()
        self._generation = 0
        self._active: threading.Event | None = None

    def health(self) -> dict[str, Any]:
        checker = getattr(self.provider, "health", None)
        result = checker() if checker else {"status": "ready"}
        return {"configured": True, "provider": type(self.provider).__name__, **result}

    def synthesize(self, text: str, *, voice: str | None = None, speed: float = 1.0) -> bytes:
        cancel = threading.Event()
        with self._lock:
            self._generation += 1
            generation = self._generation
            if self._active is not None:
                self._active.set()
            self._active = cancel
        try:
            audio = self.provider.synthesize(text, voice=voice, speed=speed, cancel_event=cancel)
            with self._lock:
                if cancel.is_set() or generation != self._generation:
                    raise TTSCancelled()
            if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
                raise TTSUnavailable("TTS provider returned invalid or oversized audio")
            return audio
        finally:
            with self._lock:
                if self._active is cancel:
                    self._active = None

    def close(self) -> None:
        with self._lock:
            self._generation += 1
            if self._active is not None:
                self._active.set()
                self._active = None


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TTSCancelled()


def _merge_wav(chunks: list[bytes], max_bytes: int) -> bytes:
    if len(chunks) == 1:
        if len(chunks[0]) > max_bytes:
            raise TTSUnavailable("TTS audio exceeds configured limit")
        try:
            with wave.open(io.BytesIO(chunks[0]), "rb") as wav:
                if wav.getnframes() <= 0:
                    raise TTSUnavailable("TTS provider returned empty WAV audio")
        except (wave.Error, OSError) as exc:
            raise TTSUnavailable("CozyVoice returned invalid WAV audio") from exc
        return chunks[0]
    params = None
    frames: list[bytes] = []
    try:
        for chunk in chunks:
            with wave.open(io.BytesIO(chunk), "rb") as wav:
                current = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype())
                if params is None:
                    params = current
                elif current != params:
                    raise TTSUnavailable("TTS chunks have incompatible WAV formats")
                frames.append(wav.readframes(wav.getnframes()))
        assert params is not None
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(params[0]); wav.setsampwidth(params[1]); wav.setframerate(params[2])
            wav.writeframes(b"".join(frames))
        result = output.getvalue()
    except (wave.Error, OSError) as exc:
        raise TTSUnavailable("CozyVoice returned invalid WAV audio") from exc
    if len(result) > max_bytes:
        raise TTSUnavailable("TTS audio exceeds configured limit")
    return result
