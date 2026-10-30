"""Small, replaceable and cancellable TTS boundary."""

from __future__ import annotations

import io
import json
import socket
import base64
import re
import threading
import time
from dataclasses import dataclass
from uuid import uuid4
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterator, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .resources import ResourceGovernor
from .speech_requests import SpeechRequests


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


# Non-speakable decoration: emoji/pictographs/dingbats/symbol blocks plus
# variation selectors, skin-tone modifiers and ZWJ sequences. Speech must
# never voice these; the model writing them is a display-only concern.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictographs, emoji blocks, supplementary symbols
    "\U00002600-\U000027BF"   # misc symbols, dingbats
    "\U00002B00-\U00002BFF"   # misc symbols and arrows
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "\U00002190-\U000021FF"   # arrows
    "\u200D"                   # zero-width joiner
    "]+\\s*",
    re.UNICODE,
)


def strip_decorations(text: str) -> str:
    """Remove emoji and other non-speakable decorations from speech text."""
    return _EMOJI_RE.sub("", str(text or "")).strip()


def split_sentences(text: str, max_chars: int = 500) -> list[str]:
    """Split bounded display text while retaining punctuation for TTS."""
    clean = re.sub(r"\s+", " ", strip_decorations(text)).strip()
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
        self._active_responses: dict[Any, threading.Event | None] = {}

    def _track_response(self, response: Any, cancel_event: threading.Event | None) -> None:
        # Register and inspect the event under the same lock used by targeted
        # cancellation. This closes the race where cancellation arrives while
        # the HTTP opener is still returning its response.
        with self._response_lock:
            self._active_responses[response] = cancel_event
            cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled:
            try:
                response.close()
            except Exception:
                pass

    def _begin_worker_request(self, cancel_event: threading.Event | None) -> Any:
        """Hook for adapters that correlate each HTTP inference request."""
        del cancel_event
        return None

    def _decorate_request_payload(self, payload: dict[str, Any], request_token: Any) -> None:
        """Keep the shared Cozy/Qwen request body unchanged by default."""
        del payload, request_token

    def _finish_worker_request(
        self, cancel_event: threading.Event | None, request_token: Any
    ) -> None:
        del cancel_event, request_token

    def _worker_request_failed(self, request_token: Any) -> None:
        del request_token

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
        prosody: dict[str, float] | None = None,
    ) -> bytes:
        text = str(text or "").strip()
        if not text or len(text) > MAX_TTS_CHARS:
            raise ValueError("TTS text must be non-empty and at most 4000 characters")
        speed = float(speed)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0")
        parts = split_sentences(text)
        if len(parts) == 1:
            chunks = [self._request_sentence(parts[0], voice, speed, cancel_event, prosody=prosody)]
        else:
            with ThreadPoolExecutor(max_workers=min(3, len(parts)), thread_name_prefix="tts") as pool:
                futures = [pool.submit(self._request_sentence, part, voice, speed, cancel_event, prosody=prosody) for part in parts]
                chunks = [future.result() for future in futures]
        if not chunks:
            raise ValueError("TTS text contains no speakable sentence")
        return _merge_wav(chunks, self.max_audio_bytes)

    def _request_sentence(
        self, text: str, voice: str | None, speed: float, cancel_event: threading.Event | None,
        prosody: dict[str, float] | None = None,
    ) -> bytes:
        _check_cancel(cancel_event)
        request_token = self._begin_worker_request(cancel_event)
        try:
            _check_cancel(cancel_event)
            payload: dict[str, Any] = {"text": text, "speed": speed, "stream": False}
            if voice:
                payload["voice"] = str(voice)[:120]
            if prosody:
                # Worker-side bounds re-validate; extra keys are ignored by older
                # workers so the envelope stays forward/backward compatible.
                for key in ("pitch", "f0_range", "energy"):
                    value = prosody.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        payload[key] = float(value)
            self._decorate_request_payload(payload, request_token)
            request = Request(
                f"{self.base_url}/tts",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self._opener(request, timeout=self.timeout_seconds) as response:
                self._track_response(response, cancel_event)
                try:
                    _check_cancel(cancel_event)
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
                        self._active_responses.pop(response, None)
        except TTSCancelled:
            self._worker_request_failed(request_token)
            raise
        except TTSUnavailable:
            self._worker_request_failed(request_token)
            raise
        except (HTTPError, URLError, OSError) as exc:
            self._worker_request_failed(request_token)
            if isinstance(exc, HTTPError):
                exc.close()
            if request_token is not None and isinstance(exc, HTTPError) and exc.code == 409:
                raise TTSCancelled("TTS worker cancelled this request") from exc
            if cancel_event is not None and cancel_event.is_set():
                raise TTSCancelled() from exc
            raise TTSUnavailable("TTS worker request failed") from exc
        except Exception:
            self._worker_request_failed(request_token)
            raise
        finally:
            self._finish_worker_request(cancel_event, request_token)

    def cancel(self) -> None:
        """Close active HTTP bodies so provider reads can unblock promptly."""
        with self._response_lock:
            responses = list(self._active_responses)
        self._close_responses(responses)

    def cancel_generation(self, cancel_event: threading.Event) -> None:
        """Close only HTTP bodies owned by ``cancel_event``."""
        with self._response_lock:
            responses = [
                response for response, owner in self._active_responses.items()
                if owner is cancel_event
            ]
        self._close_responses(responses)

    @staticmethod
    def _close_responses(responses: list[Any]) -> None:
        for response in responses:
            # HTTPResponse.close alone can wait for a BufferedReader lock
            # held by a blocking read. Interrupt only this owned connection
            # first, so cancellation need not wait for the provider timeout.
            try:
                owned_socket = response.fp.raw._sock
                try:
                    owned_socket.shutdown(socket.SHUT_RDWR)
                finally:
                    # SocketIO owns another file reference. socket.close()
                    # alone defers its OS close until BufferedReader exits,
                    # which is exactly the read we need to interrupt. Force
                    # this socket object's native close (also invalidates its
                    # fd, unlike closing a copied integer descriptor).
                    native_close = getattr(owned_socket, "_real_close", None)
                    if callable(native_close):
                        native_close()
            except (AttributeError, OSError):
                pass
            try:
                response.close()
            except Exception:
                pass


class TeraTTSHttpClient(CozyVoiceHttpClient):
    """HTTP adapter for the selected TeraTTSv2 ``teratts_server.py`` worker."""

    MAX_REGISTERED_REQUESTS = 16
    MAX_CANCEL_BATCH = 8

    def __init__(self, base_url: str, **kwargs: Any):
        super().__init__(base_url, **kwargs)
        self._worker_request_lock = threading.Lock()
        self._worker_requests: dict[threading.Event | None, set[str]] = {}

    def _begin_worker_request(self, cancel_event: threading.Event | None) -> str:
        with self._worker_request_lock:
            if cancel_event is not None and cancel_event.is_set():
                raise TTSCancelled()
            count = sum(len(ids) for ids in self._worker_requests.values())
            if count >= self.MAX_REGISTERED_REQUESTS:
                raise TTSUnavailable("TeraTTS worker request registry is full")
            request_id = str(uuid4())
            self._worker_requests.setdefault(cancel_event, set()).add(request_id)
            # Cancellation may set the event immediately before acquiring this
            # lock. In that case the cancel hook either saw this ID, or this
            # check prevents inference from being submitted.
            if cancel_event is not None and cancel_event.is_set():
                self._worker_requests[cancel_event].discard(request_id)
                if not self._worker_requests[cancel_event]:
                    del self._worker_requests[cancel_event]
                raise TTSCancelled()
            return request_id

    def _decorate_request_payload(self, payload: dict[str, Any], request_token: Any) -> None:
        payload["request_id"] = request_token

    def _finish_worker_request(
        self, cancel_event: threading.Event | None, request_token: Any
    ) -> None:
        if not request_token:
            return
        with self._worker_request_lock:
            request_ids = self._worker_requests.get(cancel_event)
            if request_ids is None:
                return
            request_ids.discard(request_token)
            if not request_ids:
                del self._worker_requests[cancel_event]

    def _worker_request_failed(self, request_token: Any) -> None:
        if isinstance(request_token, str):
            self._post_worker_cancellations([request_token])

    def cancel_generation(self, cancel_event: threading.Event) -> None:
        """Stop only this generation's transports and worker request IDs."""
        with self._response_lock:
            responses = [
                response for response, owner in self._active_responses.items()
                if owner is cancel_event
            ]
        self._close_responses(responses)
        with self._worker_request_lock:
            request_ids = sorted(self._worker_requests.get(cancel_event, ()))
        self._post_worker_cancellations(request_ids)

    def cancel(self) -> None:
        """Explicitly stop this adapter's requests without global worker cancel."""
        super().cancel()
        with self._worker_request_lock:
            request_ids = sorted(
                request_id
                for owned_ids in self._worker_requests.values()
                for request_id in owned_ids
            )
        self._post_worker_cancellations(request_ids)

    def _post_worker_cancellations(self, request_ids: list[str]) -> None:
        for offset in range(0, len(request_ids), self.MAX_CANCEL_BATCH):
            batch = request_ids[offset:offset + self.MAX_CANCEL_BATCH]
            if not batch:
                continue
            request = Request(
                f"{self.base_url}/cancel",
                data=json.dumps({"request_ids": batch}).encode("ascii"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with self._opener(request, timeout=1.0) as response:
                    # Headers acknowledge this best-effort control POST. Do
                    # not wait for/trickle-read a body while holding TTS's
                    # generation transition lock; this connection is not pooled.
                    pass
            except Exception:
                # Socket close is the fast path; the scoped worker endpoint is
                # best-effort when the service is shutting down or restarting.
                pass


class Qwen3TTSHttpClient(CozyVoiceHttpClient):
    """HTTP adapter for the optional Qwen3-TTS Base voice-clone worker."""

    pass


class VoxCPMHttpClient(CozyVoiceHttpClient):
    """HTTP adapter for the optional VoxCPM2 GPU worker.

    ``/tts`` keeps the existing complete-WAV contract.  The worker's native
    generator is exposed separately as ``/tts/stream`` and yields independent
    WAV chunks, so the companion can start playback before final synthesis.
    """

    def stream_synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[bytes]:
        text = str(text or "").strip()
        if not text or len(text) > MAX_TTS_CHARS:
            raise ValueError("TTS text must be non-empty and at most 4000 characters")
        speed = float(speed)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("TTS speed must be between 0.5 and 2.0")
        _check_cancel(cancel_event)
        payload: dict[str, Any] = {"text": text, "speed": speed, "stream": True}
        if voice:
            payload["voice"] = str(voice)[:120]
        request = Request(
            f"{self.base_url}/tts/stream",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                self._track_response(response, cancel_event)
                try:
                    _check_cancel(cancel_event)
                    for raw_line in response:
                        _check_cancel(cancel_event)
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise TTSUnavailable("VoxCPM stream returned a non-object event")
                        event_type = event.get("type")
                        if event_type == "error":
                            raise TTSUnavailable(str(event.get("error") or "VoxCPM stream failed")[:300])
                        if event_type == "cancelled":
                            raise TTSCancelled()
                        if event_type != "audio":
                            continue
                        encoded = event.get("data_base64")
                        if not isinstance(encoded, str):
                            raise TTSUnavailable("VoxCPM stream audio event is missing data")
                        try:
                            audio = base64.b64decode(encoded, validate=True)
                        except (ValueError, TypeError) as exc:
                            raise TTSUnavailable("VoxCPM stream returned invalid base64 audio") from exc
                        if not audio or len(audio) > self.max_audio_bytes:
                            raise TTSUnavailable("VoxCPM stream audio is empty or oversized")
                        yield audio
                finally:
                    with self._response_lock:
                        self._active_responses.pop(response, None)
        except TTSCancelled:
            raise
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise TTSCancelled() from exc
            raise TTSUnavailable("VoxCPM streaming worker request failed") from exc

    def cancel(self) -> None:
        """Close the stream and ask the worker to stop after its current chunk."""
        super().cancel()
        request = Request(
            f"{self.base_url}/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=min(self.timeout_seconds, 3.0)) as response:
                response.read(4 * 1024)
        except (HTTPError, URLError, OSError, ValueError):
            # Transport close already stops browser playback; worker cancel is
            # best-effort when the worker is restarting or already gone.
            pass


@dataclass
class _SpeechLease:
    governor: ResourceGovernor | None
    calls: int = 0
    closing: bool = False
    iterator: Any | None = None


class TTSService:
    """Latest-request-wins coordinator around a provider."""

    def __init__(self, provider: TTSProvider, governor: ResourceGovernor | None = None,
                 prosody_planner: Any | None = None, *, replacement_timeout_seconds: float = 2.0):
        self.provider = provider
        self.governor = governor
        self.prosody_planner = prosody_planner
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._generation = 0
        self._active: threading.Event | None = None
        self._latest: threading.Event | None = None
        self._leases: dict[threading.Event, _SpeechLease] = {}
        self._closed = False
        self._replacement_timeout = max(0.05, min(float(replacement_timeout_seconds), 10.0))
        self._requests = SpeechRequests()
        self._planner_slot = threading.BoundedSemaphore(1)

    def health(self) -> dict[str, Any]:
        if self._closed:
            return {"configured": False, "provider": type(self.provider).__name__, "status": "closed"}
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
        request_id: str | None = None,
    ) -> bytes:
        speed = self.emotion_speed(speed, emotion)
        cancel, generation = self._begin_generation(request_id)
        try:
            audio = self._provider_call(cancel, self.provider.synthesize,
                                        text, voice=voice, speed=speed, cancel_event=cancel)
            with self._lock:
                if cancel.is_set() or generation != self._generation:
                    raise TTSCancelled()
            if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
                raise TTSUnavailable("TTS provider returned invalid or oversized audio")
            return audio
        finally:
            self._finish_generation(cancel)

    def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        emotion: Mapping[str, Any] | None = None,
        request_id: str | None = None,
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

        cancel, generation = self._begin_generation(request_id)

        pool: ThreadPoolExecutor | None = None
        futures: list = []
        native_iterator = None
        try:
            native_stream = getattr(self.provider, "stream_synthesize", None)
            if callable(native_stream):
                for part in parts:
                    _check_cancel(cancel)
                    native_iterator = self._provider_call(
                        cancel, self._open_native_iterator, cancel, native_stream,
                        part, voice=voice, speed=speed, cancel_event=cancel,
                    )
                    while True:
                        try:
                            audio = self._provider_call(cancel, next, native_iterator)
                        except StopIteration:
                            break
                        self._validate_stream_audio(audio, cancel, generation)
                        yield _merge_wav([audio], MAX_AUDIO_BYTES)
                    self._close_native_iterator(cancel, native_iterator)
                    native_iterator = None
                return

            pool = ThreadPoolExecutor(max_workers=min(3, len(parts)), thread_name_prefix="tts-stream")
            if self.prosody_planner is not None and len(parts) > 1:
                # First sentence starts immediately, planner annotates the tail.
                futures.append(pool.submit(self._provider_call, cancel, self.provider.synthesize,
                                           parts[0], voice=voice, speed=speed, cancel_event=cancel))
                envelope_box = {"value": None}
                def _run_planner() -> None:
                    try:
                        if not cancel.is_set():
                            envelope_box["value"] = self.prosody_planner.plan(parts)
                    except Exception:
                        envelope_box["value"] = None
                    finally:
                        self._planner_slot.release()
                planner_thread = None
                if self._planner_slot.acquire(blocking=False):
                    try:
                        planner_thread = threading.Thread(target=_run_planner, daemon=True)
                        planner_thread.start()
                    except BaseException:
                        self._planner_slot.release()
                        raise
                envelopes = None
                for index in range(len(parts)):
                    _check_cancel(cancel)
                    if index > 0 and len(futures) <= index:
                        if envelopes is None:
                            if planner_thread is not None:
                                deadline = time.monotonic() + self.prosody_planner.timeout_seconds
                                while planner_thread.is_alive():
                                    _check_cancel(cancel)
                                    remaining = deadline - time.monotonic()
                                    if remaining <= 0:
                                        break
                                    planner_thread.join(min(remaining, 0.05))
                            _check_cancel(cancel)
                            envelopes = envelope_box["value"] if isinstance(envelope_box["value"], list) else None
                        futures.append(pool.submit(
                            self._provider_call, cancel, self.provider.synthesize,
                            parts[index], voice=voice, speed=speed,
                            cancel_event=cancel,
                            prosody=envelopes[index] if envelopes else None,
                        ))
                    audio = self._future_audio(futures[index], cancel)
                    self._validate_stream_audio(audio, cancel, generation)
                    yield _merge_wav([audio], MAX_AUDIO_BYTES)
                return

            for part in parts:
                _check_cancel(cancel)
                futures.append(pool.submit(self._provider_call, cancel, self.provider.synthesize,
                                           part, voice=voice, speed=speed, cancel_event=cancel))
            for future in futures:
                audio = self._future_audio(future, cancel)
                self._validate_stream_audio(audio, cancel, generation)
                yield _merge_wav([audio], MAX_AUDIO_BYTES)
        finally:
            try:
                self._close_native_iterator(cancel, native_iterator)
            finally:
                self._finish_generation(cancel)
                for future in futures:
                    future.cancel()
                if pool is not None:
                    pool.shutdown(wait=False, cancel_futures=True)

    def set_governor(self, governor: ResourceGovernor | None) -> None:
        with self._lock:
            if governor is not self.governor and self._leases:
                raise TTSUnavailable("cannot replace a resource governor during speech")
            self.governor = governor

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.cancel()

    def cancel(self, *, request_id: str | None = None) -> None:
        """Cancel one correlated request, or explicitly stop all speech."""
        with self._lock:
            if request_id is not None:
                try:
                    token = self._requests.cancel(request_id)
                except RuntimeError as exc:
                    raise TTSUnavailable(str(exc)) from exc
                self._cancel_provider_generation_locked(token)
                self._close_lease_locked(token)
                self._condition.notify_all()
                return
            self._generation += 1
            if self._latest is not None:
                self._latest.set()
            for token in self._leases:
                token.set()
            self._latest = self._active = None
            # Keep explicit cancellation global for providers that expose only
            # the historical no-argument hook.
            self._cancel_provider_global()
            for token in list(self._leases):
                self._close_lease_locked(token)
            self._condition.notify_all()

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

    def _begin_generation(self, request_id: str | None) -> tuple[threading.Event, int]:
        try:
            cancel = self._requests.begin(request_id)
        except RuntimeError as exc:
            raise TTSUnavailable(str(exc)) from exc
        try:
            with self._condition:
                if self._closed:
                    raise TTSUnavailable("speech service is closed")
                # A replay/early cancel must not supersede a live response.
                _check_cancel(cancel)
                previous = self._latest
                if previous is not None:
                    previous.set()
                    self._cancel_provider_generation_locked(previous)
                    self._close_lease_locked(previous)
                self._generation += 1
                generation = self._generation
                self._latest = cancel
                deadline = time.monotonic() + self._replacement_timeout
                while True:
                    _check_cancel(cancel)
                    if self._closed:
                        raise TTSUnavailable("speech service is closed")
                    governor = self.governor
                    if governor is None or governor.try_acquire("speech"):
                        try:
                            # Includes reentrant cancellation from admission.
                            _check_cancel(cancel)
                            if self._closed:
                                raise TTSUnavailable("speech service is closed")
                            self._leases[cancel] = _SpeechLease(governor)
                            self._active = cancel
                            return cancel, generation
                        except BaseException:
                            if governor is not None:
                                governor.release("speech")
                            raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TTSUnavailable("speech worker is busy under the active resource profile")
                    self._condition.wait(min(remaining, 0.05))
        except BaseException:
            with self._condition:
                if self._latest is cancel:
                    self._latest = None
                self._requests.finish(cancel)
                self._condition.notify_all()
            raise

    def _provider_call(self, token: threading.Event, call: Callable[..., Any],
                       *args: Any, **kwargs: Any) -> Any:
        with self._condition:
            _check_cancel(token)
            lease = self._leases.get(token)
            if lease is None or lease.closing:
                raise TTSCancelled()
            lease.calls += 1
        try:
            return call(*args, **kwargs)
        finally:
            with self._condition:
                lease.calls -= 1
                if lease.closing and lease.calls == 0:
                    self._release_lease_locked(token, lease)

    def _open_native_iterator(self, token: threading.Event, factory: Callable[..., Any],
                              *args: Any, **kwargs: Any) -> Any:
        iterator = iter(factory(*args, **kwargs))
        with self._condition:
            # Called inside _provider_call: its active call keeps this lease
            # alive even if cancellation happens while the factory runs.
            self._leases[token].iterator = iterator
        return iterator

    def _close_native_iterator(self, token: threading.Event, iterator: Any) -> None:
        with self._condition:
            lease = self._leases.get(token)
            if lease is not None and iterator is not None and lease.iterator is iterator:
                self._close_iterator_locked(lease)

    @staticmethod
    def _close_iterator_locked(lease: _SpeechLease) -> None:
        iterator, lease.iterator = lease.iterator, None
        closer = getattr(iterator, "close", None)
        if callable(closer):
            closer()

    @staticmethod
    def _future_audio(future: Any, cancel: threading.Event) -> bytes:
        while True:
            _check_cancel(cancel)
            try:
                return future.result(timeout=0.05)
            except TimeoutError:
                # A provider's own TimeoutError is not a poll timeout.
                if future.done():
                    raise

    def _validate_stream_audio(self, audio: Any, cancel: threading.Event, generation: int) -> None:
        with self._lock:
            if cancel.is_set() or generation != self._generation:
                raise TTSCancelled()
        if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
            raise TTSUnavailable("TTS provider returned invalid or oversized audio")

    def _close_lease_locked(self, token: threading.Event) -> None:
        lease = self._leases.get(token)
        if lease is not None:
            lease.closing = True
            if lease.calls == 0:
                self._release_lease_locked(token, lease)

    def _release_lease_locked(self, token: threading.Event, lease: _SpeechLease) -> None:
        if self._leases.get(token) is not lease:
            return
        # A native iterator may be paused at a consumer yield with zero calls
        # in progress. Close it before handing the slot to another generation;
        # late consumer cleanup must not close it again under a newer owner.
        lease.calls += 1  # Fence a reentrant cancel from iterator.close().
        try:
            self._close_iterator_locked(lease)
        except Exception:
            pass
        finally:
            lease.calls -= 1
        del self._leases[token]
        if lease.governor is not None:
            lease.governor.release("speech")
        self._requests.finish(token)
        if self._active is token:
            self._active = None
        if self._latest is token:
            self._latest = None
        self._condition.notify_all()

    def _cancel_provider_generation_locked(self, cancel_event: threading.Event) -> None:
        targeted = getattr(self.provider, "cancel_generation", None)
        if callable(targeted):
            try:
                targeted(cancel_event)
            except Exception:
                pass
        elif self._active is cancel_event:
            # Legacy global providers run while ownership transitions are
            # locked, before a replacement generation can be published.
            self._cancel_provider_global()

    def _finish_generation(self, cancel_event: threading.Event) -> None:
        with self._condition:
            cancel_event.set()
            self._cancel_provider_generation_locked(cancel_event)
            self._close_lease_locked(cancel_event)
            self._condition.notify_all()

    def _cancel_provider_global(self) -> None:
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
