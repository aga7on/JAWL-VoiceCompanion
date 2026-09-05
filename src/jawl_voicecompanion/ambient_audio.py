"""System-audio to isolated VoiceMem/ambient-memory bridge."""

from __future__ import annotations

from array import array
import sys
import time
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread, current_thread
from typing import Any

from .ambient_memory import AmbientMemoryBuffer
from .asr import ASRUnavailable, ExternalASRService
from .audio_understanding import AudioDescriptionService, AudioDescriptionUnavailable
from .ambient_segments import AmbientSegment, AmbientSegmenter
from .system_audio import SystemAudioLoopback
from .voicemem_client import VoiceMemUnavailable


class AmbientAudioDisabled(RuntimeError):
    """Raised when capture is requested before ambient memory is enabled."""


class PlaybackSuppression:
    """Short-lived marker for audio emitted by the companion itself."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._until = 0.0
        self._active = False

    def begin(self, ttl_seconds: float = 30.0) -> dict[str, Any]:
        ttl = max(1.0, min(float(ttl_seconds), 120.0))
        with self._lock:
            self._active = True
            self._until = max(self._until, time.monotonic() + ttl)
            return self.state()

    def end(self) -> dict[str, Any]:
        with self._lock:
            self._active = False
            self._until = 0.0
            return self.state()

    def active(self) -> bool:
        with self._lock:
            if self._active and time.monotonic() >= self._until:
                self._active = False
                self._until = 0.0
            return self._active

    def state(self) -> dict[str, Any]:
        with self._lock:
            active = self._active and time.monotonic() < self._until
            if not active:
                self._active = False
                self._until = 0.0
            return {"active": active, "remaining_seconds": max(0.0, self._until - time.monotonic())}


class AmbientAudioASRBridge:
    """Consume loopback PCM without entering the microphone conversation path."""

    def __init__(
        self,
        voice_mem: Any,
        memory: AmbientMemoryBuffer,
        *,
        target_sample_rate: int = 16000,
        max_feed_bytes: int = 48 * 1024,
        playback_suppression: PlaybackSuppression | None = None,
        final_asr: ExternalASRService | None = None,
        audio_describer: AudioDescriptionService | None = None,
        max_description_bytes: int = 960000,
        segment_queue_size: int = 32,
        processing_queue_size: int = 8,
        segment_queue_bytes: int | None = None,
        segment_max_bytes: int = 512 * 1024,
        segment_max_seconds: float = 15.0,
    ) -> None:
        if not hasattr(voice_mem, "feed_audio") or not hasattr(voice_mem, "end_audio"):
            raise TypeError("ambient ASR client must provide feed_audio and end_audio")
        if not isinstance(memory, AmbientMemoryBuffer):
            raise TypeError("ambient memory buffer is required")
        self.voice_mem = voice_mem
        self.memory = memory
        self.target_sample_rate = max(8000, min(int(target_sample_rate), 96000))
        self.max_feed_bytes = max(2048, min(int(max_feed_bytes), 48 * 1024)) & ~1
        self.playback_suppression = playback_suppression
        self.final_asr = final_asr
        self.audio_describer = audio_describer
        self.max_description_bytes = max(2048, min(int(max_description_bytes), 2 * 1024 * 1024)) & ~1
        self.segment_queue_size = max(1, min(int(segment_queue_size), 256))
        self.processing_queue_size = max(1, min(int(processing_queue_size), 64))
        self.segment_queue_bytes = segment_queue_bytes
        self.segment_max_bytes = max(4 * 1024, min(int(segment_max_bytes), 4 * 1024 * 1024)) & ~1
        self.segment_max_seconds = max(0.25, min(float(segment_max_seconds), 120.0))
        self._lock = RLock()
        self._lifecycle_lock = RLock()
        self._segmenter = AmbientSegmenter(
            self._enqueue_segment,
            queue_size=self.segment_queue_size,
            max_chunk_bytes=self.max_feed_bytes,
            max_queue_bytes=segment_queue_bytes,
            max_segment_bytes=self.segment_max_bytes,
            max_segment_seconds=self.segment_max_seconds,
        )
        self._processing_queue: Queue[AmbientSegment] | None = None
        self._processing_stop = Event()
        self._processing_worker: Thread | None = None
        self._session_id: str | None = None
        self._generation: str | None = None
        self._chunks = 0
        self._transcripts = 0
        self._dropped_events = 0
        self._suppressed_self_tts = 0
        self._segment_events = 0
        self._segment_ingested = 0
        self._segment_dropped = 0
        self._stale_segments = 0
        self._asr_finishes = 0
        self._last_transcript = ""
        self._last_description: dict[str, Any] | None = None
        self._asr_discards = 0
        self._cancelled_segments = 0
        self._stopping = False
        self._last_error: str | None = None

    def consume(self, pcm16: bytes, sample_rate: int, channels: int, session_id: str) -> dict[str, Any]:
        if self.playback_suppression is not None and self.playback_suppression.active():
            with self._lock:
                self._suppressed_self_tts += 1
            return {"status": "suppressed", "reason": "self_tts_playback"}
        try:
            converted = self._to_target_pcm(pcm16, sample_rate, channels, self.target_sample_rate)
            if not converted:
                return {"status": "ignored", "reason": "audio_chunk_empty"}
            with self._lifecycle_lock:
                with self._lock:
                    if self._stopping:
                        return {"status": "degraded", "error": "ambient_stopping"}
                    active_session = self._session_id
                if active_session is None:
                    self.start(session_id)
                    active_session = str(session_id or "ambient-audio")[:120]
                if active_session != str(session_id or "ambient-audio")[:120]:
                    return {"status": "degraded", "error": "ambient_session_changed"}
                accepted = 0
                dropped = 0
                for start in range(0, len(converted), self.max_feed_bytes):
                    chunk = converted[start : start + self.max_feed_bytes]
                    result = self._segmenter.submit(chunk, self.target_sample_rate, 1)
                    if result.get("status") == "accepted":
                        accepted += 1
                    elif result.get("status") == "dropped":
                        dropped += 1
                with self._lock:
                    self._chunks += 1
                    self._segment_dropped += dropped
                    self._last_error = None
            if not accepted:
                return {"status": "dropped", "reason": "ambient_segment_queue_full", "dropped_chunks": dropped}
            result = {
                "status": "accepted",
                "events": 0,
                "ingested": 0,
                "queued_chunks": accepted,
                "mode": "external_final_utterance" if self.final_asr is not None else "voicemem_streaming",
            }
            if dropped:
                result["dropped_chunks"] = dropped
            return result
        except Exception as exc:
            with self._lock:
                self._last_error = self._safe_error(exc)
            return {"status": "degraded", "error": self._last_error}

    def flush(self, session_id: str) -> dict[str, Any]:
        return self.stop(session_id, flush=True)

    def start(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "ambient-audio")[:120]
        with self._lifecycle_lock:
            with self._lock:
                if self._stopping:
                    worker_alive = self._processing_worker is not None and self._processing_worker.is_alive()
                    segmenter_alive = bool(self._segmenter.state().get("running"))
                    if worker_alive or segmenter_alive:
                        raise RuntimeError("ambient audio is still stopping")
                    self._stopping = False
                    self._generation = None
                    self._session_id = None
                    self._processing_queue = None
                    self._processing_worker = None
                if self._generation is not None and self._session_id == normalized:
                    return self.state()
                if self._processing_worker is not None and self._processing_worker.is_alive():
                    raise RuntimeError("ambient ASR worker is still stopping")
            segment_state = self._segmenter.start(normalized)
            generation = segment_state.get("generation")
            if not segment_state.get("running") or segment_state.get("session_id") != normalized:
                raise RuntimeError("ambient segmenter is still stopping")
            processing_queue: Queue[AmbientSegment] = Queue(maxsize=self.processing_queue_size)
            processing_stop = Event()
            with self._lock:
                self._processing_queue = processing_queue
                self._processing_stop = processing_stop
                self._session_id = normalized
                self._generation = str(generation or "")
                worker = Thread(
                    target=self._process_segments,
                    args=(processing_queue, processing_stop),
                    name="ambient-asr-worker",
                    daemon=True,
                )
                self._processing_worker = worker
                worker.start()
                self._last_error = None
            return self.state()

    def stop(self, session_id: str | None = None, *, flush: bool = True, timeout: float = 2.0) -> dict[str, Any]:
        with self._lifecycle_lock:
            with self._lock:
                generation = self._generation
                current_session = self._session_id
                processing_queue = self._processing_queue
                processing_worker = self._processing_worker
                before_events = self._segment_events
                before_ingested = self._segment_ingested
                before_transcript = self._last_transcript
                before_description = self._last_description
                stopping = self._stopping
                if generation is None and not stopping:
                    result = self._flush_result(0, 0, before_transcript, before_description)
                    if not flush:
                        result["status"] = "cancelled"
                    return result
                if session_id is not None and current_session is not None and current_session != str(session_id or "ambient-audio")[:120]:
                    return {"status": "degraded", "error": "ambient_session_changed"}
                self._stopping = True
                if not flush:
                    self._generation = None
                    self._session_id = None
                    self._clear_processing_queue(processing_queue)
                    self._processing_stop.set()
            self._segmenter.stop(flush=flush, timeout=timeout)
            if flush:
                self._processing_stop.set()
            if processing_worker is not None and processing_worker is not current_thread():
                processing_worker.join(timeout=max(0.0, min(float(timeout), 10.0)))
            with self._lock:
                worker_alive = processing_worker is not None and processing_worker.is_alive()
                segmenter_alive = bool(self._segmenter.state().get("running"))
                if worker_alive or segmenter_alive:
                    status = "draining" if flush else "cancelled"
                    result = self._flush_result(
                        self._segment_events - before_events,
                        self._segment_ingested - before_ingested,
                        self._last_transcript or before_transcript,
                        self._last_description or before_description,
                    )
                    result["status"] = status
                    result["worker_alive"] = worker_alive
                    result["segmenter_alive"] = segmenter_alive
                    return result
                if self._generation == generation or generation is None:
                    self._generation = None
                    self._session_id = None
                    self._processing_queue = None
                    self._processing_worker = None
                    self._stopping = False
                events = self._segment_events - before_events
                ingested = self._segment_ingested - before_ingested
                transcript = self._last_transcript or before_transcript
                description = self._last_description or before_description
                result = self._flush_result(events, ingested, transcript, description)
                if not flush:
                    result["status"] = "cancelled"
                return result

    def state(self) -> dict[str, Any]:
        with self._lock:
            self._reap_stopped_locked()
            return {
                "target_sample_rate": self.target_sample_rate,
                "max_feed_bytes": self.max_feed_bytes,
                "chunks": self._chunks,
                "transcripts": self._transcripts,
                "dropped_events": self._dropped_events,
                "suppressed_self_tts": self._suppressed_self_tts,
                "last_error": self._last_error,
                "raw_audio_persisted": False,
                "conversation_turns_emitted": 0,
                "mode": "external_final_utterance" if self.final_asr is not None else "voicemem_streaming",
                "audio_description_configured": self.audio_describer is not None,
                "audio_description_buffered_bytes": 0,
                "audio_description_truncated": False,
                "active_session_id": self._session_id,
                "active_generation": self._generation,
                "segment_events": self._segment_events,
                "segment_ingested": self._segment_ingested,
                "segment_dropped": self._segment_dropped,
                "stale_segments": self._stale_segments,
                "asr_finishes": self._asr_finishes,
                "asr_discards": self._asr_discards,
                "cancelled_segments": self._cancelled_segments,
                "lifecycle": "stopping" if self._stopping else "running" if self._generation else "stopped",
                "processing_worker_alive": self._processing_worker is not None and self._processing_worker.is_alive(),
                "segmenter": self._segmenter.state(),
                "processing_queue_depth": self._processing_queue.qsize() if self._processing_queue is not None else 0,
            }

    def _reap_stopped_locked(self) -> None:
        if not self._stopping:
            return
        worker_alive = self._processing_worker is not None and self._processing_worker.is_alive()
        if worker_alive or self._segmenter.state().get("running"):
            return
        self._generation = None
        self._session_id = None
        self._processing_queue = None
        self._processing_worker = None
        self._stopping = False

    def _enqueue_segment(self, segment: AmbientSegment) -> None:
        with self._lock:
            if segment.generation != self._generation or self._processing_queue is None:
                self._stale_segments += 1
                return
            queue = self._processing_queue
            try:
                queue.put_nowait(segment)
            except Full:
                self._segment_dropped += 1

    def _process_segments(self, queue: Queue[AmbientSegment], stop: Event) -> None:
        try:
            while not stop.is_set() or not queue.empty():
                try:
                    segment = queue.get(timeout=0.05)
                except Empty:
                    continue
                try:
                    self._process_segment(segment)
                finally:
                    queue.task_done()
        finally:
            with self._lock:
                if self._processing_worker is current_thread():
                    self._processing_worker = None
                    if self._stopping and not self._segmenter.state().get("running"):
                        self._generation = None
                        self._session_id = None
                        self._processing_queue = None
                        self._stopping = False

    def _process_segment(self, segment: AmbientSegment) -> None:
        if not self._is_current(segment):
            with self._lock:
                self._stale_segments += 1
            return
        session_id = self._segment_session(segment)
        events: list[dict[str, Any]] = []
        succeeded = False
        try:
            if self.final_asr is not None:
                try:
                    for start in range(0, len(segment.pcm16), self.max_feed_bytes):
                        self.final_asr.feed_audio(
                            segment.pcm16[start : start + self.max_feed_bytes],
                            sample_rate=self.target_sample_rate,
                            channels=1,
                            session_id=session_id,
                        )
                    with self._lock:
                        self._asr_finishes += 1
                    transcription = self.final_asr.finish(session_id)
                except Exception:
                    self._discard_asr_session(session_id)
                    raise
                text = str(transcription.get("text") or "").strip()
                if text:
                    self._commit_transcript(segment, text, confidence=0.7, event_id=segment.segment_id)
            else:
                feed_error: Exception | None = None
                for start in range(0, len(segment.pcm16), self.max_feed_bytes):
                    try:
                        events.extend(self.voice_mem.feed_audio(
                            segment.pcm16[start : start + self.max_feed_bytes],
                            sample_rate=self.target_sample_rate,
                            session_id=session_id,
                        ))
                    except Exception as exc:
                        feed_error = exc
                        break
                try:
                    events.extend(self.voice_mem.end_audio(session_id=session_id))
                except Exception:
                    if feed_error is None:
                        raise
                if feed_error is not None:
                    raise feed_error
                if self._is_current(segment):
                    self._ingest_final_events(events, segment)
                elif events:
                    with self._lock:
                        self._stale_segments += 1
            succeeded = True
        except Exception as exc:
            with self._lock:
                self._last_error = self._safe_error(exc)
                self._segment_dropped += 1
        self._process_description(segment, session_id)
        if succeeded:
            with self._lock:
                self._last_error = None

    def _process_description(self, segment: AmbientSegment, session_id: str) -> None:
        if self.audio_describer is None:
            return
        if not self._is_current(segment):
            with self._lock:
                self._stale_segments += 1
            return
        try:
            if len(segment.pcm16) > self.max_description_bytes:
                result: dict[str, Any] = {"status": "skipped", "reason": "audio_description_clip_unbounded"}
            else:
                description = self.audio_describer.describe(
                    segment.pcm16,
                    sample_rate=self.target_sample_rate,
                    channels=1,
                    clip_id=segment.segment_id,
                )
                with self._lock:
                    if not self._is_current_locked(segment):
                        self._stale_segments += 1
                        return
                    stored = self.memory.ingest_audio_description(description, session_id=session_id)
                    result = {
                        "status": stored.get("status"),
                        "description": description,
                        "ingested": int(stored.get("status") == "retained"),
                    }
                    self._last_description = result
            with self._lock:
                if not self._is_current_locked(segment):
                    self._stale_segments += 1
                    return
                self._last_description = result
        except (AudioDescriptionUnavailable, ValueError, TypeError) as exc:
            with self._lock:
                if self._is_current_locked(segment):
                    self._last_description = {"status": "degraded", "reason": str(exc)[:160] or type(exc).__name__}
                else:
                    self._stale_segments += 1

    def _ingest_final_events(self, events: list[dict[str, Any]], segment: AmbientSegment) -> int:
        count = 0
        for event in events:
            if not isinstance(event, dict) or event.get("type") != "VOICE_TURN":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or not str(payload.get("text") or "").strip():
                continue
            result = self._commit_transcript(
                segment,
                str(payload["text"]),
                confidence=payload.get("confidence", 0.7),
                event_id=str(event.get("event_id") or "") or None,
            )
            if result is None:
                return count
            if result.get("status") == "retained":
                count += 1
            return count
        return count

    def _commit_transcript(
        self,
        segment: AmbientSegment,
        text: str,
        *,
        confidence: Any,
        event_id: str | None,
    ) -> dict[str, Any] | None:
        with self._lock:
            if not self._is_current_locked(segment):
                self._stale_segments += 1
                return None
            result = self.memory.ingest_system_audio(
                text,
                confidence=confidence,
                event_id=event_id,
                session_id=self._segment_session(segment),
            )
            self._segment_events += 1
            self._last_transcript = text[:1200]
            if result.get("status") == "retained":
                self._transcripts += 1
                self._segment_ingested += 1
            elif result.get("status") not in {"duplicate", "disabled"}:
                self._dropped_events += 1
                self._segment_dropped += 1
            return result

    def _discard_asr_session(self, session_id: str) -> None:
        discard = getattr(self.final_asr, "discard", None) or getattr(self.final_asr, "cancel", None)
        if not callable(discard):
            return
        try:
            discard(session_id)
        except Exception:
            return
        with self._lock:
            self._asr_discards += 1

    def _is_current(self, segment: AmbientSegment) -> bool:
        with self._lock:
            return self._is_current_locked(segment)

    def _is_current_locked(self, segment: AmbientSegment) -> bool:
        return segment.generation == self._generation and self._session_id == segment.session_id

    @staticmethod
    def _segment_session(segment: AmbientSegment) -> str:
        return f"ambient-audio:{segment.segment_id}"[:200]

    def _flush_result(
        self,
        events: int,
        ingested: int,
        transcript: str,
        description: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "flushed",
            "events": events,
            "ingested": ingested,
            "transcript": transcript,
            "mode": "external_final_utterance" if self.final_asr is not None else "voicemem_streaming",
        }
        if description is not None:
            result["audio_description"] = description
        return result

    def _clear_processing_queue(self, queue: Queue[AmbientSegment] | None) -> None:
        if queue is None:
            return
        while True:
            try:
                queue.get_nowait()
                with self._lock:
                    self._cancelled_segments += 1
                queue.task_done()
            except Empty:
                return

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

    def set_playback_suppression(self, marker: PlaybackSuppression | None) -> None:
        self.playback_suppression = marker

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, VoiceMemUnavailable):
            return "voicemem_unavailable"
        if isinstance(exc, ASRUnavailable):
            return "asr_unavailable"
        if isinstance(exc, AudioDescriptionUnavailable):
            return "audio_description_unavailable"
        return f"{type(exc).__name__}: {str(exc)[:160]}"[:200]


class AmbientAudioService:
    """Explicit lifecycle wrapper for loopback capture and bounded ASR segments."""

    def __init__(
        self,
        bridge: AmbientAudioASRBridge,
        *,
        capture: SystemAudioLoopback | None = None,
    ) -> None:
        self.bridge = bridge
        self.capture = capture or SystemAudioLoopback(bridge.consume, session_id="ambient-audio")

    def start(self) -> dict[str, Any]:
        if not self.bridge.memory.enabled:
            raise AmbientAudioDisabled("enable ambient memory before starting system audio")
        if self.capture.running:
            return self.state()
        self.bridge.start(self.capture.session_id)
        try:
            self.capture.start()
        except Exception:
            self.bridge.stop(self.capture.session_id, flush=False)
            raise
        return self.state()

    def stop(self) -> dict[str, Any]:
        try:
            capture_state = self.capture.stop()
        finally:
            flushed = self.bridge.stop(self.capture.session_id, flush=True)
        return {"capture": capture_state, "bridge": self.bridge.state(), "flush": flushed}

    def state(self) -> dict[str, Any]:
        return {
            "configured": True,
            "enabled": self.bridge.memory.enabled,
            "capture": self.capture.state(),
            "bridge": self.bridge.state(),
        }


__all__ = [
    "AmbientAudioASRBridge",
    "AmbientAudioDisabled",
    "AmbientAudioService",
    "PlaybackSuppression",
]
