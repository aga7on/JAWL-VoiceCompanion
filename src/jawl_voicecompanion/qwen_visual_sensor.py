"""Selectable Qwen visual describer over the existing screen capture.

One capture adapter, one running request plus one latest pending frame, a
change/scene/periodic trigger placed before attention, and a single delivery
per processed observation into PerceptionFusion.  Qwen is CPU-only here; EG2
keeps its own embeddings/memory channel.
"""

from __future__ import annotations

import base64
import time
from collections import deque
from dataclasses import asdict
from threading import Event, RLock, Thread
from typing import Any, Callable

import numpy as np
from PIL import Image

from .qwen_event_describer import QwenEventDescriber, QwenEventObservation


class QwenVisualSensor:
    """Bounded change-triggered Qwen caption lane."""

    def __init__(
        self,
        *,
        screen_capture: Any,
        describer: QwenEventDescriber,
        fusion: Any,
        on_observation: Callable[[QwenEventObservation], Any] | None = None,
        roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
        target_title: str = "",
        display_index: int | None = None,
        active_interval_s: float = 1.0,
        static_interval_s: float = 4.0,
        periodic_s: float = 4.0,
        poll_interval_s: float = 0.2,
        change_threshold: float = 0.02,
        scene_threshold: float = 0.08,
        activity_window_s: float = 3.0,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
    ) -> None:
        self.screen_capture = screen_capture
        self.describer = describer
        self.fusion = fusion
        self.on_observation = on_observation
        self.roi = self._normalize_roi(roi)
        self.target_title = str(target_title or "").strip()
        self.display_index = None if display_index is None else max(0, min(int(display_index), 3))
        self.active_interval_s = max(0.25, float(active_interval_s))
        self.static_interval_s = max(self.active_interval_s, float(static_interval_s))
        self.periodic_s = max(0.5, float(periodic_s))
        self.poll_interval_s = max(0.05, min(float(poll_interval_s), 2.0))
        self.change_threshold = max(0.0, min(float(change_threshold), 1.0))
        self.scene_threshold = max(self.change_threshold, min(float(scene_threshold), 1.0))
        self.activity_window_s = max(0.5, float(activity_window_s))
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._signature: np.ndarray | None = None
        self._scene_id = "scene-1"
        self._scene_counter = 1
        self._frame_counter = 0
        self._last_submit_at = 0.0
        self._last_ocr_at: float | None = None
        self._ocr_pending = True
        self._last_submit_reason = ""
        self._dirty = False
        self._dirty_reason = ""
        self._dirty_since = 0.0
        self._last_processed_at = 0.0
        self._last_delivered_frame = ""
        self._last_observation: QwenEventObservation | None = None
        self._change_times: deque[float] = deque(maxlen=32)
        self._history: deque[dict[str, Any]] = deque(maxlen=200)
        self._scene_changes = 0
        self._captures = 0
        self._submits = 0
        self._delivered = 0
        self._dropped_scene_change = 0
        self._scene_change_history_recorded = 0
        self._scene_change_history_rejected = 0
        self._stale_history_recorded = 0
        self._dropped_stale = 0
        self._capture_errors = 0
        self._last_error: str | None = None

    @staticmethod
    def _normalize_roi(roi: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        try:
            x, y, width, height = (float(value) for value in roi)
        except (TypeError, ValueError):
            return (0.0, 0.0, 1.0, 1.0)
        x = max(0.0, min(x, 1.0))
        y = max(0.0, min(y, 1.0))
        width = max(0.01, min(width, 1.0 - x))
        height = max(0.01, min(height, 1.0 - y))
        return (round(x, 4), round(y, 4), round(width, 4), round(height, 4))

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._loop, name="qwen-visual-sensor", daemon=True)
        self.describer.start()
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self.describer.stop(timeout=timeout)
        with self._lock:
            self._thread = None

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
        return round(ordered[index], 1)

    def state(self) -> dict[str, Any]:
        current_screen = self.fusion.current_state("screen", now=self._clock())
        with self._lock:
            latest = self._last_observation
            ages = [float(item.get("age_ms") or 0.0) for item in self._history]
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "roi": self.roi,
                "target_title": self.target_title,
                "display_index": self.display_index,
                "scene_id": self._scene_id,
                "captures": self._captures,
                "submits": self._submits,
                "delivered": self._delivered,
                # Backward-compatible counter: these results were not made
                # current because their scene had changed. They may still be
                # retained in the separate short visual-history channel.
                "dropped_scene_change": self._dropped_scene_change,
                "scene_change_history_recorded": self._scene_change_history_recorded,
                "scene_change_history_rejected": self._scene_change_history_rejected,
                "stale_history_recorded": self._stale_history_recorded,
                "dropped_stale": self._dropped_stale,
                "capture_errors": self._capture_errors,
                "last_error": self._last_error,
                "last_submit_reason": self._last_submit_reason,
                "scene_changes": self._scene_changes,
                "age_ms_p50": self._percentile(ages, 0.50),
                "age_ms_p95": self._percentile(ages, 0.95),
                "history_size": len(self._history),
                "dirty": self._dirty,
                "dirty_reason": self._dirty_reason,
                "dirty_age_ms": (
                    round(max(0.0, self._clock() - self._dirty_since) * 1000.0, 1)
                    if self._dirty
                    else 0.0
                ),
                "last_delivered_frame": self._last_delivered_frame,
                "last_observation": asdict(latest) if latest is not None else None,
                "latest_age_ms": (
                    round(max(0.0, self._wall_clock() - latest.observed_at) * 1000.0, 1)
                    if latest is not None
                    else None
                ),
                "caption_fresh": current_screen["fresh"],
                "caption_age_ms": current_screen.get("caption_age_ms", current_screen["age_ms"]),
                "caption_confirmed_age_ms": current_screen["age_ms"],
                "caption_ttl_ms": current_screen["ttl_ms"],
            }

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - sensor must stay alive
                with self._lock:
                    self._capture_errors += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"[:300]
            self._stop.wait(self.poll_interval_s)

    def _tick(self) -> None:
        self._deliver()
        capture_now = self._clock()
        ocr_enabled = bool(getattr(self.screen_capture, "ocr_enabled", False))
        ocr_due = ocr_enabled and (
            self._ocr_pending
            or self._dirty
            or self._last_ocr_at is None
            or capture_now - self._last_ocr_at >= self.static_interval_s
        )
        captured = self._capture(include_ocr=ocr_due)
        if captured is None:
            return
        image_bytes, signature, source, captured_wall, captured_monotonic, ocr_items = captured
        if ocr_due:
            self._last_ocr_at = captured_monotonic
            self._ocr_pending = False
        now = self._clock()
        score = self._change_score(signature)
        scene_change = self._signature is not None and score >= self.scene_threshold
        roi_change = self._signature is not None and score >= self.change_threshold
        self._signature = signature
        if not scene_change and not roi_change:
            confirm_caption = getattr(self.fusion, "confirm_caption", None)
            if callable(confirm_caption):
                try:
                    confirm_caption(
                        scene_id=self._scene_id,
                        confirmed_at_monotonic=captured_monotonic,
                        confirmed_at_wall=captured_wall,
                    )
                except Exception:
                    pass
        if scene_change:
            self._scene_counter += 1
            self._scene_id = f"scene-{self._scene_counter}"
            self._scene_changes += 1
            self._invalidate_previous_caption()
        if (scene_change or roi_change) and ocr_enabled and not ocr_due:
            self._ocr_pending = True
        if ocr_due:
            texts = [
                str(item.get("text") or "").strip()
                for item in ocr_items
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
            if texts:
                self.fusion.note(
                    "ocr",
                    " | ".join(texts),
                    now=captured_monotonic,
                    metadata={
                        "observed_at": captured_wall,
                        "source": "windows_ocr",
                        "capture_source": source,
                        "scene_id": self._scene_id,
                        "verified": False,
                    },
                )
            else:
                invalidate = getattr(self.fusion, "invalidate", None)
                if callable(invalidate):
                    try:
                        invalidate("ocr", now=captured_monotonic)
                    except Exception:
                        pass
        if roi_change or scene_change:
            self._change_times.append(now)
        active = scene_change or len([t for t in self._change_times if now - t <= self.activity_window_s]) >= 2
        pending_change = self._dirty_reason in {"scene_change", "roi_change"}
        min_interval = self.active_interval_s if (active or pending_change) else self.static_interval_s
        periodic_due = now - self._last_submit_at >= self.periodic_s
        if roi_change or scene_change or periodic_due:
            if not self._dirty:
                self._dirty_since = now
            self._dirty = True
            self._dirty_reason = "scene_change" if scene_change else "roi_change" if roi_change else "periodic"
        if not self._dirty:
            return
        if now - self._last_submit_at < min_interval:
            return
        reason = self._dirty_reason or "pending"
        self._frame_counter += 1
        frame_id = f"qwen-frame-{self._frame_counter}"
        submitted = self.describer.submit(
            image_bytes,
            observed_at=captured_wall,
            source=source,
            event_id=frame_id,
            frame_id=frame_id,
            scene_id=self._scene_id,
            roi=self.roi,
            captured_monotonic=captured_monotonic,
        )
        if not submitted:
            return
        with self._lock:
            self._submits += 1
            self._last_submit_at = now
            self._last_submit_reason = reason
            self._dirty = False
            self._dirty_reason = ""
            self._dirty_since = 0.0

    def _invalidate_previous_caption(self) -> None:
        invalidate = getattr(self.fusion, "invalidate", None)
        if callable(invalidate):
            try:
                invalidate("screen")
            except Exception:
                pass

    def _capture(
        self, *, include_ocr: bool = False,
    ) -> tuple[bytes, np.ndarray, str, float, float, list[dict[str, Any]]] | None:
        capture = self.screen_capture
        if capture is None:
            raise RuntimeError("screen capture is not configured")
        display_bounds: list[int] | None = None
        if self.display_index is not None and hasattr(capture, "capture_displays"):
            displays = capture.capture_displays(
                max_displays=self.display_index + 1, include_ocr=include_ocr
            )
            observation = displays[self.display_index] if len(displays) > self.display_index else None
            if isinstance(observation, dict):
                bounds = observation.get("bounds")
                if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
                    display_bounds = [int(value) for value in bounds]
        elif self.target_title and hasattr(capture, "observe_window"):
            observation = capture.observe_window(self.target_title, include_ocr=include_ocr)
        else:
            observation = capture.observe(include_ocr=include_ocr)
        # The adapter's returned frame is the capture boundary. Timestamp it
        # before base64 decoding, ROI crop, and JPEG encoding so those costs do
        # not disappear from the observation's freshness age.
        captured_wall = self._wall_clock()
        captured_monotonic = self._clock()
        if not isinstance(observation, dict) or observation.get("status") != "verified":
            with self._lock:
                self._capture_errors += 1
                self._last_error = "screen_capture_unavailable"
            return None
        image = observation.get("image")
        encoded = image.get("data_base64") if isinstance(image, dict) else None
        if not isinstance(encoded, str) or not encoded:
            with self._lock:
                self._capture_errors += 1
                self._last_error = "screen_capture_has_no_image"
            return None
        image_bytes = base64.b64decode(encoded)
        cropped, signature = self._crop(image_bytes)
        window = observation.get("window") if isinstance(observation.get("window"), dict) else {}
        capture_source = (
            f"display:{self.display_index}"
            if self.display_index is not None
            else "target_visible_region" if self.target_title else "focused_visible_region"
        )
        source = f"screen:{capture_source}"
        if display_bounds is not None:
            source += f":bounds={','.join(str(value) for value in display_bounds)}"
        source += f":roi={self.roi[0]},{self.roi[1]},{self.roi[2]},{self.roi[3]}"
        window_class = str(window.get("class_name") or "")[:64]
        if window_class:
            source += f":{window_class}"
        with self._lock:
            self._captures += 1
            self._last_error = None
        ocr_items = observation.get("ocr") if isinstance(observation.get("ocr"), list) else []
        return cropped, signature, source, captured_wall, captured_monotonic, ocr_items

    def _crop(self, image_bytes: bytes) -> tuple[bytes, np.ndarray]:
        image = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        x, y, roi_width, roi_height = self.roi
        box = (
            int(round(x * width)),
            int(round(y * height)),
            int(round((x + roi_width) * width)),
            int(round((y + roi_height) * height)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            box = (0, 0, width, height)
        cropped = image.crop(box)
        signature = np.asarray(cropped.convert("L").resize((32, 32)), dtype=np.float32)
        buffer = __import__("io").BytesIO()
        cropped.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue(), signature

    def _change_score(self, signature: np.ndarray) -> float:
        if self._signature is None:
            return 0.0
        return float(np.mean(np.abs(signature - self._signature)) / 255.0)

    def _deliver(self) -> None:
        observation = self.describer.poll()
        if observation is None:
            return
        if observation.processed_at == self._last_processed_at:
            return
        self._last_processed_at = observation.processed_at
        with self._lock:
            self._last_observation = observation
        # Deliver late captions with their original capture time. The brain's
        # context now labels their age instead of silently discarding them.
        if observation.scene_id and observation.scene_id != self._scene_id:
            # A late result must not become the current screen caption, but if
            # it is still inside the short event horizon it can help answer
            # "what just happened?" as history with its original provenance.
            record_event = getattr(self.fusion, "record_visual_event", None)
            archived = False
            if callable(record_event):
                archived = bool(record_event(
                    observation.caption,
                    captured_at_monotonic=observation.captured_monotonic,
                    captured_at_wall=observation.observed_at,
                    frame_id=observation.frame_id,
                    source=observation.source,
                    scene_id=observation.scene_id,
                    roi=observation.roi,
                    now=self._clock(),
                    persist_history=True,
                ))
            with self._lock:
                self._dropped_scene_change += 1
                if archived:
                    self._scene_change_history_recorded += 1
                else:
                    self._scene_change_history_rejected += 1
            return
        if observation.stale:
            # A stale caption is still useful for "what just happened?" while
            # it fits the short history horizon, but it must never refresh the
            # current screen channel. PerceptionFusion rejects events that are
            # older than its configured visual-history TTL.
            record_event = getattr(self.fusion, "record_visual_event", None)
            archived = False
            if callable(record_event):
                try:
                    archived = bool(record_event(
                        observation.caption,
                        captured_at_monotonic=observation.captured_monotonic,
                        captured_at_wall=observation.observed_at,
                        frame_id=observation.frame_id,
                        source=observation.source,
                        scene_id=observation.scene_id,
                        roi=observation.roi,
                        now=self._clock(),
                        persist_history=True,
                    ))
                except (TypeError, ValueError):
                    archived = False
            with self._lock:
                if archived:
                    self._stale_history_recorded += 1
                else:
                    self._dropped_stale += 1
            return
        self.fusion.observe_caption(
            observation.caption,
            captured_at_monotonic=observation.captured_monotonic,
            captured_at_wall=observation.observed_at,
            frame_id=observation.frame_id,
            source=observation.source,
            scene_id=observation.scene_id,
            roi=observation.roi,
        )
        with self._lock:
            self._delivered += 1
            self._last_delivered_frame = observation.frame_id
            self._history.append({
                "frame_id": observation.frame_id,
                "scene_id": observation.scene_id,
                "age_ms": observation.age_ms,
                "observed_at": observation.observed_at,
                "reason": self._last_submit_reason,
            })
        if self.on_observation is not None:
            self.on_observation(observation)
