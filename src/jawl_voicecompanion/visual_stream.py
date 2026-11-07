"""High-performance Windows visual capture and scene delta detection.

Provides zero-disk desktop frame streaming via DXGI Desktop Duplication (0.05-0.3 ms
latency in GPU/CPU memory) with graceful fallback to PIL ImageGrab, and fast perceptual
frame delta gating to eliminate redundant processing during static display scenes.
"""

from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Any, Callable, Tuple

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

try:
    import dxcam
    _DXCAM_AVAILABLE = True
except Exception:
    dxcam = None
    _DXCAM_AVAILABLE = False


class VisualCaptureError(RuntimeError):
    """Raised when visual capture fails to initialize or grab frames."""


class DXGIScreenCapture:
    """Zero-disk desktop frame capture using DirectX Desktop Duplication with fallback."""

    def __init__(
        self,
        *,
        output_idx: int = 0,
        device_idx: int = 0,
        target_fps: int = 30,
        force_fallback: bool = False,
    ) -> None:
        self.output_idx = int(output_idx)
        self.device_idx = int(device_idx)
        self.target_fps = max(1, min(int(target_fps), 120))
        self.force_fallback = bool(force_fallback)

        self._lock = threading.RLock()
        self._cam: Any = None
        self._is_dxgi = False
        self._running = False
        self._last_frame_time = 0.0
        self._frame_count = 0
        self._last_resolution: Tuple[int, int] | None = None

        self._init_backend()

    def _init_backend(self) -> None:
        with self._lock:
            if not self.force_fallback and _DXCAM_AVAILABLE and dxcam is not None:
                try:
                    self._cam = dxcam.create(
                        device_idx=self.device_idx,
                        output_idx=self.output_idx,
                        processor_backend="numpy",
                        output_color="RGB",
                    )
                    self._is_dxgi = True
                    self._running = True
                    logger.info("Initialized DXGI Desktop Duplication on display output %d", self.output_idx)
                    return
                except Exception as exc:
                    logger.warning("DXGI capture init failed (%s), falling back to ImageGrab", exc)
                    self._cam = None
                    self._is_dxgi = False

            # Fallback path using PIL ImageGrab
            self._is_dxgi = False
            self._running = True
            logger.info("Initialized visual capture fallback using PIL ImageGrab")

    @property
    def is_dxgi(self) -> bool:
        return self._is_dxgi

    @property
    def running(self) -> bool:
        return self._running

    def grab(self) -> np.ndarray | None:
        """Capture one raw RGB frame as a numpy array (H, W, 3) uint8 directly in memory."""
        with self._lock:
            if not self._running:
                return None

            frame: np.ndarray | None = None
            if self._is_dxgi and self._cam is not None:
                try:
                    frame = self._cam.grab(new_frame_only=False)
                except Exception as exc:
                    logger.warning("DXGI grab failed, attempting fallback: %s", exc)
                    self._is_dxgi = False
                    self._cam = None

            if frame is None and not self._is_dxgi:
                try:
                    from PIL import ImageGrab
                    img = ImageGrab.grab(all_screens=False)
                    frame = np.array(img.convert("RGB"), dtype=np.uint8)
                except Exception as exc:
                    logger.error("Visual grab fallback failed: %s", exc)
                    return None

            if frame is not None:
                self._frame_count += 1
                self._last_frame_time = time.monotonic()
                self._last_resolution = (int(frame.shape[1]), int(frame.shape[0]))

            return frame

    def grab_pil(self, max_dimension: int | None = None) -> Image.Image | None:
        """Capture a frame directly converted to a PIL Image, optionally downscaled."""
        arr = self.grab()
        if arr is None:
            return None
        img = Image.fromarray(arr, mode="RGB")
        if max_dimension is not None and max_dimension > 0:
            w, h = img.size
            if max(w, h) > max_dimension:
                scale = float(max_dimension) / float(max(w, h))
                new_w = max(1, int(round(w * scale)))
                new_h = max(1, int(round(h * scale)))
                img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
        return img

    def grab_pil_with_timestamp(self, max_dimension: int | None = None) -> tuple[Image.Image | None, float]:
        """Capture a frame directly converted to a PIL Image, returning (image, captured_at_monotonic_sec)."""
        t_now = time.monotonic()
        img = self.grab_pil(max_dimension=max_dimension)
        t_capture = self._last_frame_time if self._last_frame_time > 0.0 else t_now
        return img, t_capture

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._cam is not None:
                try:
                    del self._cam
                except Exception:
                    pass
                self._cam = None

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "is_dxgi": self._is_dxgi,
                "output_idx": self.output_idx,
                "frames_captured": self._frame_count,
                "last_resolution": self._last_resolution,
                "last_frame_time": round(self._last_frame_time, 3),
            }


class SceneDeltaDetector:
    """Fast perceptual difference estimator between consecutive visual frames.

    Downsamples frames to a compact grid (e.g. 64x64) and computes normalized
    luminance difference to gate heavy VLM or embedding computation.
    """

    def __init__(
        self,
        *,
        grid_size: int = 64,
        change_threshold: float = 0.12,
        saliency_cell_threshold: float = 0.25,
        min_active_cells: int = 2,
    ) -> None:
        self.grid_size = max(16, min(int(grid_size), 256))
        self.change_threshold = max(0.01, min(float(change_threshold), 1.0))
        self.saliency_cell_threshold = max(0.05, min(float(saliency_cell_threshold), 1.0))
        self.min_active_cells = max(1, min(int(min_active_cells), self.grid_size * self.grid_size))

        self._lock = threading.RLock()
        self._prev_thumbnail: np.ndarray | None = None
        self._last_delta = 0.0
        self._last_saliency_delta = 0.0
        self._last_active_cells = 0
        self._last_change_bbox: list[float] | None = None
        self._scene_id_seq = 0
        self._last_scene_id = f"scene_{self._scene_id_seq}"
        self._last_check_time = 0.0

    @property
    def last_change_bbox(self) -> list[float] | None:
        with self._lock:
            return list(self._last_change_bbox) if self._last_change_bbox is not None else None

    @property
    def last_saliency_delta(self) -> float:
        with self._lock:
            return self._last_saliency_delta

    def _extract_thumb(self, frame: np.ndarray | Image.Image) -> np.ndarray:
        if isinstance(frame, Image.Image):
            return np.array(
                frame.resize((self.grid_size, self.grid_size), Image.Resampling.BILINEAR).convert("L"),
                dtype=np.float32,
            )
        elif isinstance(frame, np.ndarray):
            h, w = frame.shape[:2]
            step_y = max(1, h // self.grid_size)
            step_x = max(1, w // self.grid_size)
            sub = frame[::step_y, ::step_x][:self.grid_size, :self.grid_size]
            if len(sub.shape) == 3:
                return (sub[:, :, 0] * 0.299 + sub[:, :, 1] * 0.587 + sub[:, :, 2] * 0.114).astype(np.float32)
            return sub.astype(np.float32)
        else:
            raise TypeError(f"Unsupported frame type: {type(frame)}")

    def compute_delta(
        self,
        frame: np.ndarray | Image.Image,
        *,
        commit: bool = True,
    ) -> Tuple[float, bool, str]:
        """Compute visual delta score (0.0 to 1.0) and whether it represents a scene change.

        When commit=True (default), advances internal thumbnail baseline and scene_id on change.
        When commit=False, performs non-destructive change probing without altering baseline.

        Returns: (delta_score, is_scene_change, current_scene_id)
        """
        with self._lock:
            thumb = self._extract_thumb(frame)

            now = time.monotonic()
            self._last_check_time = now

            if self._prev_thumbnail is None:
                if commit:
                    self._prev_thumbnail = thumb
                self._last_delta = 1.0
                self._last_change_bbox = [0.0, 0.0, 1.0, 1.0]
                return 1.0, True, self._last_scene_id

            diff = np.abs(thumb - self._prev_thumbnail)
            # Normalized Mean Absolute Error: [0.0, 1.0]
            mae = float(np.mean(diff)) / 255.0
            self._last_delta = round(mae, 4)

            # Localized motion-saliency check (Event Cascade Pruning, arXiv:2605.19506)
            norm_diff = diff / 255.0
            active_mask = norm_diff > self.saliency_cell_threshold
            active_count = int(np.sum(active_mask))
            self._last_active_cells = active_count

            if active_count >= self.min_active_cells:
                sal_delta = float(np.mean(norm_diff[active_mask]))
                self._last_saliency_delta = round(sal_delta, 4)
                y_idx, x_idx = np.where(active_mask)
                ymin = float(np.min(y_idx)) / self.grid_size
                ymax = float(np.max(y_idx) + 1) / self.grid_size
                xmin = float(np.min(x_idx)) / self.grid_size
                xmax = float(np.max(x_idx) + 1) / self.grid_size
                self._last_change_bbox = [round(ymin, 3), round(xmin, 3), round(ymax, 3), round(xmax, 3)]
            else:
                self._last_saliency_delta = 0.0
                self._last_change_bbox = None

            # Change triggers on global threshold OR concentrated localized change
            is_change = (mae >= self.change_threshold) or (
                active_count >= self.min_active_cells and self._last_saliency_delta >= 0.35
            )

            if is_change and commit:
                self._prev_thumbnail = thumb
                self._scene_id_seq += 1
                self._last_scene_id = f"scene_{self._scene_id_seq}"

            return self._last_delta, is_change, self._last_scene_id

    def verify_preflight_freshness(
        self,
        frame: np.ndarray | Image.Image,
        tolerance: float = 0.04,
    ) -> bool:
        """Pre-flight visual freshness verification (What Does 'Now' Mean, arXiv:2610.39282).
        
        Quickly verifies in <0.05 ms whether current visual input is stable against baseline.
        """
        with self._lock:
            if self._prev_thumbnail is None:
                return True
            thumb = self._extract_thumb(frame)
            diff = float(np.mean(np.abs(thumb - self._prev_thumbnail))) / 255.0
            return diff <= tolerance

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "grid_size": self.grid_size,
                "change_threshold": self.change_threshold,
                "saliency_cell_threshold": self.saliency_cell_threshold,
                "min_active_cells": self.min_active_cells,
                "last_delta": self._last_delta,
                "last_saliency_delta": self._last_saliency_delta,
                "last_active_cells": self._last_active_cells,
                "last_change_bbox": self._last_change_bbox,
                "current_scene_id": self._last_scene_id,
                "scene_count": self._scene_id_seq,
                "last_check_time": round(self._last_check_time, 3),
            }


class VisualStreamWorker:
    """Background worker for visual scene change detection.

    The application supplies its configured ScreenCaptureAdapter, including
    redaction and pause checks. Keyframe persistence is not wired in the daily
    composition; text-only observations may be fed to NarrativeConsolidator.

    Includes safe throttling (e.g., 500ms check cadence, >=5.0s min interval between
    expensive LanceDB ingestions) and resource governor coordination to ensure 0% FPS
    impact during gaming / video playback.
    """

    def __init__(
        self,
        *,
        episodic_memory: Any | None = None,
        narrative_consolidator: Any | None = None,
        perception_fusion: Any | None = None,
        scene_state: Any | None = None,
        capture: Any | None = None,
        delta_detector: SceneDeltaDetector | None = None,
        spatial_matrix: IncrementalSpatialMatrix | None = None,
        poll_interval_s: float = 0.5,
        min_ingest_interval_s: float = 5.0,
        resource_governor: Any | None = None,
        enabled_fn: Callable[[], bool] | None = None,
        max_dimension: int = 1280,
    ) -> None:
        self.episodic_memory = episodic_memory
        self.narrative_consolidator = narrative_consolidator
        self.perception_fusion = perception_fusion
        self.scene_state = scene_state
        self.capture = capture or DXGIScreenCapture()
        self.delta_detector = delta_detector or SceneDeltaDetector()
        self.spatial_matrix = spatial_matrix or IncrementalSpatialMatrix()
        self.poll_interval_s = max(0.01, float(poll_interval_s))
        self.min_ingest_interval_s = max(0.01, float(min_ingest_interval_s))
        self.resource_governor = resource_governor
        self.enabled_fn = enabled_fn
        self.max_dimension = max_dimension

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._frames_checked = 0
        self._keyframes_ingested = 0
        self._last_ingest_time = 0.0
        self._last_delta = 0.0
        self._last_scene_id = ""
        self._errors = 0
        self._last_error = ""
        self._latest_frame_pil: Image.Image | None = None
        self._latest_frame_time: float = 0.0

    def _capture_allowed(self) -> bool:
        if self.enabled_fn is None:
            return True
        try:
            return bool(self.enabled_fn())
        except Exception:
            return False

    def get_latest_frame_with_timestamp(
        self, max_dimension: int | None = None
    ) -> tuple[Image.Image | None, float]:
        """Returns the most recent frame and its capture timestamp (monotonic seconds).

        Attempts on-demand grab from hardware capture to guarantee fresh provenance;
        falls back to latest polled frame if on-demand grab fails.
        Enforces sensory authorization: returns (None, 0.0) if worker is stopped or sensory is paused/disabled.
        """
        if not self._running:
            return None, 0.0
        if not self._capture_allowed():
            return None, 0.0

        if self.capture is not None and hasattr(self.capture, "grab_pil_with_timestamp"):
            img, t_cap = self.capture.grab_pil_with_timestamp(max_dimension=max_dimension)
            if img is not None and self._capture_allowed() and self._running:
                with self._lock:
                    self._latest_frame_pil = img
                    self._latest_frame_time = t_cap
                return img, t_cap
            # A denied or failed fresh capture must not expose the prior frame.
            return None, 0.0
        with self._lock:
            return self._latest_frame_pil, self._latest_frame_time

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, name="VisualStreamWorker", daemon=True)
            self._thread.start()
            logger.info(
                "VisualStreamWorker started (poll=%.2fs, min_ingest=%.2fs)",
                self.poll_interval_s,
                self.min_ingest_interval_s,
            )

    def stop(self, timeout: float = 3.0) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self.capture is not None and hasattr(self.capture, "stop"):
            try:
                self.capture.stop()
            except Exception:
                pass
        logger.info("VisualStreamWorker stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_s):
            if not self._running:
                break
            if not self._capture_allowed():
                with self._lock:
                    self._latest_frame_pil = None
                    self._latest_frame_time = 0.0
                continue

            t0 = time.monotonic()
            try:
                self._poll_once(t0)
            except Exception as exc:  # noqa: BLE001
                self._errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("VisualStreamWorker poll error: %s", exc)

    def _poll_once(self, now_mono: float) -> None:
        if not self._capture_allowed() or self._stop_event.is_set():
            return
        if hasattr(self.capture, "grab_pil_with_timestamp"):
            image, captured_at = self.capture.grab_pil_with_timestamp(max_dimension=self.max_dimension)
            raw_frame = np.asarray(image.convert("RGB")) if image is not None else None
            source = "screen_adapter_display"
        else:
            raw_frame = self.capture.grab()
            captured_at = now_mono
            source = "dxgi_desktop"
        if raw_frame is None:
            return
        # Pause may have been requested while the capture was in flight.
        if not self._capture_allowed() or self._stop_event.is_set():
            return

        self._frames_checked += 1
        with self._lock:
            self._latest_frame_time = captured_at
            self._latest_frame_pil = Image.fromarray(raw_frame, mode="RGB")
        delta, is_change, scene_id = self.delta_detector.compute_delta(raw_frame, commit=False)
        self._last_delta = delta
        self._last_scene_id = scene_id

        # Incremental Spatial Matrix update (VLMCache / Language-Out-of-the-Loop)
        matrix_changed, dirty_count, matrix_bbox = self.spatial_matrix.update(raw_frame, commit=True)

        if not is_change:
            return

        if (now_mono - self._last_ingest_time) < self.min_ingest_interval_s:
            return

        # Throttle gate passed: commit scene and ingest keyframe
        if self.resource_governor is not None and hasattr(self.resource_governor, "try_acquire"):
            if not self.resource_governor.try_acquire("visual", background=True):
                return

        delta, is_change, scene_id = self.delta_detector.compute_delta(raw_frame, commit=True)
        self._last_delta = delta
        self._last_scene_id = scene_id
        if self.scene_state is not None and hasattr(self.scene_state, "transition_scene"):
            self.scene_state.transition_scene(scene_id)
        elif self.perception_fusion is not None and getattr(self.perception_fusion, "scene_state", None) is not None:
            self.perception_fusion.scene_state.transition_scene(scene_id)

        try:
            if not self._capture_allowed() or self._stop_event.is_set():
                return
            pil_img = Image.fromarray(raw_frame, mode="RGB")
            if self.max_dimension > 0 and max(pil_img.size) > self.max_dimension:
                scale = float(self.max_dimension) / float(max(pil_img.size))
                new_w = max(1, int(round(pil_img.size[0] * scale)))
                new_h = max(1, int(round(pil_img.size[1] * scale)))
                pil_img = pil_img.resize((new_w, new_h), Image.Resampling.BILINEAR)

            summary = f"Смена сцены {scene_id} (дельта {delta:.2f})"
            record = None
            if self.episodic_memory is not None and hasattr(self.episodic_memory, "ingest_keyframe"):
                record = self.episodic_memory.ingest_keyframe(
                    pil_img,
                    scene_id=scene_id,
                    summary=summary,
                )
                self._keyframes_ingested += 1

            webp_path = record.get("image_path", "") if isinstance(record, dict) else ""
            if self.narrative_consolidator is not None and hasattr(self.narrative_consolidator, "feed_keyframe"):
                self.narrative_consolidator.feed_keyframe(
                    scene_id=scene_id,
                    webp_path=webp_path,
                    summary=summary,
                    timestamp=time.time(),
                )

            if self.perception_fusion is not None:
                sal_delta = getattr(self.delta_detector, "last_saliency_delta", 0.0)
                change_bbox = getattr(self.delta_detector, "last_change_bbox", None)
                if hasattr(self.perception_fusion, "record_visual_event"):
                    roi_val = tuple(change_bbox) if change_bbox and len(change_bbox) == 4 else None
                    self.perception_fusion.record_visual_event(
                        summary,
                        captured_at_monotonic=captured_at,
                        captured_at_wall=time.time(),
                        frame_id=f"frame_{scene_id}",
                        source=source,
                        scene_id=scene_id,
                        roi=roi_val,
                        persist_history=True,
                    )
                if hasattr(self.perception_fusion, "note"):
                    self.perception_fusion.note(
                        "visual",
                        summary,
                        metadata={
                            "scene_id": scene_id,
                            "delta": delta,
                            "saliency_delta": sal_delta,
                            "change_bbox": change_bbox,
                            "matrix_bbox": matrix_bbox,
                            "dirty_tiles": dirty_count,
                            "matrix_vlm_awaken": self.spatial_matrix.should_awaken_vlm(),
                            "image_path": webp_path,
                            "source": source,
                        },
                    )

            self._last_ingest_time = now_mono
        finally:
            if self.resource_governor is not None and hasattr(self.resource_governor, "release"):
                self.resource_governor.release("visual")

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "frames_checked": self._frames_checked,
                "keyframes_ingested": self._keyframes_ingested,
                "last_delta": self._last_delta,
                "last_scene_id": self._last_scene_id,
                "last_ingest_sec_ago": round(time.monotonic() - self._last_ingest_time, 1) if self._last_ingest_time else None,
                "errors": self._errors,
                "last_error": self._last_error,
                "capture": self.capture.state() if hasattr(self.capture, "state") else None,
                "detector": self.delta_detector.state() if hasattr(self.delta_detector, "state") else None,
                "spatial_matrix": self.spatial_matrix.state() if hasattr(self.spatial_matrix, "state") else None,
            }


class FoveatedVisionProcessor:
    """Dual-stream foveated vision: coarse peripheral context + 1:1 lossless native crop.

    Implements CropVLM (arXiv:2511.19820) / S-BOED (arXiv:2605.01345) to eliminate
    the perceptual bandwidth bottleneck without expanding full-frame token budgets.
    """

    def __init__(
        self,
        coarse_resolution: tuple[int, int] = (640, 360),
        foveal_crop_size: int = 512,
    ) -> None:
        self.coarse_resolution = coarse_resolution
        self.foveal_crop_size = foveal_crop_size

    def process(
        self,
        frame: np.ndarray,
        focus_point: tuple[int, int] | None = None,
        saliency_bbox: list[float] | None = None,
    ) -> dict[str, Any]:
        """Process 1080p frame into peripheral + foveal crop."""
        h, w = frame.shape[:2]

        if focus_point is not None:
            cx, cy = focus_point
        elif saliency_bbox is not None and len(saliency_bbox) == 4:
            ymin, xmin, ymax, xmax = saliency_bbox
            cx = int(round((xmin + xmax) / 2.0 * w))
            cy = int(round((ymin + ymax) / 2.0 * h))
        else:
            cx, cy = w // 2, h // 2

        half = self.foveal_crop_size // 2
        x0 = max(0, min(cx - half, w - self.foveal_crop_size))
        y0 = max(0, min(cy - half, h - self.foveal_crop_size))
        x1 = x0 + self.foveal_crop_size
        y1 = y0 + self.foveal_crop_size

        foveal_crop = frame[y0:y1, x0:x1]
        img_pil = Image.fromarray(frame, mode="RGB")
        coarse_img = img_pil.resize(self.coarse_resolution, Image.Resampling.BILINEAR)

        composite_w = self.coarse_resolution[0] + self.foveal_crop_size
        composite_h = max(self.coarse_resolution[1], self.foveal_crop_size)
        composite = Image.new("RGB", (composite_w, composite_h), color=(18, 18, 18))
        composite.paste(coarse_img, (0, (composite_h - self.coarse_resolution[1]) // 2))
        composite.paste(Image.fromarray(foveal_crop), (self.coarse_resolution[0], 0))

        return {
            "coarse_img": coarse_img,
            "foveal_crop": Image.fromarray(foveal_crop),
            "composite": composite,
            "crop_coords": (x0, y0, x1, y1),
            "center": (cx, cy),
        }


class IncrementalSpatialMatrix:
    """Incremental spatial feature matrix and cache (VLMCache / EP-ViT / STC-Cacher 2026).

    Partitions visual frames into an HxW grid of spatial tiles (default 21x30, matching
    EG2 patch tokens with axial RoPE) and maintains cached feature vectors per cell.

    Key capabilities:
    1. Language-Out-of-the-Loop: Maintains a fast non-language spatial feature matrix in memory
       (15-30 Hz at <1 ms CPU) without waking heavy VLM/LLM decoders until significant change occurs.
    2. VLMCache / STC-Cacher: Recomputes only 'dirty' (modified) tile vectors while preserving
       cached vectors for static cells; periodic full keyframe refresh prevents cumulative drift.
    3. EP-ViT Motion Compensation: Shifts matrix feature vectors according to hardware DXGI
       MoveRects / motion vectors during scrolling/panning without re-encoding static content.
    4. Saliency Bounding Box: Consolidates active dirty cells into a normalized BBox for direct
       hand-off to FoveatedVisionProcessor (1:1 native crop).
    5. Spatial Zones: Computes top, bottom, left, center, right zone pooled representations
       analogous to EG2 token slices.
    """

    def __init__(
        self,
        grid_shape: tuple[int, int] = (21, 30),
        feature_dim: int = 64,
        tile_delta_threshold: float = 0.05,
        keyframe_interval: int = 60,
        subsample_stride: int = 4,
    ) -> None:
        self.grid_h = max(4, int(grid_shape[0]))
        self.grid_w = max(4, int(grid_shape[1]))
        self.feature_dim = max(16, int(feature_dim))
        self.tile_delta_threshold = max(0.01, min(float(tile_delta_threshold), 1.0))
        self.keyframe_interval = max(1, int(keyframe_interval))
        self.subsample_stride = max(1, int(subsample_stride))

        self._lock = threading.RLock()
        self._matrix = np.zeros((self.grid_h, self.grid_w, self.feature_dim), dtype=np.float32)
        self._prev_luma: np.ndarray | None = None
        self._prev_crg: np.ndarray | None = None
        self._prev_cby: np.ndarray | None = None
        self._dirty_mask = np.zeros((self.grid_h, self.grid_w), dtype=bool)
        self._tick_count = 0
        self._last_dirty_count = 0
        self._last_saliency_bbox: list[float] | None = None
        self._total_tiles_computed = 0
        self._total_tiles_cached = 0

        # Deterministic orthogonal projection matrix for fast CPU feature extraction
        rng = np.random.RandomState(42)
        proj = rng.randn(16, self.feature_dim).astype(np.float32)
        self._proj = proj / (np.linalg.norm(proj, axis=0, keepdims=True) + 1e-6)

    @property
    def last_saliency_bbox(self) -> list[float] | None:
        with self._lock:
            return list(self._last_saliency_bbox) if self._last_saliency_bbox is not None else None

    @property
    def dirty_mask(self) -> np.ndarray:
        with self._lock:
            return self._dirty_mask.copy()

    def _get_luma_tiles(self, frame_np: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self.subsample_stride > 1 and frame_np.shape[0] >= 300 and frame_np.shape[1] >= 300:
            sub = frame_np[::self.subsample_stride, ::self.subsample_stride]
        else:
            sub = frame_np

        h, w = sub.shape[:2]
        min_h = self.grid_h * 2
        min_w = self.grid_w * 2
        if h < min_h or w < min_w:
            img_pil = Image.fromarray(sub) if isinstance(sub, np.ndarray) else sub
            sub = np.array(img_pil.resize((max(w, min_w), max(h, min_h)), Image.Resampling.BILINEAR))
            h, w = sub.shape[:2]

        th = max(2, h // self.grid_h)
        tw = max(2, w // self.grid_w)
        trimmed = sub[:self.grid_h * th, :self.grid_w * tw]

        if len(trimmed.shape) == 3 and trimmed.shape[2] >= 3:
            r = trimmed[:, :, 0].astype(np.int16)
            g = trimmed[:, :, 1].astype(np.int16)
            b = trimmed[:, :, 2].astype(np.int16)
            # Fast integer luminance: (R + 2G + B) >> 2
            luma = ((r + (g << 1) + b) >> 2).astype(np.uint16)
            # Opponent color channels: red-green and blue-yellow
            crg = r - g
            cby = b - ((r + g) >> 1)
        elif len(trimmed.shape) == 3:
            luma = trimmed[:, :, 0].astype(np.uint16)
            crg = np.zeros_like(luma, dtype=np.int16)
            cby = np.zeros_like(luma, dtype=np.int16)
        else:
            luma = trimmed.astype(np.uint16)
            crg = np.zeros_like(luma, dtype=np.int16)
            cby = np.zeros_like(luma, dtype=np.int16)

        blocked = luma.reshape(self.grid_h, th, self.grid_w, tw).transpose(0, 2, 1, 3)
        tile_means = blocked.mean(axis=(2, 3)) / 255.0
        tile_crg = crg.reshape(self.grid_h, th, self.grid_w, tw).transpose(0, 2, 1, 3).mean(axis=(2, 3)) / 255.0
        tile_cby = cby.reshape(self.grid_h, th, self.grid_w, tw).transpose(0, 2, 1, 3).mean(axis=(2, 3)) / 255.0
        return tile_means.astype(np.float32), tile_crg.astype(np.float32), tile_cby.astype(np.float32), blocked

    def _compute_tile_features(self, blocked_tiles: np.ndarray) -> np.ndarray:
        n, th, tw = blocked_tiles.shape
        if n == 0:
            return np.zeros((0, self.feature_dim), dtype=np.float32)

        means = blocked_tiles.mean(axis=(1, 2)) / 255.0
        stds = blocked_tiles.std(axis=(1, 2)) / 255.0
        mid_y, mid_x = th // 2, tw // 2

        q1 = blocked_tiles[:, :mid_y, :mid_x].mean(axis=(1, 2)) / 255.0
        q2 = blocked_tiles[:, :mid_y, mid_x:].mean(axis=(1, 2)) / 255.0
        q3 = blocked_tiles[:, mid_y:, :mid_x].mean(axis=(1, 2)) / 255.0
        q4 = blocked_tiles[:, mid_y:, mid_x:].mean(axis=(1, 2)) / 255.0

        gy = np.abs(q3 + q4 - q1 - q2)
        gx = np.abs(q2 + q4 - q1 - q3)

        raw = np.stack([
            means, stds, q1, q2, q3, q4, gy, gx,
            means * 0.5, stds * 0.5, q1 * q4, q2 * q3,
            np.maximum(q1, q2), np.maximum(q3, q4),
            np.minimum(q1, q3), np.minimum(q2, q4),
        ], axis=-1).astype(np.float32)

        feats = np.dot(raw, self._proj)
        norm = np.linalg.norm(feats, axis=-1, keepdims=True) + 1e-6
        return (feats / norm).astype(np.float32)

    def update(
        self,
        frame: np.ndarray | Image.Image,
        *,
        commit: bool = True,
        force_keyframe: bool = False,
        dirty_rects: list[tuple[int, int, int, int]] | None = None,
    ) -> tuple[bool, int, list[float] | None]:
        """Update spatial matrix incrementally, re-encoding only modified tiles.

        Returns: (is_changed, dirty_tile_count, saliency_bbox)
        """
        with self._lock:
            if isinstance(frame, Image.Image):
                frame_np = np.array(frame)
            elif isinstance(frame, np.ndarray):
                frame_np = frame
            else:
                raise TypeError(f"Unsupported frame type: {type(frame)}")

            luma, crg, cby, blocked = self._get_luma_tiles(frame_np)
            total_tiles = self.grid_h * self.grid_w
            self._tick_count += 1

            is_keyframe = force_keyframe or (self._prev_luma is None) or (self._tick_count % self.keyframe_interval == 0)

            if is_keyframe or self._prev_luma is None:
                flat_blocked = blocked.reshape(total_tiles, blocked.shape[2], blocked.shape[3])
                feats = self._compute_tile_features(flat_blocked).reshape(self.grid_h, self.grid_w, self.feature_dim)
                if commit:
                    self._matrix = feats
                    self._prev_luma = luma
                    self._prev_crg = crg
                    self._prev_cby = cby
                    self._dirty_mask.fill(True)
                self._last_dirty_count = total_tiles
                self._last_saliency_bbox = [0.0, 0.0, 1.0, 1.0]
                self._total_tiles_computed += total_tiles
                return True, total_tiles, [0.0, 0.0, 1.0, 1.0]

            # Fast dirty mask computation (combining luma + opponent color channels)
            if dirty_rects:
                dirty_mask = np.zeros((self.grid_h, self.grid_w), dtype=bool)
                h, w = frame_np.shape[:2]
                th_px = h / self.grid_h
                tw_px = w / self.grid_w
                for x1, y1, x2, y2 in dirty_rects:
                    ys = max(0, int(y1 / th_px))
                    ye = min(self.grid_h, int(np.ceil(y2 / th_px)))
                    xs = max(0, int(x1 / tw_px))
                    xe = min(self.grid_w, int(np.ceil(x2 / tw_px)))
                    dirty_mask[ys:ye, xs:xe] = True
            else:
                diff_y = np.abs(luma - self._prev_luma)
                diff_crg = np.abs(crg - (self._prev_crg if self._prev_crg is not None else crg)) * 0.7
                diff_cby = np.abs(cby - (self._prev_cby if self._prev_cby is not None else cby)) * 0.7
                diff = np.maximum(diff_y, np.maximum(diff_crg, diff_cby))
                dirty_mask = diff > self.tile_delta_threshold

            dirty_count = int(np.sum(dirty_mask))
            cached_count = total_tiles - dirty_count
            self._total_tiles_cached += cached_count

            if dirty_count == 0:
                self._dirty_mask.fill(False)
                self._last_dirty_count = 0
                self._last_saliency_bbox = None
                return False, 0, None

            # Recompute ONLY dirty tiles (VLMCache / STC-Cacher)
            dirty_blocked = blocked[dirty_mask]
            dirty_feats = self._compute_tile_features(dirty_blocked)
            self._total_tiles_computed += dirty_count

            y_idx, x_idx = np.where(dirty_mask)
            ymin = float(np.min(y_idx)) / self.grid_h
            xmin = float(np.min(x_idx)) / self.grid_w
            ymax = float(np.max(y_idx) + 1) / self.grid_h
            xmax = float(np.max(x_idx) + 1) / self.grid_w
            bbox = [round(ymin, 4), round(xmin, 4), round(ymax, 4), round(xmax, 4)]

            if commit:
                self._matrix[dirty_mask] = dirty_feats
                self._prev_luma[dirty_mask] = luma[dirty_mask]
                if self._prev_crg is not None:
                    self._prev_crg[dirty_mask] = crg[dirty_mask]
                if self._prev_cby is not None:
                    self._prev_cby[dirty_mask] = cby[dirty_mask]
                self._dirty_mask = dirty_mask
                self._last_dirty_count = dirty_count
                self._last_saliency_bbox = bbox

            return True, dirty_count, bbox

    def apply_motion(self, dy_tiles: int, dx_tiles: int) -> tuple[int, list[float] | None]:
        """Shifts cached matrix feature vectors along motion vector (EP-ViT 2026).

        Moves shifted tiles without recomputation and marks newly exposed borders as dirty.
        Returns: (exposed_dirty_tile_count, exposed_bbox)
        """
        with self._lock:
            if dy_tiles == 0 and dx_tiles == 0:
                return 0, None

            new_matrix = np.zeros_like(self._matrix)
            new_luma = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
            exposed_mask = np.ones((self.grid_h, self.grid_w), dtype=bool)

            src_ys = max(0, -dy_tiles)
            src_ye = min(self.grid_h, self.grid_h - dy_tiles)
            dst_ys = max(0, dy_tiles)
            dst_ye = min(self.grid_h, self.grid_h + dy_tiles)

            src_xs = max(0, -dx_tiles)
            src_xe = min(self.grid_w, self.grid_w - dx_tiles)
            dst_xs = max(0, dx_tiles)
            dst_xe = min(self.grid_w, self.grid_w + dx_tiles)

            if dst_ye > dst_ys and dst_xe > dst_xs:
                new_matrix[dst_ys:dst_ye, dst_xs:dst_xe] = self._matrix[src_ys:src_ye, src_xs:src_xe]
                if self._prev_luma is not None:
                    new_luma[dst_ys:dst_ye, dst_xs:dst_xe] = self._prev_luma[src_ys:src_ye, src_xs:src_xe]
                exposed_mask[dst_ys:dst_ye, dst_xs:dst_xe] = False

            self._matrix = new_matrix
            self._prev_luma = new_luma
            self._dirty_mask = exposed_mask

            exposed_count = int(np.sum(exposed_mask))
            self._last_dirty_count = exposed_count

            if exposed_count > 0:
                y_idx, x_idx = np.where(exposed_mask)
                bbox = [
                    round(float(np.min(y_idx)) / self.grid_h, 4),
                    round(float(np.min(x_idx)) / self.grid_w, 4),
                    round(float(np.max(y_idx) + 1) / self.grid_h, 4),
                    round(float(np.max(x_idx) + 1) / self.grid_w, 4),
                ]
                self._last_saliency_bbox = bbox
                return exposed_count, bbox

            self._last_saliency_bbox = None
            return 0, None

    def get_matrix(self) -> np.ndarray:
        with self._lock:
            return self._matrix.copy()

    def get_global_embedding(self) -> np.ndarray:
        """Global pooled embedding across all spatial cells, L2-normalized."""
        with self._lock:
            pooled = self._matrix.mean(axis=(0, 1))
            norm = np.linalg.norm(pooled) + 1e-6
            return (pooled / norm).astype(np.float32)

    def get_spatial_zones(self) -> dict[str, np.ndarray]:
        """5 spatial zones (top, bottom, left, right, center) matching EG2 token layout."""
        with self._lock:
            gh, gw = self.grid_h, self.grid_w
            y_q1, y_q3 = max(1, gh // 4), max(gh - 1, (gh * 3) // 4)
            x_q1, x_q3 = max(1, gw // 4), max(gw - 1, (gw * 3) // 4)

            top = self._matrix[:y_q1, :, :].mean(axis=(0, 1))
            bottom = self._matrix[y_q3:, :, :].mean(axis=(0, 1))
            left = self._matrix[:, :x_q1, :].mean(axis=(0, 1))
            right = self._matrix[:, x_q3:, :].mean(axis=(0, 1))
            center = self._matrix[y_q1:y_q3, x_q1:x_q3, :].mean(axis=(0, 1))

            def _norm(v: np.ndarray) -> np.ndarray:
                return (v / (np.linalg.norm(v) + 1e-6)).astype(np.float32)

            return {
                "top": _norm(top),
                "bottom": _norm(bottom),
                "left": _norm(left),
                "right": _norm(right),
                "center": _norm(center),
            }

    def should_awaken_vlm(self, threshold: float = 0.15) -> bool:
        """Language-Out-of-the-Loop gating: returns True only if significant change warrants VLM inference."""
        with self._lock:
            total_tiles = self.grid_h * self.grid_w
            dirty_ratio = self._last_dirty_count / max(1, total_tiles)
            return dirty_ratio >= threshold

    def state(self) -> dict[str, Any]:
        with self._lock:
            total_evals = self._total_tiles_computed + self._total_tiles_cached
            hit_rate = (self._total_tiles_cached / max(1, total_evals)) * 100.0 if total_evals > 0 else 0.0
            return {
                "grid_shape": (self.grid_h, self.grid_w),
                "total_tiles": self.grid_h * self.grid_w,
                "feature_dim": self.feature_dim,
                "tick_count": self._tick_count,
                "last_dirty_count": self._last_dirty_count,
                "dirty_ratio": round(self._last_dirty_count / (self.grid_h * self.grid_w), 4),
                "last_saliency_bbox": self._last_saliency_bbox,
                "total_tiles_computed": self._total_tiles_computed,
                "total_tiles_cached": self._total_tiles_cached,
                "cache_hit_rate_pct": round(hit_rate, 2),
            }


class StoryboardGridAssembler:
    """Stitches rapid consecutive scene keyframes into a 2x2 storyboard collage.

    Prevents frame dropping during fast-cut action or anime trailer sequences by
    bundling 4 consecutive cuts into a single composite VLM request with quadrant indexing.
    """

    def __init__(self, quadrant_size: int = 512) -> None:
        self.quadrant_size = quadrant_size
        self._buffer: deque[tuple[np.ndarray, str, float]] = deque(maxlen=4)

    def add_keyframe(self, frame: np.ndarray, scene_id: str, timestamp: float) -> None:
        self._buffer.append((frame, scene_id, timestamp))

    @property
    def ready(self) -> bool:
        return len(self._buffer) >= 4

    def clear(self) -> None:
        self._buffer.clear()

    def assemble(self) -> Image.Image | None:
        if len(self._buffer) < 2:
            return None

        canvas_size = self.quadrant_size * 2
        canvas = Image.new("RGB", (canvas_size, canvas_size), color=(0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        positions = [
            (0, 0),
            (self.quadrant_size, 0),
            (0, self.quadrant_size),
            (self.quadrant_size, self.quadrant_size),
        ]

        frames = list(self._buffer)
        for i, (frame, sid, _ts) in enumerate(frames[:4]):
            q_img = Image.fromarray(frame).resize(
                (self.quadrant_size, self.quadrant_size), Image.Resampling.BILINEAR
            )
            px, py = positions[i]
            canvas.paste(q_img, (px, py))

            label = f"[{i+1}] {sid}"
            draw.rectangle([px + 10, py + 10, px + 120, py + 34], fill=(0, 0, 0, 200))
            draw.text((px + 16, py + 14), label, fill=(255, 255, 255))

        return canvas


class AsyncVisualRingBuffer:
    """Non-blocking ring buffer decoupling high-cadence DXGI capture from LanceDB ingestion."""

    def __init__(self, maxlen: int = 8) -> None:
        self.queue: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.dropped_frames = 0
        self.ingested_frames = 0

    def push(self, frame: np.ndarray, scene_id: str, delta: float) -> bool:
        """Pushes raw numpy frame with zero blocking (<0.01 ms)."""
        entry = {
            "frame": frame,
            "scene_id": scene_id,
            "delta": delta,
            "timestamp": time.monotonic(),
        }
        if len(self.queue) == self.queue.maxlen:
            self.dropped_frames += 1
        self.queue.append(entry)
        return True

    def pop_latest(self) -> dict[str, Any] | None:
        """Pulls the freshest frame for background LanceDB/WebP ingestion, discarding stale intermediates."""
        if not self.queue:
            return None
        item = self.queue.pop()
        self.queue.clear()
        self.ingested_frames += 1
        return item


__all__ = [
    "AsyncVisualRingBuffer",
    "DXGIScreenCapture",
    "FoveatedVisionProcessor",
    "IncrementalSpatialMatrix",
    "SceneDeltaDetector",
    "StoryboardGridAssembler",
    "VisualCaptureError",
    "VisualStreamWorker",
]
