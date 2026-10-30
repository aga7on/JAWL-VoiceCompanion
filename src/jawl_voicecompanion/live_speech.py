"""Live speech session: speak the first sentence while the reply still streams.

The desktop client already consumes sentence WAVs as NDJSON
(``desktop/speech-stream.js``) and the TTS service already yields one WAV per
sentence (``TTSService.stream``).  What was missing is the *timing*: both
waited for the complete JAWL envelope, so the voice started only after the
whole JSON had been generated.

This module closes that gap.  It accepts the reply as it arrives — either as
plain text or as the raw bytes of the JAWL JSON envelope — and starts the
synthesis of every finished sentence immediately:

    client ──delta──▶ LiveSpeechSession ──sentence──▶ TTSService ──WAV──▶ client
          (raw JSON envelope)      (speech-first gate)

The gate guarantees three invariants:

* private fields (``observation`` / ``reasoning``) are never spoken;
* a sentence is spoken only at a real boundary, so the voice never stutters;
* spoken text plus the final tail reconstructs the authoritative reply.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .speech_first import SpeechFirstGate, first_speakable_chunk
from .tts import TTSCancelled

__all__ = ["LiveSpeechSession", "LiveSpeechState"]

_SENTENCE_QUEUE_MAX = 32
_AUDIO_QUEUE_MAX = 32


@dataclass
class LiveSpeechState:
    """Bounded counters for one live speech session."""

    mode: str = "text"
    sentences: int = 0
    audio_chunks: int = 0
    spoken_chars: int = 0
    started_at: float = field(default_factory=time.monotonic)
    finished: bool = False
    cancelled: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "sentences": self.sentences,
            "audio_chunks": self.audio_chunks,
            "spoken_chars": self.spoken_chars,
            "elapsed_s": round(time.monotonic() - self.started_at, 3),
            "finished": self.finished,
            "cancelled": self.cancelled,
            "error": self.error,
        }


class LiveSpeechSession:
    """Stream a reply into sentence WAVs that start before the reply ends."""

    def __init__(
        self,
        tts: Any,
        *,
        voice: str | None = None,
        speed: float = 1.0,
        emotion: dict[str, Any] | None = None,
        request_id: str | None = None,
        mode: str = "text",
        min_chars: int = 3,
        min_words: int = 1,
        long_clause_chars: int = 120,
        on_audio: Any | None = None,
    ) -> None:
        if tts is None:
            raise ValueError("live speech needs a TTS service")
        if mode not in {"text", "envelope"}:
            raise ValueError("live speech mode must be 'text' or 'envelope'")
        self._on_audio = on_audio
        self._tts = tts
        self._voice = voice
        self._speed = speed
        self._emotion = emotion
        self._request_id = request_id
        self._tts_request_id = request_id or f"live-{uuid.uuid4().hex}"
        self._mode = mode
        self._min_chars = int(min_chars)
        self._min_words = int(min_words)
        self._long_clause_chars = int(long_clause_chars)
        self._gate = (
            SpeechFirstGate(
                min_chars=self._min_chars,
                min_words=self._min_words,
                long_clause_chars=self._long_clause_chars,
            )
            if mode == "envelope"
            else None
        )
        self._text_buffer = ""
        self._raw_text = ""
        self._raw_spoken = 0
        self._spoken_text = ""
        self._pending_text = ""
        self._sentences: "queue.Queue[str | None]" = queue.Queue(maxsize=_SENTENCE_QUEUE_MAX)
        self._audio: "queue.Queue[bytes | None]" = queue.Queue(maxsize=_AUDIO_QUEUE_MAX)
        self._lock = threading.RLock()
        self._state = LiveSpeechState(mode=mode)
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._done = threading.Event()
        self._audio_index = 0

    # ------------------------------------------------------------ lifecycle

    def start(self) -> "LiveSpeechSession":
        """Start the synthesis worker (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._thread = threading.Thread(
                target=self._run, name="live-speech", daemon=True
            )
            self._thread.start()
            return self

    def cancel(self) -> None:
        """Stop the session and cancel its in-flight synthesis request."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._state.cancelled = True
        cancel_tts = getattr(self._tts, "cancel", None)
        if callable(cancel_tts):
            try:
                cancel_tts(request_id=self._tts_request_id)
            except TypeError:
                try:
                    cancel_tts()
                except Exception:  # noqa: BLE001 - best-effort transport stop
                    pass
            except Exception:  # noqa: BLE001 - best-effort transport stop
                pass
        self._done.set()
        self._drain(self._sentences)
        self._drain(self._audio)
        try:
            self._sentences.put_nowait(None)
        except queue.Full:  # pragma: no cover - defensive
            pass

    def _drain(self, target: "queue.Queue[Any]") -> None:
        while True:
            try:
                target.get_nowait()
            except queue.Empty:
                return

    # ---------------------------------------------------------------- input

    def feed(self, delta: str) -> list[str]:
        """Accept a streamed fragment and return sentences that are ready."""
        if not delta:
            return []
        ready: list[str] = []
        if self._gate is not None:
            piece = self._gate.feed(delta)
            self._pending_text = self._gate.pending_text
            if piece:
                self._spoken_text += piece
                ready.append(piece.strip())
        else:
            self._raw_text += delta
            window = self._raw_text[self._raw_spoken :]
            chunk = first_speakable_chunk(
                window,
                min_chars=self._min_chars,
                min_words=self._min_words,
                long_clause_chars=self._long_clause_chars,
            )
            if chunk is not None:
                raw_slice = window[: chunk.end]
                self._raw_spoken += chunk.end
                self._spoken_text += raw_slice
                self._pending_text = self._raw_text[self._raw_spoken :]
                piece = raw_slice.strip()
                if piece:
                    ready.append(piece)
        for sentence in ready:
            self._enqueue(sentence)
        return ready

    def finish(self, final_text: str | None = None) -> list[str]:
        """Flush the tail that never reached a sentence boundary."""
        ready: list[str] = []
        if self._gate is not None:
            tail, mismatch = self._gate.finalize(str(final_text or ""))
            if mismatch:
                self._state.error = "stream_diverged_from_final"
            if tail.strip():
                self._spoken_text += tail
                ready.append(tail.strip())
        else:
            tail = self._raw_text[self._raw_spoken :]
            self._raw_spoken = len(self._raw_text)
            self._spoken_text += tail
            if tail.strip():
                ready.append(tail.strip())
        self._pending_text = ""
        for sentence in ready:
            self._enqueue(sentence)
        with self._lock:
            self._state.finished = True
        try:
            self._sentences.put_nowait(None)
        except queue.Full:  # pragma: no cover - defensive
            pass
        return ready

    def _enqueue(self, sentence: str) -> None:
        if not sentence:
            return
        with self._lock:
            self._state.sentences += 1
            self._state.spoken_chars += len(sentence)
        try:
            self._sentences.put_nowait(sentence)
        except queue.Full:
            # Back-pressure: the consumer is behind; keep the newest text only.
            try:
                self._sentences.get_nowait()
                self._sentences.put_nowait(sentence)
            except queue.Empty:  # pragma: no cover - defensive
                pass

    # --------------------------------------------------------------- output

    def audio(self) -> Iterator[bytes]:
        """Yield WAV chunks as soon as the worker produces them."""
        while True:
            chunk = self._audio.get()
            if chunk is None:
                return
            yield chunk

    def poll_audio(self, timeout: float = 0.0) -> list[bytes]:
        """Return the WAV chunks that are ready right now (bounded wait)."""
        chunks: list[bytes] = []
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            try:
                if remaining > 0:
                    chunk = self._audio.get(timeout=remaining)
                else:
                    chunk = self._audio.get_nowait()
            except queue.Empty:
                break
            if chunk is None:
                self._done.set()
                break
            chunks.append(chunk)
        return chunks

    def drain_all(self, limit_seconds: float = 120.0) -> list[bytes]:
        """Collect every remaining WAV chunk, waiting for the worker to finish."""
        chunks: list[bytes] = []
        deadline = time.monotonic() + max(1.0, float(limit_seconds))
        while not self._done.is_set() and time.monotonic() < deadline:
            chunk = self.poll_audio(timeout=0.05)
            if not chunk:
                continue
            chunks.extend(chunk)
        chunks.extend(self.poll_audio(timeout=0.0))
        return chunks

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def _run(self) -> None:
        while True:
            try:
                sentence = self._sentences.get(timeout=0.2)
            except queue.Empty:
                with self._lock:
                    if self._stopped:
                        return
                continue
            if sentence is None:
                break
            if self._stopped:
                break
            try:
                audio = self._tts.synthesize(
                    sentence,
                    voice=self._voice,
                    speed=self._speed,
                    emotion=self._emotion,
                    **({"request_id": self._tts_request_id} if self._tts_request_id else {}),
                )
            except TTSCancelled:
                with self._lock:
                    self._state.cancelled = True
                break
            except Exception as exc:  # noqa: BLE001 - reported to the caller
                with self._lock:
                    if self._stopped:
                        break
                    self._state.error = f"{type(exc).__name__}: {exc}"[:200]
                break
            with self._lock:
                if self._stopped:
                    break
            if not isinstance(audio, (bytes, bytearray)) or not audio:
                with self._lock:
                    self._state.error = "tts returned no audio"
                break
            with self._lock:
                self._state.audio_chunks += 1
            payload = bytes(audio)
            # Push it to the live transport immediately: the caller may be
            # blocked waiting for the next text delta, and a sentence WAV that
            # is already ready must not wait for the turn to finish.
            if self._on_audio is not None:
                try:
                    self._on_audio(payload)
                except Exception:  # noqa: BLE001 - the transport owns its errors
                    pass
            try:
                self._audio.put_nowait(payload)
            except queue.Full:  # pragma: no cover - callback mode drains instead
                pass
        try:
            self._audio.put_nowait(None)
        except queue.Full:  # pragma: no cover - defensive
            pass
        self._done.set()

    def state(self) -> dict[str, Any]:
        with self._lock:
            payload = self._state.to_dict()
            payload["spoken_text"] = self._spoken_text[-2000:]
            payload["pending_text"] = self._pending_text[-2000:]
            return payload

    @property
    def spoken_text(self) -> str:
        """Exact text already handed to the synthesizer (whitespace intact)."""
        return self._spoken_text

    @property
    def pending_text(self) -> str:
        """Text that was received but not spoken yet."""
        return self._pending_text
