"""System-audio to isolated VoiceMem/ambient-memory bridge."""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import replace
from math import isfinite
import sys
import time
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread, current_thread
from typing import Any

from .ambient_memory import AmbientMemoryBuffer
from .asr import UtteranceBuffer
from .audio_understanding import (
    AudioDescriptionService,
    AudioDescriptionUnavailable,
    TENTATIVE_RHYTHM_CUE,
)
from .ambient_segments import AmbientSegment, AmbientSegmenter
from .music_frame import build_music_frame
from .system_audio import SystemAudioLoopback
from .voicemem_client import VoiceMemUnavailable
from .transcript_quality import is_meaningful_transcript


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
        final_asr: UtteranceBuffer | None = None,
        audio_describer: AudioDescriptionService | None = None,
        soundscape_detector: Any | None = None,
        soundscape_source: str = "system_audio_loopback",
        perception_fusion: Any | None = None,
        max_description_bytes: int = 960000,
        segment_queue_size: int = 32,
        processing_queue_size: int = 8,
        description_queue_size: int = 2,
        soundscape_queue_size: int = 8,
        segment_queue_bytes: int | None = None,
        segment_max_bytes: int = 512 * 1024,
        segment_max_seconds: float = 15.0,
        soundscape_segment_max_seconds: float = 4.0,
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
        self.soundscape_detector = soundscape_detector
        self.soundscape_source = str(soundscape_source or "unknown")[:80]
        self.perception_fusion = perception_fusion
        self.stream_tap: Any | None = None
        self.stream_tap_owner: Any | None = None
        self._stream_tap_paused = False
        self.max_description_bytes = max(2048, min(int(max_description_bytes), 2 * 1024 * 1024)) & ~1
        self.segment_queue_size = max(1, min(int(segment_queue_size), 256))
        self.processing_queue_size = max(1, min(int(processing_queue_size), 64))
        self.description_queue_size = max(1, min(int(description_queue_size), 16))
        self.soundscape_queue_size = max(1, min(int(soundscape_queue_size), 64))
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
        self.soundscape_segment_max_seconds = max(2.0, min(float(soundscape_segment_max_seconds), 15.0))
        self._soundscape_segmenter = (
            AmbientSegmenter(
                self._enqueue_soundscape_segment,
                queue_size=self.segment_queue_size,
                max_chunk_bytes=self.max_feed_bytes,
                max_queue_bytes=segment_queue_bytes,
                max_segment_bytes=max(4 * 1024, min(
                    int(self.target_sample_rate * 2 * self.soundscape_segment_max_seconds),
                    4 * 1024 * 1024,
                )),
                max_segment_seconds=self.soundscape_segment_max_seconds,
            )
            if self.soundscape_detector is not None else None
        )
        self._processing_queue: Queue[AmbientSegment] | None = None
        self._description_queue: Queue[AmbientSegment] | None = None
        self._soundscape_queue: Queue[AmbientSegment] | None = None
        self._processing_stop = Event()
        self._description_stop = Event()
        self._soundscape_stop = Event()
        self._asr_cancel = Event()
        self._processing_worker: Thread | None = None
        self._description_worker: Thread | None = None
        self._soundscape_worker: Thread | None = None
        self._session_id: str | None = None
        self._generation: str | None = None
        self._soundscape_generation: str | None = None
        self._chunks = 0
        self._transcripts = 0
        self._asr_noise_filtered = 0
        self._last_transcript_observed_at: float | None = None
        self._dropped_events = 0
        self._suppressed_self_tts = 0
        self._segment_events = 0
        self._segment_ingested = 0
        self._segment_dropped = 0
        self._stale_segments = 0
        self._asr_finishes = 0
        self._last_transcript = ""
        self._last_description: dict[str, Any] | None = None
        self._description_latency_ms: deque[float] = deque(maxlen=200)
        self._description_count = 0
        self._description_errors = 0
        self._description_skipped = 0
        self._description_queue_dropped = 0
        self._description_queue_cancelled = 0
        self._last_description_latency_ms: float | None = None
        self._last_description_observed_at: float | None = None
        self._last_description_kind: str | None = None
        self._soundscape_count = 0
        self._soundscape_dropped = 0
        self._soundscape_stale = 0
        self._soundscape_cancelled = 0
        self._soundscape_errors = 0
        self._soundscape_latency_ms: deque[float] = deque(maxlen=200)
        self._last_soundscape_latency_ms: float | None = None
        self._last_soundscape_kind: str | None = None
        self._last_soundscape_tags: tuple[str, ...] = ()
        self._last_soundscape_windows: int | None = None
        self._last_soundscape_music_windows: int | None = None
        self._last_soundscape_music_score_max: float | None = None
        self._last_soundscape_music_score_median: float | None = None
        self._last_soundscape_observed_at: float | None = None
        self._last_soundscape_result: dict[str, Any] | None = None
        self._asr_discards = 0
        self._cancelled_segments = 0
        self._stopping = False
        self._last_error: str | None = None

    def consume(self, pcm16: bytes, sample_rate: int, channels: int, session_id: str) -> dict[str, Any]:
        self_tts_active = self.playback_suppression is not None and self.playback_suppression.active()
        if self_tts_active:
            with self._lock:
                self._suppressed_self_tts += 1
            # Without an independent soundscape lane, preserve the old complete
            # suppression behavior. When YAMNet is available, continue only that
            # non-ASR lane so game/music evidence is not lost during JAWL speech.
            if self._soundscape_segmenter is None:
                return {"status": "suppressed", "reason": "self_tts_playback"}
        try:
            capture_end = time.monotonic()
            converted = self._to_target_pcm(pcm16, sample_rate, channels, self.target_sample_rate)
            if not converted:
                return {"status": "ignored", "reason": "audio_chunk_empty"}
            with self._lifecycle_lock:
                with self._lock:
                    if self._stopping:
                        return {"status": "degraded", "error": "ambient_stopping"}
                    active_session = self._session_id
                    tap = None if self_tts_active or self._stream_tap_paused else self.stream_tap
                if tap is not None:
                    try:
                        tap(converted, self.target_sample_rate, 1, session_id)
                    except Exception:  # noqa: BLE001 - tap must not break ASR
                        pass
                if active_session is None:
                    self.start(session_id)
                    active_session = str(session_id or "ambient-audio")[:120]
                if active_session != str(session_id or "ambient-audio")[:120]:
                    return {"status": "degraded", "error": "ambient_session_changed"}
                accepted = 0
                dropped = 0
                soundscape_accepted = 0
                bytes_per_second = self.target_sample_rate * 2
                for start in range(0, len(converted), self.max_feed_bytes):
                    chunk = converted[start : start + self.max_feed_bytes]
                    chunk_end = capture_end - (len(converted) - start - len(chunk)) / bytes_per_second
                    if not self_tts_active:
                        result = self._segmenter.submit(
                            chunk, self.target_sample_rate, 1, captured_at=chunk_end
                        )
                        if result.get("status") == "accepted":
                            accepted += 1
                        elif result.get("status") == "dropped":
                            dropped += 1
                    if self._soundscape_segmenter is not None:
                        soundscape_result = self._soundscape_segmenter.submit(
                            chunk, self.target_sample_rate, 1, captured_at=chunk_end
                        )
                        if soundscape_result.get("status") == "accepted":
                            soundscape_accepted += 1
                        if soundscape_result.get("status") == "dropped":
                            with self._lock:
                                self._soundscape_dropped += 1
                with self._lock:
                    self._chunks += 1
                    self._segment_dropped += dropped
                    self._last_error = None
            if self_tts_active:
                if not soundscape_accepted:
                    return {"status": "dropped", "reason": "ambient_soundscape_queue_full"}
                return {
                    "status": "accepted",
                    "events": 0,
                    "ingested": 0,
                    "queued_chunks": soundscape_accepted,
                    "mode": "soundscape_only_self_tts",
                    "asr_suppressed": True,
                }
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

    def pause_stream_tap(self) -> None:
        with self._lifecycle_lock:
            self._stream_tap_paused = True
            pause = getattr(self.stream_tap_owner, "pause_audio", None)
            if callable(pause):
                pause()

    def resume_stream_tap(self) -> None:
        with self._lifecycle_lock:
            resume = getattr(self.stream_tap_owner, "resume_audio", None)
            if callable(resume):
                resume()
            self._stream_tap_paused = False

    def flush(self, session_id: str) -> dict[str, Any]:
        return self.stop(session_id, flush=True)

    def start(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "ambient-audio")[:120]
        with self._lifecycle_lock:
            with self._lock:
                if self._stopping:
                    worker_alive = self._processing_worker is not None and self._processing_worker.is_alive()
                    description_worker_alive = self._description_worker is not None and self._description_worker.is_alive()
                    soundscape_worker_alive = self._soundscape_worker is not None and self._soundscape_worker.is_alive()
                    segmenter_alive = bool(self._segmenter.state().get("running")) or bool(
                        self._soundscape_segmenter is not None
                        and self._soundscape_segmenter.state().get("running")
                    )
                    if worker_alive or description_worker_alive or soundscape_worker_alive or segmenter_alive:
                        raise RuntimeError("ambient audio is still stopping")
                    self._stopping = False
                    self._generation = None
                    self._soundscape_generation = None
                    self._session_id = None
                    self._processing_queue = None
                    self._description_queue = None
                    self._soundscape_queue = None
                    self._processing_worker = None
                    self._description_worker = None
                    self._soundscape_worker = None
                if self._generation is not None and self._session_id == normalized:
                    return self.state()
                if (
                    (self._processing_worker is not None and self._processing_worker.is_alive())
                    or (self._description_worker is not None and self._description_worker.is_alive())
                    or (self._soundscape_worker is not None and self._soundscape_worker.is_alive())
                ):
                    raise RuntimeError("ambient ASR worker is still stopping")
            self._invalidate_audio_context()
            segment_state = self._segmenter.start(normalized)
            generation = segment_state.get("generation")
            if not segment_state.get("running") or segment_state.get("session_id") != normalized:
                raise RuntimeError("ambient segmenter is still stopping")
            if self._soundscape_segmenter is not None:
                soundscape_segment_state = self._soundscape_segmenter.start(normalized)
                if not soundscape_segment_state.get("running") or soundscape_segment_state.get("session_id") != normalized:
                    self._segmenter.stop(flush=False)
                    raise RuntimeError("ambient soundscape segmenter is still stopping")
                soundscape_generation = str(soundscape_segment_state.get("generation") or "")
            else:
                soundscape_generation = None
            processing_queue: Queue[AmbientSegment] = Queue(maxsize=self.processing_queue_size)
            description_queue: Queue[AmbientSegment] | None = (
                Queue(maxsize=self.description_queue_size)
                if self.audio_describer is not None else None
            )
            soundscape_queue: Queue[AmbientSegment] | None = (
                Queue(maxsize=self.soundscape_queue_size)
                if self.soundscape_detector is not None else None
            )
            processing_stop = Event()
            description_stop = Event()
            soundscape_stop = Event()
            with self._lock:
                self._processing_queue = processing_queue
                self._description_queue = description_queue
                self._soundscape_queue = soundscape_queue
                self._processing_stop = processing_stop
                self._description_stop = description_stop
                self._soundscape_stop = soundscape_stop
                self._asr_cancel = Event()
                self._session_id = normalized
                self._generation = str(generation or "")
                self._soundscape_generation = soundscape_generation
                self._last_transcript = ""
                self._last_description = None
                self._last_description_observed_at = None
                self._last_description_kind = None
                self._last_soundscape_result = None
                self._description_queue_dropped = 0
                self._description_queue_cancelled = 0
                worker = Thread(
                    target=self._process_segments,
                    args=(processing_queue, processing_stop),
                    name="ambient-asr-worker",
                    daemon=True,
                )
                self._processing_worker = worker
                worker.start()
                description_worker = None
                if description_queue is not None:
                    description_worker = Thread(
                        target=self._process_descriptions,
                        args=(description_queue, description_stop),
                        name="ambient-description-worker",
                        daemon=True,
                    )
                    self._description_worker = description_worker
                    description_worker.start()
                else:
                    self._description_worker = None
                soundscape_worker = None
                if soundscape_queue is not None:
                    soundscape_worker = Thread(
                        target=self._process_soundscape_segments,
                        args=(soundscape_queue, soundscape_stop),
                        name="ambient-soundscape-worker",
                        daemon=True,
                    )
                    self._soundscape_worker = soundscape_worker
                    soundscape_worker.start()
                else:
                    self._soundscape_worker = None
                self._last_error = None
            return self.state()

    def stop(self, session_id: str | None = None, *, flush: bool = True, timeout: float = 2.0) -> dict[str, Any]:
        with self._lifecycle_lock:
            with self._lock:
                generation = self._generation
                current_session = self._session_id
                processing_queue = self._processing_queue
                processing_worker = self._processing_worker
                description_queue = self._description_queue
                description_worker = self._description_worker
                soundscape_queue = self._soundscape_queue
                soundscape_worker = self._soundscape_worker
                before_events = self._segment_events
                before_ingested = self._segment_ingested
                before_transcript = self._last_transcript if flush else ""
                before_description = self._last_description if flush else None
                stopping = self._stopping
                if generation is None and not stopping:
                    if not flush:
                        self._invalidate_audio_context()
                    result = self._flush_result(0, 0, before_transcript, before_description)
                    if not flush:
                        result["status"] = "cancelled"
                    return result
                if session_id is not None and current_session is not None and current_session != str(session_id or "ambient-audio")[:120]:
                    return {"status": "degraded", "error": "ambient_session_changed"}
                self._stopping = True
                if not flush:
                    self._asr_cancel.set()
                    self._generation = None
                    self._soundscape_generation = None
                    self._session_id = None
                    self._last_transcript = ""
                    self._last_description = None
                    self._clear_processing_queue(processing_queue)
                    self._clear_description_queue(description_queue)
                    self._clear_soundscape_queue(soundscape_queue)
                    self._processing_stop.set()
                    self._description_stop.set()
                    self._soundscape_stop.set()
            if not flush:
                self._invalidate_audio_context()
            self._segmenter.stop(flush=flush, timeout=timeout)
            if self._soundscape_segmenter is not None:
                self._soundscape_segmenter.stop(flush=flush, timeout=timeout)
            if flush:
                self._processing_stop.set()
                self._description_stop.set()
                self._soundscape_stop.set()
            if processing_worker is not None and processing_worker is not current_thread():
                processing_worker.join(timeout=max(0.0, min(float(timeout), 10.0)))
            if description_worker is not None and description_worker is not current_thread():
                description_worker.join(timeout=max(0.0, min(float(timeout), 10.0)))
            if soundscape_worker is not None and soundscape_worker is not current_thread():
                soundscape_worker.join(timeout=max(0.0, min(float(timeout), 10.0)))
            with self._lock:
                worker_alive = processing_worker is not None and processing_worker.is_alive()
                description_worker_alive = description_worker is not None and description_worker.is_alive()
                soundscape_worker_alive = soundscape_worker is not None and soundscape_worker.is_alive()
                segmenter_alive = bool(self._segmenter.state().get("running")) or bool(
                    self._soundscape_segmenter is not None
                    and self._soundscape_segmenter.state().get("running")
                )
                soundscape_segmenter_alive = bool(
                    self._soundscape_segmenter is not None
                    and self._soundscape_segmenter.state().get("running")
                )
                if worker_alive or description_worker_alive or soundscape_worker_alive or segmenter_alive or soundscape_segmenter_alive:
                    status = "draining" if flush else "cancelled"
                    result = self._flush_result(
                        self._segment_events - before_events,
                        self._segment_ingested - before_ingested,
                        self._last_transcript or before_transcript,
                        self._last_description or before_description,
                    )
                    result["status"] = status
                    result["worker_alive"] = worker_alive
                    result["description_worker_alive"] = description_worker_alive
                    result["soundscape_worker_alive"] = soundscape_worker_alive
                    result["segmenter_alive"] = segmenter_alive
                    result["soundscape_segmenter_alive"] = soundscape_segmenter_alive
                    return result
                if self._generation == generation or generation is None:
                    self._generation = None
                    self._soundscape_generation = None
                    self._session_id = None
                    self._processing_queue = None
                    self._description_queue = None
                    self._soundscape_queue = None
                    self._processing_worker = None
                    self._description_worker = None
                    self._soundscape_worker = None
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
            description_latencies = list(self._description_latency_ms)
            soundscape_age_ms = (
                max(0, round((time.monotonic() - self._last_soundscape_observed_at) * 1000.0))
                if self._last_soundscape_observed_at is not None
                else None
            )
            description_age_ms = (
                max(0, round((time.monotonic() - self._last_description_observed_at) * 1000.0))
                if self._last_description_observed_at is not None
                else None
            )
            description_freshness_ms = max(20_000, round(self.segment_max_seconds * 2_000))
            transcript_age_ms = (
                max(0, round((time.monotonic() - self._last_transcript_observed_at) * 1000.0))
                if self._last_transcript_observed_at is not None
                else None
            )
            description_provider = getattr(
                getattr(self.audio_describer, "provider", None), "name", None
            ) if self.audio_describer is not None else None
            return {
                "target_sample_rate": self.target_sample_rate,
                "max_feed_bytes": self.max_feed_bytes,
                "chunks": self._chunks,
                "transcripts": self._transcripts,
                "asr_noise_filtered": self._asr_noise_filtered,
                "transcript_last_age_ms": transcript_age_ms,
                "transcript_last_fresh": transcript_age_ms is not None and transcript_age_ms <= 120_000,
                "dropped_events": self._dropped_events,
                "suppressed_self_tts": self._suppressed_self_tts,
                "last_error": self._last_error,
                "raw_audio_persisted": False,
                "conversation_turns_emitted": 0,
                "mode": "external_final_utterance" if self.final_asr is not None else "voicemem_streaming",
                "audio_description_configured": self.audio_describer is not None,
                "audio_description_provider": str(description_provider or "audio-describer")[:40]
                if self.audio_describer is not None else None,
                "soundscape_configured": self.soundscape_detector is not None,
                "soundscape_count": self._soundscape_count,
                "soundscape_dropped": self._soundscape_dropped,
                "soundscape_stale": self._soundscape_stale,
                "soundscape_cancelled": self._soundscape_cancelled,
                "soundscape_errors": self._soundscape_errors,
                "soundscape_latency_ms_last": self._last_soundscape_latency_ms,
                "soundscape_latency_ms_p50": self._percentile(list(self._soundscape_latency_ms), 0.50),
                "soundscape_latency_ms_p95": self._percentile(list(self._soundscape_latency_ms), 0.95),
                "soundscape_last_kind": self._last_soundscape_kind,
                "soundscape_last_tags": list(self._last_soundscape_tags),
                "soundscape_last_windows": self._last_soundscape_windows,
                "soundscape_last_music_windows": self._last_soundscape_music_windows,
                "soundscape_last_music_score_max": self._last_soundscape_music_score_max,
                "soundscape_last_music_score_median": self._last_soundscape_music_score_median,
                "soundscape_last_music_frame": (
                    dict(self._last_soundscape_result.get("music_frame") or {})
                    if isinstance(self._last_soundscape_result, dict) else None
                ),
                "soundscape_last_age_ms": soundscape_age_ms,
                "soundscape_last_fresh": soundscape_age_ms is not None and soundscape_age_ms <= 20_000,
                "audio_description_buffered_bytes": 0,
                "audio_description_truncated": False,
                "audio_description_count": self._description_count,
                "audio_description_errors": self._description_errors,
                "audio_description_skipped": self._description_skipped,
                "audio_description_queue_dropped": self._description_queue_dropped,
                "audio_description_queue_cancelled": self._description_queue_cancelled,
                "audio_description_latency_ms_last": self._last_description_latency_ms,
                "audio_description_latency_ms_p50": self._percentile(description_latencies, 0.50),
                "audio_description_latency_ms_p95": self._percentile(description_latencies, 0.95),
                "audio_description_last_kind": self._last_description_kind,
                "audio_description_last_age_ms": description_age_ms,
                "audio_description_last_fresh": (
                    description_age_ms is not None and description_age_ms <= description_freshness_ms
                ),
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
                "audio_description_worker_alive": self._description_worker is not None and self._description_worker.is_alive(),
                "soundscape_worker_alive": self._soundscape_worker is not None and self._soundscape_worker.is_alive(),
                "segmenter": self._segmenter.state(),
                "soundscape_segmenter": self._soundscape_segmenter.state() if self._soundscape_segmenter is not None else None,
                "processing_queue_depth": self._processing_queue.qsize() if self._processing_queue is not None else 0,
                "audio_description_queue_depth": self._description_queue.qsize() if self._description_queue is not None else 0,
                "soundscape_queue_depth": self._soundscape_queue.qsize() if self._soundscape_queue is not None else 0,
            }

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
        return round(ordered[index], 1)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return max(0, int(value)) if value is not None else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _optional_score(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            score = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return round(min(1.0, max(0.0, score)), 4) if isfinite(score) else None

    @staticmethod
    def _render_audio_candidates(hypotheses: list[Any]) -> str:
        groups: list[str] = []
        for item in hypotheses[:7]:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()[:30]
            candidates = item.get("candidates")
            if not category or not isinstance(candidates, list):
                continue
            ranked: list[str] = []
            for candidate in candidates[:2]:
                if not isinstance(candidate, dict):
                    continue
                label = str(candidate.get("label") or "").strip()[:48]
                similarity = AmbientAudioASRBridge._optional_score(candidate.get("similarity"))
                if label and similarity is not None:
                    ranked.append(f"{label} {similarity:.2f}")
            if ranked:
                groups.append(f"{category}: " + " / ".join(ranked))
        if not groups:
            return ""
        return (
            "Модельные аудиогипотезы (не факты; сходство, не вероятность): "
            + "; ".join(groups)
        )[:520]

    @staticmethod
    def _render_sound_event_candidates(candidates: list[Any]) -> str:
        rendered: list[str] = []
        for item in candidates[:3]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:48]
            score = AmbientAudioASRBridge._optional_score(item.get("score"))
            hits = AmbientAudioASRBridge._optional_int(item.get("window_hits"))
            windows = AmbientAudioASRBridge._optional_int(item.get("windows"))
            if label and score is not None and hits is not None and windows:
                rendered.append(f"{label} (score {score:.2f}; {hits}/{windows} windows)")
        if not rendered:
            return ""
        return "Possible YAMNet sound-event class matches, unverified: " + "; ".join(rendered)

    @staticmethod
    def _wall_time_for_monotonic(observed_monotonic: float) -> float:
        """Translate a capture timestamp before passing it to wall-clock memory."""
        age_seconds = max(0.0, time.monotonic() - float(observed_monotonic))
        return time.time() - age_seconds

    def _record_description_latency_locked(self, segment: AmbientSegment, *, succeeded: bool) -> None:
        latency_ms = round(max(0.0, time.monotonic() - segment.ended_at) * 1000.0, 1)
        self._description_latency_ms.append(latency_ms)
        self._last_description_latency_ms = latency_ms
        if succeeded:
            self._description_count += 1
        else:
            self._description_errors += 1

    def _reap_stopped_locked(self) -> None:
        if not self._stopping:
            return
        worker_alive = self._processing_worker is not None and self._processing_worker.is_alive()
        description_worker_alive = self._description_worker is not None and self._description_worker.is_alive()
        soundscape_worker_alive = self._soundscape_worker is not None and self._soundscape_worker.is_alive()
        soundscape_segmenter_alive = bool(
            self._soundscape_segmenter is not None
            and self._soundscape_segmenter.state().get("running")
        )
        if worker_alive or description_worker_alive or soundscape_worker_alive or self._segmenter.state().get("running") or soundscape_segmenter_alive:
            return
        self._generation = None
        self._soundscape_generation = None
        self._session_id = None
        self._processing_queue = None
        self._description_queue = None
        self._soundscape_queue = None
        self._processing_worker = None
        self._description_worker = None
        self._soundscape_worker = None
        self._stopping = False

    def _enqueue_segment(self, segment: AmbientSegment) -> None:
        with self._lock:
            if segment.generation != self._generation or self._processing_queue is None:
                self._stale_segments += 1
                return
            queue = self._processing_queue
            if queue is not None:
                try:
                    queue.put_nowait(segment)
                except Full:
                    self._segment_dropped += 1
            description_queue = self._description_queue
            if description_queue is not None:
                try:
                    description_queue.put_nowait(segment)
                except Full:
                    # Audio descriptions are live state: discard the oldest
                    # pending clip so a slow model can catch up to recent sound.
                    try:
                        description_queue.get_nowait()
                        description_queue.task_done()
                        self._description_queue_dropped += 1
                    except Empty:
                        pass
                    try:
                        description_queue.put_nowait(segment)
                    except Full:
                        self._description_queue_dropped += 1

    def _enqueue_soundscape_segment(self, segment: AmbientSegment) -> None:
        with self._lock:
            if (
                segment.session_id != self._session_id
                or segment.generation != self._soundscape_generation
                or self._generation is None
                or self._soundscape_queue is None
            ):
                self._soundscape_stale += 1
                return
            queue = self._soundscape_queue
            current = replace(segment, generation=self._generation)
            try:
                queue.put_nowait(current)
            except Full:
                # Music is a live state: discard the oldest pending segment.
                try:
                    queue.get_nowait()
                    queue.task_done()
                    self._soundscape_dropped += 1
                except Empty:
                    pass
                try:
                    queue.put_nowait(current)
                except Full:
                    self._soundscape_dropped += 1

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
                    self._finish_stop_if_drained_locked()

    def _process_descriptions(self, queue: Queue[AmbientSegment], stop: Event) -> None:
        try:
            while not stop.is_set() or not queue.empty():
                try:
                    segment = queue.get(timeout=0.05)
                except Empty:
                    continue
                try:
                    if self._is_current(segment):
                        self._process_description(segment, self._segment_session(segment))
                    else:
                        with self._lock:
                            self._stale_segments += 1
                except Exception as exc:  # noqa: BLE001 - optional description must not kill future audio updates
                    with self._lock:
                        self._description_errors += 1
                        self._last_error = f"audio-description: {self._safe_error(exc)}"[:300]
                finally:
                    queue.task_done()
        finally:
            with self._lock:
                if self._description_worker is current_thread():
                    self._description_worker = None
                    self._finish_stop_if_drained_locked()

    def _process_soundscape_segments(self, queue: Queue[AmbientSegment], stop: Event) -> None:
        try:
            while not stop.is_set() or not queue.empty():
                try:
                    segment = queue.get(timeout=0.05)
                except Empty:
                    continue
                try:
                    self._process_soundscape_segment(segment)
                except Exception as exc:  # noqa: BLE001 - optional lane must not kill future music updates
                    with self._lock:
                        self._soundscape_errors += 1
                        self._last_error = f"soundscape: {self._safe_error(exc)}"[:300]
                finally:
                    queue.task_done()
        finally:
            with self._lock:
                if self._soundscape_worker is current_thread():
                    self._soundscape_worker = None
                    self._finish_stop_if_drained_locked()

    def _process_soundscape_segment(self, segment: AmbientSegment) -> None:
        if self.soundscape_detector is None or not self._is_current(segment):
            if not self._is_current(segment):
                with self._lock:
                    self._soundscape_stale += 1
            return
        soundscape = self._run_soundscape_detector(segment)
        if soundscape is None:
            return
        music_frame = build_music_frame(
            segment, soundscape, source=self.soundscape_source
        ).as_dict()
        ingested = self._ingest_soundscape(
            soundscape, segment, self._segment_session(segment), music_frame=music_frame
        )
        result = {
            "status": "retained" if ingested else "abstained",
            "segment_id": segment.segment_id,
            "description": soundscape,
            "music_frame": music_frame,
            "ingested": int(ingested),
        }
        with self._lock:
            if not self._is_current_locked(segment):
                self._soundscape_stale += 1
                return
            self._last_soundscape_result = result

    def _finish_stop_if_drained_locked(self) -> None:
        if not self._stopping:
            return
        processing_alive = self._processing_worker is not None and self._processing_worker.is_alive()
        description_worker_alive = self._description_worker is not None and self._description_worker.is_alive()
        soundscape_alive = self._soundscape_worker is not None and self._soundscape_worker.is_alive()
        soundscape_segmenter_alive = bool(
            self._soundscape_segmenter is not None
            and self._soundscape_segmenter.state().get("running")
        )
        if processing_alive or description_worker_alive or soundscape_alive or self._segmenter.state().get("running") or soundscape_segmenter_alive:
            return
        self._generation = None
        self._soundscape_generation = None
        self._session_id = None
        self._processing_queue = None
        self._description_queue = None
        self._soundscape_queue = None
        self._processing_worker = None
        self._description_worker = None
        self._soundscape_worker = None
        self._stopping = False

    def _process_segment(self, segment: AmbientSegment) -> None:
        with self._lock:
            if not self._is_current_locked(segment):
                self._stale_segments += 1
                return
            asr_cancel = self._asr_cancel
        session_id = self._segment_session(segment)
        events: list[dict[str, Any]] = []
        succeeded = False
        transcript = ""
        try:
            if self.final_asr is not None:
                try:
                    for start in range(0, len(segment.pcm16), self.max_feed_bytes):
                        self.final_asr.feed_audio(
                            segment.pcm16[start : start + self.max_feed_bytes],
                            sample_rate=self.target_sample_rate,
                            channels=1,
                            session_id=session_id,
                            cancel_event=asr_cancel,
                        )
                    with self._lock:
                        self._asr_finishes += 1
                    transcription = self.final_asr.finish(session_id)
                except Exception:
                    self._discard_asr_session(session_id)
                    raise
                candidate = str(transcription.get("text") or "").strip()
                if candidate:
                    stored = self._commit_transcript(
                        segment, candidate, confidence=0.0, event_id=segment.segment_id,
                    )
                    if stored is not None and stored.get("status") == "retained":
                        transcript = candidate
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
                    transcript = next((
                        str(event.get("payload", {}).get("text") or "").strip()
                        for event in events
                        if isinstance(event, dict)
                        and event.get("type") == "VOICE_TURN"
                        and isinstance(event.get("payload"), dict)
                        and str(event.get("payload", {}).get("text") or "").strip()
                        and is_meaningful_transcript(str(event.get("payload", {}).get("text") or ""))
                    ), "")
                elif events:
                    with self._lock:
                        self._stale_segments += 1
            succeeded = True
        except Exception as exc:
            with self._lock:
                self._last_error = self._safe_error(exc)
                self._segment_dropped += 1
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
                with self._lock:
                    if self._is_current_locked(segment):
                        self._description_skipped += 1
            else:
                description = self.audio_describer.describe(
                    segment.pcm16,
                    sample_rate=self.target_sample_rate,
                    channels=1,
                    clip_id=segment.segment_id,
                )
                if description is not None:
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
                        self._last_description_observed_at = segment.ended_at
                        self._last_description_kind = str(description.get("kind") or "unknown")[:32]
                        self._record_description_latency_locked(segment, succeeded=True)
                    candidate_hypotheses = description.get("candidate_hypotheses")
                    if (
                        stored.get("status") == "retained"
                        and isinstance(candidate_hypotheses, list)
                        and candidate_hypotheses
                        and self.perception_fusion is not None
                    ):
                        candidate_text = self._render_audio_candidates(candidate_hypotheses)
                        if candidate_text:
                            provider = getattr(self.audio_describer, "provider", self.audio_describer)
                            provider_name = str(
                                getattr(provider, "name", type(provider).__name__)
                            )[:80]
                            with self._lock:
                                if self._is_current_locked(segment):
                                    self.perception_fusion.note(
                                        "audio_candidates",
                                        candidate_text,
                                        now=segment.ended_at,
                                        metadata={
                                            "source": provider_name,
                                            "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                                            "segment_id": segment.segment_id,
                                            "observed_at_monotonic": segment.ended_at,
                                            "segment_started_monotonic": segment.started_at,
                                            "segment_ended_monotonic": segment.ended_at,
                                            "audio_kind": "music",
                                            "candidate_hypotheses": True,
                                            "score_type": "cosine_similarity_not_probability",
                                            "verified": False,
                                            "confidence": 0.0,
                                        },
                                    )
                                else:
                                    self._stale_segments += 1
                    if (
                        stored.get("status") == "retained"
                        and description.get("kind") == "sound"
                        and description.get("description") == TENTATIVE_RHYTHM_CUE
                        and not description.get("tags")
                        and not description.get("mood")
                        and float(description.get("confidence", -1)) == 0.0
                        and self.perception_fusion is not None
                    ):
                        with self._lock:
                            if self._is_current_locked(segment):
                                self.perception_fusion.note(
                                    "sound",
                                    TENTATIVE_RHYTHM_CUE,
                                    now=segment.ended_at,
                                    metadata={
                                        "source": "system_audio_loopback",
                                        "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                                        "segment_id": segment.segment_id,
                                        "observed_at_monotonic": segment.ended_at,
                                        "segment_started_monotonic": segment.started_at,
                                        "segment_ended_monotonic": segment.ended_at,
                                        "duration_ms": round(max(0.0, segment.ended_at - segment.started_at) * 1000.0, 1),
                                        "audio_kind": "sound",
                                        "verified": False,
                                        "confidence": 0.0,
                                    },
                                )
                            else:
                                self._stale_segments += 1
                    elif (
                        stored.get("status") == "retained"
                        and description.get("kind") == "music"
                        and self.perception_fusion is not None
                    ):
                        # Keep the caption model independent from YAMNet's
                        # music-presence evidence; one worker must not overwrite
                        # the other merely because it finished later.
                        provider = getattr(self.audio_describer, "provider", self.audio_describer)
                        provider_name = str(
                            getattr(provider, "name", type(provider).__name__)
                        )[:80]
                        text = f"Возможная музыка ({provider_name}, не подтверждена отдельно): " + str(
                            description.get("description") or "музыкальный фрагмент"
                        )
                        tags = list(description.get("tags") or [])[:4]
                        if tags:
                            text += "; теги: " + ", ".join(str(tag)[:40] for tag in tags)
                        if description.get("mood"):
                            text += "; возможное настроение: " + str(description["mood"])[:80]
                        with self._lock:
                            if self._is_current_locked(segment):
                                self.perception_fusion.note(
                                    "audio_description",
                                    text[:240],
                                    now=segment.ended_at,
                                    metadata={
                                        "source": provider_name,
                                        "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                                        "segment_id": segment.segment_id,
                                        "observed_at_monotonic": segment.ended_at,
                                        "segment_started_monotonic": segment.started_at,
                                        "segment_ended_monotonic": segment.ended_at,
                                        "duration_ms": round(max(0.0, segment.ended_at - segment.started_at) * 1000.0, 1),
                                        "audio_kind": "music",
                                        "caption_provider": provider_name,
                                        "verified": False,
                                        "confidence": float(description.get("confidence", 0.0)),
                                    },
                                )
                            else:
                                self._stale_segments += 1
            with self._lock:
                if not self._is_current_locked(segment):
                    self._stale_segments += 1
                    return
                self._last_description = result
        except (AudioDescriptionUnavailable, ValueError, TypeError) as exc:
            with self._lock:
                if self._is_current_locked(segment):
                    self._last_description = {"status": "degraded", "reason": str(exc)[:160] or type(exc).__name__}
                    self._record_description_latency_locked(segment, succeeded=False)
                else:
                    self._stale_segments += 1

    def _run_soundscape_detector(self, segment: AmbientSegment) -> dict[str, Any] | None:
        detector = self.soundscape_detector
        if detector is None:
            return None
        started = time.perf_counter()
        try:
            result = detector.describe(
                segment.pcm16,
                sample_rate=self.target_sample_rate,
                channels=1,
                clip_id=segment.segment_id,
            )
            if not isinstance(result, dict):
                raise TypeError("soundscape detector returned a non-object")
        except Exception as exc:  # noqa: BLE001 - optional sensor must not break ASR
            with self._lock:
                self._soundscape_errors += 1
                self._last_soundscape_latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
                self._soundscape_latency_ms.append(self._last_soundscape_latency_ms)
            return None
        latency = round((time.perf_counter() - started) * 1000.0, 1)
        with self._lock:
            if not self._is_current_locked(segment):
                self._soundscape_stale += 1
                return None
            self._soundscape_count += 1
            self._last_soundscape_latency_ms = latency
            self._soundscape_latency_ms.append(latency)
            kind = result.get("kind")
            self._last_soundscape_kind = str(kind)[:32] if kind is not None else "unknown"
            raw_tags = result.get("tags")
            raw_tags = raw_tags if isinstance(raw_tags, (list, tuple)) else ()
            self._last_soundscape_tags = tuple(
                str(tag)[:80]
                for tag in raw_tags[:4]
                if isinstance(tag, str) and tag.strip()
            )
            self._last_soundscape_windows = self._optional_int(result.get("windows"))
            self._last_soundscape_music_windows = self._optional_int(result.get("music_windows"))
            self._last_soundscape_music_score_max = self._optional_score(result.get("music_score_max"))
            self._last_soundscape_music_score_median = self._optional_score(result.get("music_score_median"))
            self._last_soundscape_observed_at = segment.ended_at
        return result

    def _ingest_soundscape(
        self,
        soundscape: dict[str, Any],
        segment: AmbientSegment,
        session_id: str,
        *,
        music_frame: dict[str, Any] | None = None,
    ) -> bool:
        is_music = str((music_frame or {}).get("state") or soundscape.get("kind")) == "music"
        tags = list(soundscape.get("tags") or [])[:8]
        stored_music = False
        with self._lock:
            if not self._is_current_locked(segment):
                self._soundscape_stale += 1
                return False
            # Long-term ambient memory remains music-only. Live perception also
            # publishes unknown so an old positive claim is replaced promptly.
            if is_music and not self.memory.paused:
                description = {
                    "schema_version": 1,
                    "clip_id": f"{segment.segment_id}:yamnet"[:120],
                    "kind": "music",
                    "description": str(soundscape.get("description") or "Music detected by the independent soundscape model.")[:600],
                    "tags": tags,
                    "mood": "",
                    "confidence": max(0.0, min(float(soundscape.get("confidence", 0.0)), 1.0)),
                    "duration_seconds": max(0.1, min(float(soundscape.get("duration_seconds", 0.1)), 30.0)),
                    "raw_audio_persisted": False,
                }
                stored = self.memory.ingest_audio_description(
                    description,
                    source_app="yamnet-onnx-cpu",
                    event_id=f"{segment.segment_id}:yamnet",
                    session_id=session_id,
                    now=self._wall_time_for_monotonic(segment.ended_at),
                )
                stored_music = stored.get("status") == "retained"
            if self.perception_fusion is not None:
                self.perception_fusion.invalidate("sound", now=segment.ended_at)
                raw_event_candidates = soundscape.get("event_candidates")
                raw_event_candidates = raw_event_candidates if isinstance(raw_event_candidates, list) else []
                event_text = self._render_sound_event_candidates(raw_event_candidates)
                if event_text:
                    self.perception_fusion.note(
                        "audio_event_candidates",
                        event_text,
                        now=segment.ended_at,
                        metadata={
                            "source": self.soundscape_source,
                            "detector": "yamnet-onnx-cpu",
                            "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                            "segment_id": segment.segment_id,
                            "observed_at_monotonic": segment.ended_at,
                            "segment_started_monotonic": segment.started_at,
                            "segment_ended_monotonic": segment.ended_at,
                            "window_count": int(soundscape.get("windows", 0) or 0),
                            "event_candidates": [dict(item) for item in raw_event_candidates[:3] if isinstance(item, dict)],
                            "audio_kind": "sound",
                            "verified": False,
                            "confidence_calibrated": False,
                            "independent_of_asr": True,
                        },
                    )
                else:
                    self.perception_fusion.invalidate("audio_event_candidates", now=segment.ended_at)
                if not is_music:
                    self.perception_fusion.invalidate("audio_description", now=segment.ended_at)
                    self.perception_fusion.invalidate("audio_candidates", now=segment.ended_at)
                windows = int(soundscape.get("windows", 0) or 0)
                music_windows = int(soundscape.get("music_windows", 0) or 0)
                text = (
                    f"Music detected by independent YAMNet ({music_windows}/{windows} windows)."
                    if is_music else
                    "YAMNet не подтвердил присутствие музыки в последнем сегменте; это не доказывает, что музыки нет."
                )
                self.perception_fusion.note(
                    "music",
                    text,
                    now=segment.ended_at,
                    metadata={
                        "source": self.soundscape_source,
                        "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                        "detector": "yamnet-onnx-cpu",
                        "segment_id": segment.segment_id,
                        "observed_at_monotonic": segment.ended_at,
                        "segment_started_monotonic": segment.started_at,
                        "segment_ended_monotonic": segment.ended_at,
                        "duration_ms": round(max(0.0, segment.ended_at - segment.started_at) * 1000.0, 1),
                        "window_count": windows,
                        "windows": windows,
                        "music_windows": music_windows,
                        "model_score": soundscape.get("confidence"),
                        "music_frame": dict(music_frame or {}),
                        "music_state": "music" if is_music else "unknown",
                        # Preserve stable detector labels for the brain as
                        # explicitly unverified model candidates, not facts.
                        "candidate_tags": tags[:4],
                        "candidate_tags_calibrated": False,
                        "rms_dbfs": (music_frame or {}).get("rms_dbfs"),
                        "energy_trend": (music_frame or {}).get("energy_trend", "unknown"),
                        "music_score_median": (music_frame or {}).get("music_score_median"),
                        "music_score_max": (music_frame or {}).get("music_score_max"),
                        "segment_started_monotonic": segment.started_at,
                        "segment_ended_monotonic": segment.ended_at,
                        "calibrated": False,
                        "independent_of_asr": True,
                    },
                )
                weak_music = soundscape.get("music_hypothesis")
                if is_music or not isinstance(weak_music, dict):
                    self.perception_fusion.invalidate("music_candidate", now=segment.ended_at)
                else:
                    raw_max = self._optional_score(weak_music.get("raw_score_max"))
                    raw_median = self._optional_score(weak_music.get("raw_score_median"))
                    music_windows = int(weak_music.get("music_windows", 0) or 0)
                    windows = int(weak_music.get("windows", soundscape.get("windows", 0)) or 0)
                    score_text = f"raw max={raw_max:.4f}" if raw_max is not None else "raw score unavailable"
                    self.perception_fusion.note(
                        "music_candidate",
                        f"Гипотеза YAMNet: возможен музыкальный или тональный фон; Music "
                        f"отмечен в {music_windows}/{windows} окнах ({score_text}, не вероятность). "
                        "Многокадровое подтверждение не пройдено.",
                        now=segment.ended_at,
                        metadata={
                            "source": self.soundscape_source,
                            "detector": "yamnet-onnx-cpu",
                            "segment_id": segment.segment_id,
                            "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                            "observed_at_monotonic": segment.ended_at,
                            "segment_started_monotonic": segment.started_at,
                            "segment_ended_monotonic": segment.ended_at,
                            "duration_ms": round(max(0.0, segment.ended_at - segment.started_at) * 1000.0, 1),
                            "music_score_max": raw_max,
                            "music_score_median": raw_median,
                            "music_windows": music_windows,
                            "required_windows": int(weak_music.get("required_windows", 0) or 0),
                            "score_type": "uncalibrated_raw_model_score",
                            "verified": False,
                            "confidence_calibrated": False,
                            "independent_of_asr": True,
                        },
                    )
        return stored_music

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
                confidence=payload.get("confidence", 0.0),
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
            if not is_meaningful_transcript(text):
                self._asr_noise_filtered += 1
                self._last_transcript = ""
                return {"status": "ignored", "reason": "asr_noise_hallucination"}
            result = self.memory.ingest_system_audio(
                text,
                confidence=confidence,
                event_id=event_id,
                session_id=self._segment_session(segment),
            )
            self._segment_events += 1
            # Stop/flush may return this value to the local control API. Keep
            # only text that passed AmbientMemory's privacy/retention gate.
            self._last_transcript = text[:1200] if result.get("status") == "retained" else ""
            if result.get("status") == "retained":
                self._transcripts += 1
                self._segment_ingested += 1
                self._last_transcript_observed_at = segment.ended_at
            elif result.get("status") not in {"duplicate", "disabled"}:
                self._dropped_events += 1
                self._segment_dropped += 1
            # Serialize fusion publication with stop()'s generation invalidation.
            # A pause either invalidates after this note, or wins first and makes
            # the generation check above reject the result.
            fusion = self.perception_fusion
            if result.get("status") == "retained" and fusion is not None:
                try:
                    fusion.note(
                        "speech",
                        f"System-audio transcript: {text[:500]}",
                        now=segment.ended_at,
                        metadata={
                            "source": "system_audio_loopback",
                            "observed_at": self._wall_time_for_monotonic(segment.ended_at),
                            "segment_id": segment.segment_id,
                            "observed_at_monotonic": segment.ended_at,
                            "segment_started_monotonic": segment.started_at,
                            "segment_ended_monotonic": segment.ended_at,
                            "duration_ms": round(max(0.0, segment.ended_at - segment.started_at) * 1000.0, 1),
                            "confidence": confidence,
                            "confidence_calibrated": False,
                            "verified": False,
                            "recognition_type": "ambient_asr_transcript",
                        },
                    )
                except Exception:  # noqa: BLE001 - a failed context hint must not break capture
                    pass
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

    def _invalidate_audio_context(self) -> None:
        fusion = self.perception_fusion
        if fusion is None:
            return
        try:
            fusion.invalidate("speech")
            fusion.invalidate("sound")
            fusion.invalidate("music")
            fusion.invalidate("audio_description")
            fusion.invalidate("audio_candidates")
            fusion.invalidate("audio_event_candidates")
        except Exception:  # noqa: BLE001 - context invalidation must not break lifecycle cleanup
            pass

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
        description_payload = dict(description) if description is not None else None
        if self._last_soundscape_result is not None:
            soundscape_payload = dict(self._last_soundscape_result)
            result["soundscape"] = soundscape_payload
            if description_payload is None:
                description_payload = {
                    "status": "classified",
                    "description": soundscape_payload.get("description"),
                    "ingested": 0,
                }
            described = description_payload.get("description")
            described_clip_id = described.get("clip_id") if isinstance(described, dict) else None
            if description is None or described_clip_id == soundscape_payload.get("segment_id"):
                description_payload["soundscape"] = soundscape_payload
        if description_payload is not None:
            result["audio_description"] = description_payload
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

    def _clear_description_queue(self, queue: Queue[AmbientSegment] | None) -> None:
        if queue is None:
            return
        while True:
            try:
                queue.get_nowait()
                with self._lock:
                    self._description_queue_cancelled += 1
                queue.task_done()
            except Empty:
                return

    def _clear_soundscape_queue(self, queue: Queue[AmbientSegment] | None) -> None:
        if queue is None:
            return
        while True:
            try:
                queue.get_nowait()
                with self._lock:
                    self._soundscape_cancelled += 1
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
        governor: Any | None = None,
    ) -> None:
        self.bridge = bridge
        self.capture = capture or SystemAudioLoopback(bridge.consume, session_id="ambient-audio")
        self.governor = governor
        self._paused = False
        self._lifecycle_lock = RLock()
        self._resume_error: str | None = None

    def start(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            if not self.bridge.memory.enabled:
                raise AmbientAudioDisabled("enable ambient memory before starting system audio")
            if self.capture.running:
                return self.state()
            self.bridge.start(self.capture.session_id)
            try:
                self.bridge.resume_stream_tap()
                self.capture.start()
                self._paused = False
                self._resume_error = None
            except Exception:
                self.bridge.pause_stream_tap()
                self.bridge.stop(self.capture.session_id, flush=False)
                raise
            return self.state()

    def stop(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            self.bridge.pause_stream_tap()
            try:
                capture_state = self.capture.stop()
            finally:
                flushed = self.bridge.stop(self.capture.session_id, flush=True)
            self._paused = False
            return {"capture": capture_state, "bridge": self.bridge.state(), "flush": flushed}

    def pause(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            self._paused = True
            self._resume_error = None
            self.bridge.pause_stream_tap()
            try:
                if self.capture.running:
                    capture_state = self.capture.stop()
                    if capture_state.get("running"):
                        self._resume_error = "capture_consumer_still_stopping"
            finally:
                # A pause must not let buffered PCM complete ASR and reappear as
                # current context after the source has been paused.
                self.bridge.stop(self.capture.session_id, flush=False)
            return self.state()

    def resume(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            if self.capture.running and self.bridge.state().get("lifecycle") == "running":
                self.bridge.resume_stream_tap()
                self._paused = False
                self._resume_error = None
            elif self.capture.running:
                capture_state = self.capture.stop()
                if capture_state.get("running"):
                    self._paused = True
                    self._resume_error = "capture_consumer_still_stopping"
                    return self.state()
            if not self.capture.running and self.bridge.memory.enabled:
                try:
                    self.bridge.start(self.capture.session_id)
                    self.bridge.resume_stream_tap()
                    self.capture.start()
                    self._paused = False
                    self._resume_error = None
                except Exception as exc:
                    self.bridge.pause_stream_tap()
                    self.bridge.stop(self.capture.session_id, flush=False)
                    self._paused = True
                    self._resume_error = self.bridge._safe_error(exc)
            else:
                self._paused = False
            return self.state()

    def _yields_to_game(self) -> bool:
        if self.governor is None:
            return False
        try:
            return bool(self.governor.state().get("gaming_mode"))
        except Exception:
            return False

    def state(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            result = {
                "configured": True,
                "enabled": self.bridge.memory.enabled,
                "paused": self._paused,
                "yields_to_game": self._yields_to_game(),
                "capture": self.capture.state(),
                "bridge": self.bridge.state(),
            }
            if self._resume_error:
                result["last_resume_error"] = self._resume_error
            return result


__all__ = [
    "AmbientAudioASRBridge",
    "AmbientAudioDisabled",
    "AmbientAudioService",
    "PlaybackSuppression",
]
