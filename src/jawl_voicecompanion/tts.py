"""Small, replaceable and cancellable TTS boundary."""

from __future__ import annotations

import io
import json
import re
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterator, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .resources import ResourceGovernor


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
    """Compatibility adapter for a local ``/health`` + ``/tts`` REST worker.

    The same small protocol is used by the historical CozyVoice wrapper and
    the selected TeraTTSv2 worker. Keep this name for existing integrations;
    new code should prefer ``TeraTTSHttpClient`` when Tera is selected.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 120.0,
        max_audio_bytes: int = MAX_AUDIO_BYTES,
        opener: Callable[..., Any] = urlopen,
    ):
        self.base_url = str(base_url).rstrip("/")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 300.0))
        self.max_audio_bytes = max(64 * 1024, min(int(max_audio_bytes), MAX_AUDIO_BYTES))
        self._opener = opener
        self._response_lock = threading.Lock()
        self._active_responses: set[Any] = set()

    def health(self) -> dict[str, Any]:
        try:
            request = Request(f"{self.base_url}/health", method="GET")
            with self._opener(request, timeout=min(self.timeout_seconds, 10.0)) as response:
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
        parts = split_sentences(text)
        if len(parts) == 1:
            chunks = [self._request_sentence(parts[0], voice, speed, cancel_event)]
        else:
            with ThreadPoolExecutor(max_workers=min(3, len(parts)), thread_name_prefix="tts") as pool:
                futures = [pool.submit(self._request_sentence, part, voice, speed, cancel_event) for part in parts]
                chunks = [future.result() for future in futures]
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
            with self._opener(request, timeout=self.timeout_seconds) as response:
                with self._response_lock:
                    self._active_responses.add(response)
                try:
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
                finally:
                    with self._response_lock:
                        self._active_responses.discard(response)
        except TTSCancelled:
            raise
        except (HTTPError, URLError, OSError) as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise TTSCancelled() from exc
            raise TTSUnavailable("TTS worker request failed") from exc

    def cancel(self) -> None:
        """Close active HTTP bodies so provider reads can unblock promptly."""
        with self._response_lock:
            responses = list(self._active_responses)
        for response in responses:
            try:
                response.close()
            except Exception:
                pass


class TeraTTSHttpClient(CozyVoiceHttpClient):
    """HTTP adapter for the selected TeraTTSv2 ``teratts_server.py`` worker."""

    pass


class Qwen3TTSHttpClient(CozyVoiceHttpClient):
    """HTTP adapter for the optional Qwen3-TTS Base voice-clone worker."""

    pass


class TTSService:
    """Latest-request-wins coordinator around a provider."""

    def __init__(self, provider: TTSProvider, governor: ResourceGovernor | None = None):
        self.provider = provider
        self.governor = governor
        self._lock = threading.Lock()
        self._generation = 0
        self._active: threading.Event | None = None

    def health(self) -> dict[str, Any]:
        checker = getattr(self.provider, "health", None)
        result = checker() if checker else {"status": "ready"}
        return {"configured": True, "provider": type(self.provider).__name__, **result}

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        emotion: Mapping[str, Any] | None = None,
    ) -> bytes:
        speed = self.emotion_speed(speed, emotion)
        acquired = self.governor is None or self.governor.try_acquire("speech")
        if not acquired:
            raise TTSUnavailable("speech worker is busy under the active resource profile")
        cancel = threading.Event()
        superseded = False
        with self._lock:
            self._generation += 1
            generation = self._generation
            if self._active is not None:
                self._active.set()
                superseded = True
            self._active = cancel
        if superseded:
            self._cancel_provider()
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
            if self.governor is not None:
                self.governor.release("speech")

    def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        emotion: Mapping[str, Any] | None = None,
    ) -> Iterator[bytes]:
        """Yield sentence WAVs in order as soon as each one is ready.

        Providers keep their existing whole-WAV contract.  The service owns the
        small amount of orchestration needed for first-audio latency, ordering,
        and latest-request-wins cancellation.
        """
        text = str(text or "").strip()
        if not text or len(text) > MAX_TTS_CHARS:
            raise ValueError("TTS text must be non-empty and at most 4000 characters")
        speed = self.emotion_speed(speed, emotion)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0")
        parts = split_sentences(text)
        if not parts:
            raise ValueError("TTS text contains no speakable sentence")

        acquired = self.governor is None or self.governor.try_acquire("speech")
        if not acquired:
            raise TTSUnavailable("speech worker is busy under the active resource profile")

        cancel = threading.Event()
        superseded = False
        with self._lock:
            self._generation += 1
            generation = self._generation
            if self._active is not None:
                self._active.set()
                superseded = True
            self._active = cancel
        if superseded:
            self._cancel_provider()

        pool = ThreadPoolExecutor(max_workers=min(3, len(parts)), thread_name_prefix="tts-stream")
        futures = [
            pool.submit(self.provider.synthesize, part, voice=voice, speed=speed, cancel_event=cancel)
            for part in parts
        ]
        try:
            for future in futures:
                _check_cancel(cancel)
                audio = future.result()
                with self._lock:
                    if cancel.is_set() or generation != self._generation:
                        raise TTSCancelled()
                if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
                    raise TTSUnavailable("TTS provider returned invalid or oversized audio")
                yield _merge_wav([audio], MAX_AUDIO_BYTES)
        finally:
            cancel.set()
            # A provider may be blocked inside a socket read and cannot see
            # the event until that read returns.  Give HTTP-backed providers
            # their explicit body-cancellation hook before releasing the
            # worker pool.
            self._cancel_provider()
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            with self._lock:
                if self._active is cancel:
                    self._active = None
            if self.governor is not None:
                self.governor.release("speech")

    def set_governor(self, governor: ResourceGovernor | None) -> None:
        self.governor = governor

    def close(self) -> None:
        self.cancel()

    def cancel(self) -> None:
        """Cancel the active synthesis without closing the provider."""
        with self._lock:
            self._generation += 1
            if self._active is not None:
                self._active.set()
                self._active = None
        self._cancel_provider()

    @staticmethod
    def emotion_speed(speed: float, emotion: Mapping[str, Any] | None = None) -> float:
        """Map bounded envelope emotion to TTS controls supported by all providers.

        TeraTTSv2 and the current CozyVoice wrapper do not share style tags, so
        the portable control is a small rate bias.  Unknown emotions remain
        neutral; no provider-specific argument is invented at this boundary.
        """
        value = float(speed)
        if not 0.5 <= value <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0")
        if not isinstance(emotion, Mapping):
            return value
        emotion_id = str(emotion.get("id") or "neutral").casefold()
        raw_intensity = emotion.get("intensity", 0.0)
        if isinstance(raw_intensity, bool) or not isinstance(raw_intensity, (int, float)):
            intensity = 0.0
        else:
            intensity = max(0.0, min(1.0, float(raw_intensity)))
        bias = {
            "excited": 0.10,
            "happy": 0.06,
            "angry": 0.04,
            "concerned": -0.04,
            "sad": -0.08,
            "calm": -0.04,
        }.get(emotion_id, 0.0)
        return max(0.5, min(2.0, value + bias * intensity))

    def _cancel_provider(self) -> None:
        cancel = getattr(self.provider, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass


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
            raise TTSUnavailable("TTS worker returned invalid WAV audio") from exc
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
        raise TTSUnavailable("TTS worker returned invalid WAV audio") from exc
    if len(result) > max_bytes:
        raise TTSUnavailable("TTS audio exceeds configured limit")
    return result
