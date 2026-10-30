"""Continuous EG2 video/audio perception for the Companion."""

from __future__ import annotations

import base64
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
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
        self._audio_queue: Queue[tuple[int, float, bytes, int, int]] = Queue(
            maxsize=max(1, min(int(audio_queue_size), 32))
        )
        self._audio_lock = RLock()
        self._audio_buffer = bytearray()
        self._audio_paused = False
        self._audio_epoch = 0
        self._audio_rate = 0
        self._audio_channels = 1
        self._stop = Event()
        self._video_thread: Thread | None = None
        self._audio_thread: Thread | None = None
        self._lock = RLock()
        self._cortex_lock = RLock()
        self._video_count = 0
        self._audio_count = 0
        self._video_drops = 0
        self._audio_drops = 0
        self._audio_drops_stale = 0
        self._audio_drops_old = 0
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
            return bool(self._video_thread and self._video_thread.is_alive())

    def start(self) -> None:
        with self._lock:
            if self._video_thread and self._video_thread.is_alive():
                return
            self._stop.clear()
            self._video_thread = Thread(
                target=self._video_loop, name="eg2-sensory-video", daemon=True
            )
            self._audio_thread = Thread(
                target=self._audio_loop, name="eg2-sensory-audio", daemon=True
            )
        if self.ambient_audio is not None:
            bridge = getattr(self.ambient_audio, "bridge", None)
            if bridge is not None:
                bridge.stream_tap = self.consume_audio
                bridge.stream_tap_owner = self
            try:
                self.ambient_audio.start()
                self._ambient_started = True
            except Exception as exc:  # noqa: BLE001 - video can still run
                with self._lock:
                    self._last_error = f"ambient_audio: {type(exc).__name__}: {exc}"[:300]
        self._video_thread.start()
        self._audio_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.ambient_audio is not None:
            bridge = getattr(self.ambient_audio, "bridge", None)
            if bridge is not None:
                bridge.stream_tap = None
                bridge.stream_tap_owner = None
        for thread in (self._video_thread, self._audio_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        with self._lock:
            self._video_thread = None
            self._audio_thread = None

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

    def consume_audio(self, pcm16: bytes, sample_rate: int, channels: int, session_id: str) -> None:
        if not pcm16:
            return
        rate = max(1, int(sample_rate))
        ch = max(1, int(channels))
        with self._audio_lock:
            if self._audio_paused:
                return
            if rate != self._audio_rate or ch != self._audio_channels:
                self._audio_buffer.clear()
                self._audio_rate, self._audio_channels = rate, ch
            self._audio_buffer.extend(pcm16)
            needed = max(2, int(rate * self.audio_window_seconds) * ch * 2)
            if len(self._audio_buffer) < needed:
                return
            clip = bytes(self._audio_buffer[:needed])
            del self._audio_buffer[:needed]
            epoch = self._audio_epoch
        item = (epoch, time.monotonic(), clip, rate, ch)
        try:
            self._audio_queue.put_nowait(item)
        except Full:
            # Drop the oldest queued window, never the newest one: stale
            # sensory input is worse than a skipped window.
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

    def pause_audio(self) -> None:
        """Drop partial and queued pre-pause windows from the streaming audio lane."""
        with self._audio_lock:
            self._audio_paused = True
            self._audio_epoch += 1
            self._audio_buffer.clear()
            self._audio_rate = 0
            self._audio_channels = 1
            while True:
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.task_done()
                except Empty:
                    break

    def resume_audio(self) -> None:
        with self._audio_lock:
            self._audio_buffer.clear()
            self._audio_rate = 0
            self._audio_channels = 1
            self._audio_epoch += 1
            self._audio_paused = False

    def _audio_loop(self) -> None:
        while not self._stop.is_set():
            try:
                epoch, enqueued_at, clip, rate, ch = self._audio_queue.get(timeout=0.5)
            except Empty:
                continue
            if not self._audio_epoch_is_current(epoch):
                self._audio_queue.task_done()
                continue
            age = time.monotonic() - enqueued_at
            try:
                self._process_audio(clip, rate, ch, age_s=age, audio_epoch=epoch)
            except Exception as exc:  # noqa: BLE001 - sensor must stay alive
                with self._lock:
                    self._last_error = f"audio: {type(exc).__name__}: {exc}"[:300]
            finally:
                self._audio_queue.task_done()

    def _process_audio(
        self, clip: bytes, rate: int, ch: int, *, age_s: float = 0.0,
        audio_epoch: int | None = None,
    ) -> None:
        started = time.perf_counter()
        processed_at = time.time()
        observed_at = processed_at - max(0.0, float(age_s))
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
        metadata = {
            "observed_at": observed_at,
            "processed_at": processed_at,
            "age_ms": round(max(0.0, float(age_s)) * 1000.0, 1),
            "source": "system_audio",
            "confidence": 0.0,
        }
        with self._audio_lock:
            if audio_epoch is not None and (
                self._audio_paused or self._audio_epoch != audio_epoch
            ):
                return
            self.fusion.observe_media(
                {"description": summary, "modality": "audio"},
                modality="audio",
                summary=summary,
                vector=vector,
                metadata=metadata,
                channel="sound",
            )
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

    def _audio_epoch_is_current(self, epoch: int) -> bool:
        with self._audio_lock:
            return not self._audio_paused and self._audio_epoch == epoch

    def state(self) -> dict[str, Any]:
        with self._lock:
            buffer = getattr(self.fusion, "media_buffer", None)
            buffer_state = buffer.state() if buffer is not None and hasattr(buffer, "state") else {}
            return {
                "running": bool(self._video_thread and self._video_thread.is_alive()),
                "interval_seconds": self.interval_seconds,
                "audio_window_seconds": self.audio_window_seconds,
                "audio_max_age_seconds": self.audio_max_age_seconds,
                "target_title": self.target_title,
                "video_count": self._video_count,
                "audio_count": self._audio_count,
                "video_drops": self._video_drops,
                "audio_drops": self._audio_drops,
                "audio_drops_stale": self._audio_drops_stale,
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
