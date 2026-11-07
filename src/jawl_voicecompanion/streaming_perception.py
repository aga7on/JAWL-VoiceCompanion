"""Continuous EG2 video/audio perception for the Companion."""

from __future__ import annotations

import base64
import math
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any


class StreamingPerception:
    """Bounded continuous EG2 sensory stream."""

    def __init__(
        self,
        *,
        screen_capture: Any,
        cortex: Any,
        describer: Any,
        fusion: Any,
        transcriber: Any | None = None,
        ambient_audio: Any | None = None,
        target_title: str = "",
        interval_seconds: float = 1.0,
        audio_window_seconds: float = 1.0,
        audio_queue_size: int = 8,
        audio_max_age_seconds: float = 2.0,
    ) -> None:
        self.screen_capture = screen_capture
        self.cortex = cortex
        self.describer = describer
        self.fusion = fusion
        self.transcriber = transcriber
        self.ambient_audio = ambient_audio
        self.target_title = str(target_title or "").strip()
        self.interval_seconds = max(0.5, min(float(interval_seconds), 10.0))
        self.audio_window_seconds = max(0.5, min(float(audio_window_seconds), 5.0))
        self.audio_max_age_seconds = max(0.5, min(float(audio_max_age_seconds), 30.0))
        self._audio_queue: Queue[tuple[int, float | None, bytes, int, int, str, int | None]] = Queue(
            maxsize=max(1, min(int(audio_queue_size), 32))
        )
        self._audio_lock = RLock()
        self._audio_buffer = bytearray()
        self._audio_buffer_start: float | None = None
        self._audio_buffer_timestamp_source = "unknown"
        self._audio_buffer_privacy_epoch: int | None = None
        self._audio_paused = False
        self._audio_epoch = 0
        self._audio_rate = 0
        self._audio_channels = 1
        self._stop = Event()
        self._video_thread: Thread | None = None
        self._audio_thread: Thread | None = None
        self._lock = RLock()
        self._lifecycle_lock = RLock()
        self._cortex_lock = RLock()
        self._video_count = 0
        self._audio_count = 0
        self._video_drops = 0
        self._audio_drops = 0
        self._audio_drops_stale = 0
        self._audio_drops_old = 0
        self._audio_drops_unknown_time = 0
        self._audio_reset_pending = False
        self._stop_requested = False
        self._last_video: dict[str, Any] = {}
        self._last_audio: dict[str, Any] = {}
        self._last_error: str | None = None
        self._ambient_started = False
        self._structured_summary = ""
        self._structured_at = 0.0
        self._structured_interval = 5.0

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(not self._stop.is_set() and self._video_thread and self._video_thread.is_alive())

    def start(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if self._stop_requested:
                    raise RuntimeError("streaming perception workers are still stopping")
                video_alive = bool(self._video_thread and self._video_thread.is_alive())
                audio_alive = bool(self._audio_thread and self._audio_thread.is_alive())
                if self._stop.is_set() and (video_alive or audio_alive):
                    raise RuntimeError("streaming perception workers are still stopping")
                if video_alive and audio_alive:
                    return
                if video_alive or audio_alive:
                    raise RuntimeError("streaming perception workers are not fully stopped")
            # A prior timed stop may have been unable to acquire the audio
            # lock. Clear its old epoch before admitting a replacement worker.
            if self._audio_reset_pending:
                if not self._audio_lock.acquire(blocking=False):
                    raise RuntimeError("streaming perception workers are still stopping")
                try:
                    self._reset_audio_locked()
                    self._audio_reset_pending = False
                finally:
                    self._audio_lock.release()
            else:
                with self._audio_lock:
                    self._reset_audio_locked()
            with self._lock:
                if self._stop_requested:
                    raise RuntimeError("streaming perception workers are still stopping")
                self._stop.clear()
                if self._last_error == "streaming_perception_workers_still_stopping":
                    self._last_error = None
                self._video_thread = Thread(target=self._video_loop, name="eg2-sensory-video", daemon=True)
                self._audio_thread = Thread(target=self._audio_loop, name="eg2-sensory-audio", daemon=True)
            if self.ambient_audio is not None:
                bridge = getattr(self.ambient_audio, "bridge", None)
                if bridge is not None:
                    bridge.stream_tap = self.consume_audio
                    bridge.stream_tap_owner = self
                # This worker subscribes to audio when available; permission
                # to configure a source must not implicitly start capture.
                # Capture lifecycle is owned by the explicit start/autostart.
            self._video_thread.start()
            self._audio_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + max(0.0, min(float(timeout), 10.0))
        self._stop_requested = True
        self._stop.set()
        if not self._lifecycle_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            self._last_error = "streaming_perception_workers_still_stopping"
            return
        cleanup_recorded = False
        try:
            # A fusion commit may be in progress under this lock. A timed stop
            # reports stopping instead of waiting indefinitely or claiming the
            # in-flight commit was cancelled.
            audio_locked = self._audio_lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
            if audio_locked:
                try:
                    self._reset_audio_locked()
                    self._audio_reset_pending = False
                finally:
                    self._audio_lock.release()
            else:
                self._audio_reset_pending = True
            if self.ambient_audio is not None:
                bridge = getattr(self.ambient_audio, "bridge", None)
                if bridge is not None:
                    bridge.stream_tap = None
                    bridge.stream_tap_owner = None
            for thread in (self._video_thread, self._audio_thread):
                if thread is not None and thread.is_alive() and thread is not current_thread():
                    thread.join(timeout=max(0.0, deadline - time.monotonic()))
            state_locked = self._lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
            if not state_locked:
                self._last_error = "streaming_perception_workers_still_stopping"
                return
            try:
                if self._video_thread is not None and not self._video_thread.is_alive():
                    self._video_thread = None
                if self._audio_thread is not None and not self._audio_thread.is_alive():
                    self._audio_thread = None
                if not audio_locked or self._video_thread is not None or self._audio_thread is not None:
                    self._last_error = "streaming_perception_workers_still_stopping"
                elif self._last_error == "streaming_perception_workers_still_stopping":
                    self._last_error = None
                cleanup_recorded = True
            finally:
                self._lock.release()
        finally:
            if cleanup_recorded:
                self._stop_requested = False
            self._lifecycle_lock.release()

    def _video_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._capture_video()
            except Exception as exc:  # noqa: BLE001 - sensor must stay alive
                with self._lock:
                    self._last_error = f"video: {type(exc).__name__}: {exc}"[:300]
            self._stop.wait(self.interval_seconds)

    def _capture_video(self) -> None:
        capture = self.screen_capture
        if capture is None:
            raise RuntimeError("screen capture is not configured")
        if self.target_title and hasattr(capture, "observe_window"):
            observation = capture.observe_window(self.target_title)
        else:
            observation = capture.observe()
        if not isinstance(observation, dict) or observation.get("status") != "verified":
            with self._lock:
                self._video_drops += 1
                self._last_error = "screen_capture_unavailable"
            return
        image = observation.get("image")
        encoded = image.get("data_base64") if isinstance(image, dict) else None
        if not isinstance(encoded, str) or not encoded:
            with self._lock:
                self._video_drops += 1
                self._last_error = "screen_capture_has_no_image"
            return
        image_bytes = base64.b64decode(encoded)
        started = time.perf_counter()
        observed_at = time.time()
        global_vec, token_vecs = self.cortex.embed_image_tokens(image_bytes)
        slices: list[dict[str, Any]] = []
        open_words = ""
        global_candidates: list[dict[str, Any]] = []
        if self.transcriber is not None:
            slices = self.transcriber.transcribe_image_vectors(
                global_vec, token_vecs, window_tokens=6, stride_tokens=4, top_k=6
            )
            global_candidates = self.transcriber.top_tokens(
                global_vec, top_k=8, min_score=0.50
            )
            open_words = self.transcriber.visual_transcript(
                slices,
                global_candidates=global_candidates,
                min_score=0.46,
                max_words=10,
            )
        open_score = (
            sum(float(item.get("score", 0.0)) for item in global_candidates[:5])
            / max(1, len(global_candidates[:5]))
        )
        structured = ""
        if self.describer is not None:
            moment = time.monotonic()
            if (
                not self._structured_summary
                or moment - self._structured_at >= self._structured_interval
            ):
                detailed = self.describer.describe_screen_detailed(image_bytes)
                self._structured_summary = str(
                    getattr(detailed, "description", "") or ""
                ).strip()[:600]
                self._structured_at = moment
            structured = self._structured_summary
        use_structured = (
            not open_words
            or len(open_words.split()) < 3
            or open_score < 0.50
        )
        summary = structured if use_structured and structured else open_words
        if not summary:
            with self._lock:
                self._video_drops += 1
                self._last_error = "vision_description_empty"
            return
        processed_at = time.time()
        metadata = {
            "observed_at": observed_at,
            "processed_at": processed_at,
            "age_ms": round(max(0.0, processed_at - observed_at) * 1000.0, 1),
            "source": "target_window" if self.target_title else "focused_window",
            "confidence": round(float(open_score if not use_structured else 0.5), 4),
            "selected": "structured" if use_structured and structured else "open_vocab",
            "open_vocab": open_words[:600],
            "structured": structured[:600],
            "structured_age_ms": (
                round(max(0.0, time.monotonic() - self._structured_at) * 1000.0, 1)
                if self._structured_at
                else None
            ),
        }
        self.fusion.observe_media(
            {"description": summary, "modality": "vision"},
            modality="vision",
            summary=summary,
            vector=global_vec,
            metadata=metadata,
            channel="eg2_media",
        )
        window = observation.get("window") if isinstance(observation.get("window"), dict) else {}
        with self._lock:
            self._video_count += 1
            self._last_video = {
                "summary": summary,
                "selected": metadata["selected"],
                "confidence": metadata["confidence"],
                "open_vocab": open_words,
                "structured": structured,
                "window_class": str(window.get("class_name") or "")[:120],
                "bounds": window.get("bounds"),
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "captured_at": observation.get("captured_at"),
                "regions": len(slices),
                "top_candidates": global_candidates[:6],
            }
            self._last_error = None

    def consume_audio(self, pcm16: bytes, sample_rate: int, channels: int, session_id: str, *,
                      captured_at: float | None = None, discontinuity: bool = False,
                      timestamp_source: str | None = None, privacy_epoch: int | None = None) -> None:
        if not pcm16:
            return
        rate = max(1, int(sample_rate))
        ch = max(1, int(channels))
        known_capture = (
            float(captured_at) if isinstance(captured_at, (int, float))
            and not isinstance(captured_at, bool) and math.isfinite(float(captured_at))
            and 0 <= float(captured_at) <= time.monotonic() + 1.0 else None
        )
        with self._audio_lock:
            if self._audio_paused or self._stop.is_set():
                return
            if not self._privacy_epoch_is_current(privacy_epoch):
                return
            if self._audio_buffer and self._audio_buffer_privacy_epoch != privacy_epoch:
                self._reset_audio_locked()
            if discontinuity:
                self._reset_audio_locked()
            if rate != self._audio_rate or ch != self._audio_channels:
                self._audio_buffer.clear()
                self._audio_buffer_start = None
                self._audio_buffer_timestamp_source = "unknown"
                self._audio_rate, self._audio_channels = rate, ch
            bytes_per_second = max(1, rate * ch * 2)
            chunk_source = str(timestamp_source or "upstream_monotonic_unspecified")[:80] if known_capture is not None else "unknown"
            if not self._audio_buffer:
                self._audio_buffer_privacy_epoch = privacy_epoch
                self._audio_buffer_start = (
                    known_capture - len(pcm16) / bytes_per_second if known_capture is not None else None
                )
                self._audio_buffer_timestamp_source = chunk_source
            elif known_capture is None:
                self._audio_buffer_start = None
                self._audio_buffer_timestamp_source = "unknown"
            elif self._audio_buffer_timestamp_source != chunk_source:
                self._audio_buffer_timestamp_source = "mixed"
            self._audio_buffer.extend(pcm16)
            needed = max(2, int(rate * self.audio_window_seconds) * ch * 2)
            if len(self._audio_buffer) < needed:
                return
            clip = bytes(self._audio_buffer[:needed])
            del self._audio_buffer[:needed]
            clip_end = (
                self._audio_buffer_start + needed / bytes_per_second
                if self._audio_buffer_start is not None else None
            )
            clip_source = self._audio_buffer_timestamp_source
            self._audio_buffer_start = clip_end if self._audio_buffer else None
            if not self._audio_buffer:
                self._audio_buffer_timestamp_source = "unknown"
            epoch = self._audio_epoch
            item = (epoch, clip_end, clip, rate, ch, clip_source, privacy_epoch)
            try:
                self._audio_queue.put_nowait(item)
            except Full:
                # Drop the oldest queued window, never the newest one.
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.task_done()
                except Empty:
                    pass
                with self._lock:
                    self._audio_drops_old += 1
                try:
                    self._audio_queue.put_nowait(item)
                except Full:
                    with self._lock:
                        self._audio_drops += 1

    def _reset_audio_locked(self) -> None:
        """Invalidate old windows without changing the explicit pause state."""
        self._audio_epoch += 1
        self._audio_buffer.clear()
        self._audio_buffer_start = None
        self._audio_buffer_timestamp_source = "unknown"
        self._audio_buffer_privacy_epoch = None
        self._audio_rate = 0
        self._audio_channels = 1
        while True:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.task_done()
            except Empty:
                break

    def pause_audio(self) -> None:
        """Drop partial and queued pre-pause windows from the streaming audio lane."""
        with self._audio_lock:
            self._audio_paused = True
            self._reset_audio_locked()

    def resume_audio(self) -> None:
        with self._audio_lock:
            self._reset_audio_locked()
            self._audio_paused = False

    def _audio_loop(self) -> None:
        while not self._stop.is_set():
            try:
                epoch, captured_at, clip, rate, ch, timestamp_source, privacy_epoch = self._audio_queue.get(timeout=0.5)
            except Empty:
                continue
            if not self._audio_epoch_is_current(epoch) or not self._privacy_epoch_is_current(privacy_epoch):
                self._audio_queue.task_done()
                continue
            if captured_at is None:
                with self._lock:
                    self._audio_drops_unknown_time += 1
                self._audio_queue.task_done()
                continue
            age = max(0.0, time.monotonic() - captured_at)
            if age > self.audio_max_age_seconds:
                with self._lock:
                    self._audio_drops_stale += 1
                self._audio_queue.task_done()
                continue
            try:
                self._process_audio(clip, rate, ch, age_s=age, audio_epoch=epoch,
                                    captured_at=captured_at, timestamp_source=timestamp_source,
                                    privacy_epoch=privacy_epoch)
            except Exception as exc:  # noqa: BLE001 - sensor must stay alive
                with self._lock:
                    self._last_error = f"audio: {type(exc).__name__}: {exc}"[:300]
            finally:
                self._audio_queue.task_done()

    def _process_audio(
        self, clip: bytes, rate: int, ch: int, *, age_s: float = 0.0,
        audio_epoch: int | None = None, captured_at: float | None = None,
        timestamp_source: str | None = None, privacy_epoch: int | None = None,
    ) -> None:
        started = time.perf_counter()
        vector = self.cortex.embed_audio_pcm16(clip, sample_rate=rate)
        open_words = ""
        if self.transcriber is not None:
            slices = self.transcriber.transcribe_pcm16(
                clip, sample_rate=rate, slice_seconds=0.5, top_k=5
            )
            open_words = self.transcriber.visual_transcript(
                slices, min_score=0.38, max_words=10
            )
        detailed = None
        if self.describer is not None:
            detailed = self.describer.describe_audio_pcm16(
                clip, sample_rate=rate, channels=ch
            )
        safe_audio: dict[str, Any] | None = None
        if detailed is not None:
            from .audio_understanding import safe_detailed_audio_claim

            safe_audio = safe_detailed_audio_claim(detailed, transcript=open_words)
        summary = open_words or (
            str(safe_audio.get("description") or "")[:600] if safe_audio else ""
        )
        if safe_audio is not None and not open_words:
            if safe_audio.get("kind") == "unknown":
                summary = ""
            elif safe_audio.get("kind") == "sound" and safe_audio.get("description") != (
                "Possible rhythmic sound; music is not independently verified."
            ):
                summary = ""
        if not summary:
            return
        processed_at = time.time()
        final_age = max(0.0, time.monotonic() - captured_at) if captured_at is not None else max(0.0, float(age_s))
        if captured_at is not None and final_age > self.audio_max_age_seconds:
            with self._lock:
                self._audio_drops_stale += 1
            return
        observed_at = processed_at - final_age
        metadata = {
            "observed_at": observed_at,
            "processed_at": processed_at,
            "age_ms": round(final_age * 1000.0, 1),
            "timestamp_source": (str(timestamp_source or "upstream_monotonic_unspecified")[:80]
                                 if captured_at is not None else "caller_age_estimate"),
            "wall_time_source": "estimated_from_monotonic_offset_at_processing",
            "source": "system_audio",
            "confidence": 0.0,
        }
        with self._audio_lock:
            if audio_epoch is not None and (
                self._stop.is_set() or self._audio_paused or self._audio_epoch != audio_epoch
            ):
                return
            memory = getattr(getattr(self.ambient_audio, "bridge", None), "memory", None)
            if memory is not None:
                with memory._lock:
                    if not self._privacy_epoch_is_current(privacy_epoch):
                        return
                    self._publish_audio(summary, vector, captured_at, observed_at, metadata)
            else:
                self._publish_audio(summary, vector, captured_at, observed_at, metadata)
        with self._lock:
            self._audio_count += 1
            self._last_audio = {
                "summary": summary,
                "level0": getattr(detailed, "level0", None),
                "confidence": metadata["confidence"],
                "age_ms": metadata["age_ms"],
                "observed_at": observed_at,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }

    def _publish_audio(self, summary: str, vector: Any, captured_at: float | None,
                       observed_at: float, metadata: dict[str, Any]) -> None:
            observation = {"description": summary, "modality": "audio"}
            note = getattr(self.fusion, "note", None)
            if captured_at is not None and callable(note):
                # RollingMediaBuffer timestamps use wall time; fusion channels
                # use monotonic time. Do not pass one clock as both.
                buffer = getattr(self.fusion, "media_buffer", None)
                if buffer is not None:
                    buffer.observe(observation, now=observed_at, modality="audio",
                                   summary=summary, vector=vector, metadata=metadata)
                note("sound", summary, now=captured_at, metadata=metadata)
            else:
                self.fusion.observe_media(observation, modality="audio", summary=summary,
                                          vector=vector, metadata=metadata, channel="sound")
    def _privacy_epoch_is_current(self, epoch: int | None) -> bool:
        memory = getattr(getattr(self.ambient_audio, "bridge", None), "memory", None)
        if memory is None:
            return True
        with memory._lock:
            return bool(memory.enabled and not memory.paused and epoch is not None and epoch == memory._privacy_epoch)

    def _audio_epoch_is_current(self, epoch: int) -> bool:
        with self._audio_lock:
            return not self._audio_paused and self._audio_epoch == epoch

    def state(self) -> dict[str, Any]:
        with self._lock:
            buffer = getattr(self.fusion, "media_buffer", None)
            buffer_state = buffer.state() if buffer is not None and hasattr(buffer, "state") else {}
            return {
                "running": bool(not self._stop.is_set() and self._video_thread and self._video_thread.is_alive()),
                "stopping": bool(self._stop.is_set() and (self._stop_requested or self._audio_reset_pending or any(
                    worker is not None and worker.is_alive() for worker in (self._video_thread, self._audio_thread)
                ))),
                "video_worker_alive": bool(self._video_thread and self._video_thread.is_alive()),
                "audio_worker_alive": bool(self._audio_thread and self._audio_thread.is_alive()),
                "interval_seconds": self.interval_seconds,
                "audio_window_seconds": self.audio_window_seconds,
                "audio_max_age_seconds": self.audio_max_age_seconds,
                "target_title": self.target_title,
                "video_count": self._video_count,
                "audio_count": self._audio_count,
                "video_drops": self._video_drops,
                "audio_drops": self._audio_drops,
                "audio_drops_stale": self._audio_drops_stale,
                "audio_drops_unknown_time": self._audio_drops_unknown_time,
                "audio_drops_old": self._audio_drops_old,
                "ambient_started": self._ambient_started,
                "last_video": dict(self._last_video),
                "last_audio": dict(self._last_audio),
                "last_error": self._last_error,
                "buffer": buffer_state,
            }

    def snapshot(self, *, seconds: float = 30.0, limit: int = 20) -> dict[str, Any]:
        result = self.state()
        buffer = getattr(self.fusion, "media_buffer", None)
        if buffer is not None and hasattr(buffer, "snapshot"):
            result["items"] = buffer.snapshot(seconds=seconds, limit=limit)
        return result
