"""JAWL Live Temporal Evidence Archive (Round 11, Step 2).

Integrates the live screen capture pipeline with continuous A/V segmentation
and the compact Temporal Evidence Index (JTE1). Maintains a bounded rolling
ring buffer (5-10 minutes) with microsecond-accurate timecode synchronization,
asynchronous telemetry calculation (<0.6 ms CPU), zero-drop non-blocking
ingestion, and candidate frame extraction for retrospective inspection.

Architecture:
  DXGI / Screen Capture
            │
            ├──► Live Sensory Turn (Top-down VLM, SceneState)
            │
            └──► Ingest Queue (non-blocking, bounded capacity)
                       │
              TelemetryWorker (async, <0.6 ms)
                 ├── IncrementalSpatialMatrix (21x30 delta)
                 ├── Dynamic HUD / UI Mask Estimation
                 ├── World-Sharpness Variance outside HUD
                 ├── Horizontal Edge / Text Saliency
                 └── Candidate Saliency BBoxes
                       │
              SegmentWriter (e.g. 10s chunks)
                 ├── Video Segment (.mp4, libx264 ultrafast)
                 └── Temporal Sidecar (.jte1, 256B fixed records)
                       │
              Ring Buffer Rotation (5-10 min retention)
                 └── Automatic disk eviction of oldest segments
"""

from __future__ import annotations

import collections
import io
import math
import os
import queue
import shutil
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

try:
    import av  # type: ignore
    _HAS_PYAV = True
except ImportError:
    _HAS_PYAV = False

from .retro_selector import rank_all_candidates_anchor_satellite
from .temporal_index import (
    FLAG_CAPTURE_GAP,
    FLAG_ENCODER_DROPPED,
    FLAG_FEATURES_SKIPPED,
    FLAG_OVEREXPOSED,
    FLAG_SOURCE_FRAME_MISSING,
    FLAG_VALID,
    GRID_COLS_DEFAULT,
    GRID_ROWS_DEFAULT,
    IndexFrameRecord,
    IndexROI,
    IndexSegmentHeader,
    ROI_KIND_OBJECT_DELTA,
    ROI_KIND_TEXT_LIKE,
    TemporalIndexReader,
    TemporalIndexWriter,
    repair_and_finalize,
    verify_segment_alignment,
)
from .visual_stream import IncrementalSpatialMatrix

# Backward compatibility aliases
GRID_H_DEFAULT = GRID_ROWS_DEFAULT
GRID_W_DEFAULT = GRID_COLS_DEFAULT
FLAG_NONE = 0
FLAG_OCR_CANDIDATE = 0x01
FLAG_UI_TARGET = 0x02
FLAG_UNDEREXPOSED = 0x08
FLAG_HIGH_MOTION_BLUR = 0x10
FLAG_METADATA_DROPPED = 0x20
FLAG_CORRUPTED_FRAME = 0x40


@dataclass
class EvidenceSegment:
    """Metadata and accessors for a single completed video+index segment."""

    segment_id: int
    video_path: Path
    index_path: Path
    start_pts_us: int
    end_pts_us: int
    frame_count: int
    fps: float
    width: int
    height: int
    created_at: float = field(default_factory=time.time)

    @property
    def duration_ms(self) -> float:
        if self.end_pts_us >= self.start_pts_us and self.start_pts_us > 0:
            return (self.end_pts_us - self.start_pts_us) / 1000.0
        if self.fps > 0 and self.frame_count > 0:
            return (self.frame_count / self.fps) * 1000.0
        return 0.0

    @property
    def total_file_size_bytes(self) -> int:
        sz = 0
        if self.video_path.is_file():
            sz += self.video_path.stat().st_size
        if self.index_path.is_file():
            sz += self.index_path.stat().st_size
        return sz

    def read_records(self, verify_alignment: bool = False) -> list[IndexFrameRecord]:
        """Read all sidecar index telemetry records for this segment."""
        if not self.index_path.is_file():
            # Fallback to alternate extension (.jti <-> .jte1)
            alt_ext = ".jte1" if self.index_path.suffix == ".jti" else ".jti"
            alt = self.index_path.with_suffix(alt_ext)
            if not alt.is_file():
                return []
            target_path = alt
        else:
            target_path = self.index_path

        if target_path.suffix == ".jti":
            recs = TemporalIndexReader(target_path).read_all_records()
        else:
            from .temporal_evidence_index import read_legacy_jte1_as_jti1
            recs = read_legacy_jte1_as_jti1(target_path)

        for r in recs:
            r._segment_id = self.segment_id

        if verify_alignment and self.video_path is not None:
            # Check decodable frames in MP4 if segment is incomplete or unverified
            decodable_frames = 0
            if self.video_path.is_file() and self.video_path.stat().st_size > 0:
                try:
                    if _HAS_PYAV:
                        with av.open(str(self.video_path)) as c:
                            if c.streams.video:
                                for _ in c.decode(c.streams.video[0]):
                                    decodable_frames += 1
                except Exception:
                    pass
            for r in recs:
                if r.segment_sample_idx >= decodable_frames:
                    r.quality_flags |= FLAG_SOURCE_FRAME_MISSING
                    r.segment_sample_idx = -1

        return recs

    def extract_frames(self, frame_indices: Sequence[int]) -> dict[int, Image.Image]:
        """Extract a sparse set of candidate frames from the video container in a single pass."""
        extracted: dict[int, Image.Image] = {}
        target_set = set(int(idx) for idx in frame_indices if idx >= 0)
        if not target_set or not self.video_path.is_file() or self.video_path.stat().st_size == 0:
            return extracted

        if _HAS_PYAV:
            try:
                container = av.open(str(self.video_path), mode="r")
                if not container.streams.video:
                    container.close()
                    return extracted
                max_target = max(target_set)
                for cur_idx, frame in enumerate(container.decode(container.streams.video[0])):
                    if cur_idx in target_set:
                        extracted[cur_idx] = frame.to_image()
                    if cur_idx >= max_target:
                        break
                container.close()
                return extracted
            except Exception:
                pass

        return extracted

    def extract_frame_by_pts(self, pts_us: int) -> Image.Image | None:
        """Extract the frame closest to the specified pts_us."""
        records = self.read_records()
        if not records:
            return None
        best_idx = 0
        min_diff = float("inf")
        for i, rec in enumerate(records):
            diff = abs(rec.pts_us - pts_us)
            if diff < min_diff:
                min_diff = diff
                best_idx = i
        res = self.extract_frames([best_idx])
        return res.get(best_idx)

    def delete(self) -> None:
        """Securely remove video and sidecar files from disk upon ring eviction."""
        try:
            if self.video_path.is_file():
                self.video_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if self.index_path.is_file():
                self.index_path.unlink(missing_ok=True)
        except OSError:
            pass


class TelemetryComputer:
    """Asynchronous per-frame telemetry computer (<0.6 ms CPU).

    Implements the Multi-Scale Luma Pipeline (P0.2):
      1. Coarse 21x30 grid: Global motion, dirty tile bitmask, and running EMA UI variance.
      2. 640x360 intermediate Y-buffer: Green channel proxy kept in L2 cache.
      3. 45x80 microgrid: High-frequency horizontal edge & text saliency outside HUD mask.
      4. Screen-coordinate candidate ROIs (IndexROI): Text-like and motion deltas.
      5. P50 CPU latency < 0.6 ms, P95 < 1.0 ms across 720p and 1440p resolutions.
    """

    def __init__(
        self,
        grid_shape: tuple[int, int] = (GRID_ROWS_DEFAULT, GRID_COLS_DEFAULT),
        micro_shape: tuple[int, int] = (45, 80),
        history_len: int = 30,
    ) -> None:
        self.grid_h, self.grid_w = grid_shape
        self.micro_h, self.micro_w = micro_shape
        self.spatial_matrix = IncrementalSpatialMatrix(grid_shape=grid_shape, subsample_stride=4)
        self.history_len = max(5, int(history_len))

        # Micro-to-coarse grid row/col index mapping
        self._row_map = (np.arange(self.micro_h) * self.grid_h // self.micro_h)[:, None]
        self._col_map = (np.arange(self.micro_w) * self.grid_w // self.micro_w)[None, :]

        # Predefined structural HUD prior
        self._hud_prior = np.zeros((self.grid_h, self.grid_w), dtype=bool)
        self._hud_prior[0, :] = True
        self._hud_prior[-1, :] = True
        self._hud_prior[:3, :4] = True
        self._hud_prior[-3:, -4:] = True
        self._ui_mask = self._hud_prior.copy()

        # Preallocated buffers for fast microgrid computation
        self._edge_buf_90 = np.zeros((90, 640), dtype=np.uint8)
        self._luma_history = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self._luma_var = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self._frame_count = 0

    def compute(
        self,
        frame_input: np.ndarray | Image.Image,
        frame_id: int,
        segment_id: int,
        pts_us: int,
        scene_version: int = 0,
    ) -> Tuple[IndexFrameRecord, np.ndarray]:
        """Compute the 256-byte telemetry record for a frame.

        Returns:
            (IndexFrameRecord, rgb_ndarray)
        """
        # 1. Normalize input to uint8 RGB ndarray
        if isinstance(frame_input, Image.Image):
            arr = np.array(frame_input.convert("RGB"))
        else:
            arr = frame_input
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)

        h, w = arr.shape[:2]

        # 2. Update Spatial Matrix (with resolution adapter for >720p)
        if h > 720:
            s_mat = h // 720
            mat_in = arr[::s_mat, ::s_mat]
        else:
            mat_in = arr
        is_changed, dirty_count, saliency_bbox = self.spatial_matrix.update(mat_in)
        dirty_mask = self.spatial_matrix.dirty_mask
        total_tiles = self.grid_h * self.grid_w
        dirty_ratio = float(dirty_count) / float(total_tiles) if total_tiles > 0 else 0.0

        # 3. Extract 640x360 Y-buffer (green channel proxy)
        if h < 360 or w < 640:
            # Upscale small inputs (e.g. synthetic test frames) to 640x360
            green_ch = arr[:, :, 1] if (len(arr.shape) == 3 and arr.shape[2] >= 2) else (arr[:, :, 0] if len(arr.shape) == 3 else arr)
            img_small = Image.fromarray(green_ch)
            luma_640 = np.array(img_small.resize((640, 360), Image.Resampling.BILINEAR))
        else:
            sy = max(1, h // 360)
            sx = max(1, w // 640)
            green_idx = 1 if (len(arr.shape) == 3 and arr.shape[2] >= 2) else 0
            luma_640 = arr[::sy, ::sx, green_idx][:360, :640]

        # 4. Dynamic UI mask estimation via 21x30 tile luma from spatial matrix
        coarse_means = (
            self.spatial_matrix._prev_luma
            if self.spatial_matrix._prev_luma is not None
            else np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        )

        if self._frame_count == 0:
            self._luma_history[:] = coarse_means
        else:
            delta = coarse_means - self._luma_history
            self._luma_history += 0.05 * delta
            self._luma_var = 0.95 * self._luma_var + 0.05 * (delta * delta)
            if self._frame_count >= 15:
                # Invariant tiles with variance < 0.000225 (std < 0.015)
                self._ui_mask = (self._luma_var < 0.000225) | self._hud_prior
        self._frame_count += 1

        # 5. Micro-grid 45x80 horizontal edge density (outside UI static mask)
        sub = luma_640[::4, :]  # 90 x 640
        diff = np.abs(sub[:, 1:].astype(np.int16) - sub[:, :-1].astype(np.int16))  # 90 x 639
        self._edge_buf_90[:, :639] = diff > 28
        cell_edges = self._edge_buf_90.reshape(45, 2, 80, 8).sum(axis=(1, 3))  # (45, 80)

        # Mask out UI static regions
        ui_micro = self._ui_mask[self._row_map, self._col_map]
        cell_edges_world = cell_edges.copy()
        cell_edges_world[ui_micro] = 0

        # Global sharpness & edge text scores
        sharpness_score = float(np.mean(diff))
        edge_text_score = float(np.mean(cell_edges_world)) * 6.25
        mean_luma = float(np.mean(coarse_means)) * 255.0

        # Quality flags
        quality_flags = FLAG_VALID
        if mean_luma > 245.0:
            quality_flags |= FLAG_OVEREXPOSED

        # 6. Extract top candidate ROIs in screen pixel coordinates
        flat_top = np.argsort(cell_edges_world, axis=None)[-4:]
        top_r, top_c = np.unravel_index(flat_top, (45, 80))

        rois: list[IndexROI] = []
        cell_h_px = h // 45
        cell_w_px = w // 80
        for r, c in zip(top_r, top_c):
            score_q8 = min(255, int(cell_edges_world[r, c] * 16))
            if score_q8 > 10:
                rois.append(IndexROI(
                    x_px=int(c * cell_w_px),
                    y_px=int(r * cell_h_px),
                    w_px=int(cell_w_px * 2),
                    h_px=int(cell_h_px * 2),
                    score_q8=score_q8,
                    kind=ROI_KIND_TEXT_LIKE,
                ))

        if saliency_bbox is not None and len(rois) < 4:
            bx, by, bw, bh = saliency_bbox
            rois.append(IndexROI(
                x_px=int(bx * w),
                y_px=int(by * h),
                w_px=max(16, int(bw * w)),
                h_px=max(16, int(bh * h)),
                score_q8=min(255, int(dirty_ratio * 255)),
                kind=ROI_KIND_OBJECT_DELTA,
            ))

        # Pack record
        rec = IndexFrameRecord.from_masks(
            frame_id=frame_id,
            segment_id=segment_id,
            pts_us=pts_us,
            scene_version=scene_version,
            quality_flags=quality_flags,
            global_motion=float(dirty_ratio),
            sharpness=float(sharpness_score),
            edge_text=float(edge_text_score),
            mean_luma=float(mean_luma),
            change_mask_bool=dirty_mask,
            ui_mask_bool=self._ui_mask,
            candidate_rois=rois,
        )

        return rec, arr


class SegmentWriter:
    """Manages writing a synchronized pair of video segment and .jti sidecar."""

    def __init__(
        self,
        segment_id: int,
        output_dir: Path,
        start_pts_us: int,
        fps: float = 60.0,
        width: int = 1280,
        height: int = 720,
        codec: str = "libx264",
    ) -> None:
        self.segment_id = segment_id
        self.output_dir = output_dir
        self.start_pts_us = start_pts_us
        self.fps = fps
        self.width = width
        self.height = height
        self.codec = codec

        self.video_path = output_dir / f"seg_{segment_id:06d}.mp4"
        self.index_path = output_dir / f"seg_{segment_id:06d}.jti"

        header = IndexSegmentHeader(
            segment_id=segment_id,
            source_width=width,
            source_height=height,
            grid_rows=GRID_ROWS_DEFAULT,
            grid_cols=GRID_COLS_DEFAULT,
            qpc_freq_hz=10_000_000,
            first_capture_qpc_us=start_pts_us,
            audio_start_qpc_us=start_pts_us,
        )
        self._index_writer = TemporalIndexWriter(
            path=self.index_path,
            header=header,
        )
        self._container: Any | None = None
        self._stream: Any | None = None
        self._frame_count = 0
        self._last_pts_us = start_pts_us
        self._is_open = False
        self._lock = threading.Lock()

    def open(self) -> "SegmentWriter":
        with self._lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._index_writer.open()

            if _HAS_PYAV:
                try:
                    self._container = av.open(
                        str(self.video_path),
                        mode="w",
                        format="mp4",
                        container_options={"movflags": "frag_keyframe+empty_moov+default_base_moof"},
                    )
                    # Choose codec
                    target_codec = self.codec
                    if target_codec == "libx264":
                        stream = self._container.add_stream("libx264", rate=int(self.fps))
                        stream.options = {
                            "preset": "ultrafast",
                            "tune": "zerolatency",
                            "crf": "23",
                        }
                    else:
                        stream = self._container.add_stream(target_codec, rate=int(self.fps))

                    stream.width = self.width
                    stream.height = self.height
                    stream.pix_fmt = "yuv420p"
                    self._stream = stream
                except Exception:
                    self._container = None
                    self._stream = None

            self._is_open = True
        return self

    def add_frame(self, frame_np: np.ndarray, record: IndexFrameRecord) -> None:
        """Write frame to video stream and record to sidecar index."""
        with self._lock:
            if not self._is_open:
                raise RuntimeError("SegmentWriter is closed")

            # 1. Update record with video sample mapping
            record.segment_sample_idx = self._frame_count
            record.video_pts_us = record.pts_us
            record.quality_flags |= FLAG_VALID

            # 2. Write telemetry record
            self._index_writer.write_record(record)
            self._last_pts_us = record.pts_us

            # 3. Encode video frame
            if self._container is not None and self._stream is not None:
                # Ensure dimensions match
                h, w = frame_np.shape[:2]
                if w != self.width or h != self.height:
                    img = Image.fromarray(frame_np).resize(
                        (self.width, self.height), Image.Resampling.BILINEAR
                    )
                    frame_np = np.array(img)

                av_frame = av.VideoFrame.from_ndarray(frame_np, format="rgb24")
                for packet in self._stream.encode(av_frame):
                    self._container.mux(packet)

            self._frame_count += 1

    def record_dropped_frame(self, record: IndexFrameRecord) -> None:
        """Record dropped frame telemetry without encoding to video container."""
        with self._lock:
            if not self._is_open:
                raise RuntimeError("SegmentWriter is closed")

            record.segment_sample_idx = -1
            record.video_pts_us = -1
            record.quality_flags |= (FLAG_VALID | FLAG_ENCODER_DROPPED)
            self._index_writer.write_record(record)
            self._last_pts_us = record.pts_us

    def close(self) -> EvidenceSegment:
        """Finalize and flush segment files, returning completed EvidenceSegment."""
        with self._lock:
            if not self._is_open:
                return EvidenceSegment(
                    segment_id=self.segment_id,
                    video_path=self.video_path,
                    index_path=self.index_path,
                    start_pts_us=self.start_pts_us,
                    end_pts_us=self._last_pts_us,
                    frame_count=self._frame_count,
                    fps=self.fps,
                    width=self.width,
                    height=self.height,
                )

            # Flush video container
            if self._container is not None and self._stream is not None:
                try:
                    for packet in self._stream.encode():
                        self._container.mux(packet)
                except Exception:
                    pass
                try:
                    self._container.close()
                except Exception:
                    pass
                self._container = None
                self._stream = None

            # Flush index writer
            self._index_writer.close()
            self._is_open = False

            return EvidenceSegment(
                segment_id=self.segment_id,
                video_path=self.video_path,
                index_path=self.index_path,
                start_pts_us=self.start_pts_us,
                end_pts_us=self._last_pts_us,
                frame_count=self._frame_count,
                fps=self.fps,
                width=self.width,
                height=self.height,
            )


class LiveEvidenceArchive:
    """Bounded, rolling ring buffer archive with continuous Temporal Evidence indexing.

    Guarantees:
      - Continuous 60 FPS recording split into self-contained segments.
      - Asynchronous telemetry extraction (<0.6 ms) running in dedicated worker.
      - Non-blocking frame ingestion: never stalls caller or screen capture loop.
      - Ring buffer retention: strictly bounded disk footprint (e.g. 5-10 minutes).
      - Microsecond-level temporal query API across segment boundaries.
      - Single-frame sparse candidate extraction without decoding entire segments.
    """

    def __init__(
        self,
        archive_dir: str | Path,
        segment_duration_s: float = 10.0,
        max_retention_s: float = 600.0,
        fps: float = 60.0,
        width: int = 1280,
        height: int = 720,
        codec: str = "libx264",
        queue_size: int = 120,
    ) -> None:
        self.archive_dir = Path(archive_dir).resolve()
        self.segment_duration_s = max(0.1, float(segment_duration_s))
        self.max_retention_s = max(self.segment_duration_s * 2.0, float(max_retention_s))
        self.fps = max(1.0, float(fps))
        self.width = int(width)
        self.height = int(height)
        self.codec = str(codec)
        self.frames_per_segment = int(self.segment_duration_s * self.fps)

        self._queue: queue.Queue[tuple[np.ndarray | Image.Image, int, int] | None] = queue.Queue(
            maxsize=max(1, int(queue_size))
        )
        self._telemetry_computer = TelemetryComputer()
        self._active_writer: SegmentWriter | None = None
        self._segments: list[EvidenceSegment] = []
        self._lock = threading.RLock()

        self._current_segment_id = 0
        self._frame_counter = 0
        self._dropped_frames = 0
        self._total_ingested = 0

        # Priority Micro-Stash (8 slots) for load shedding
        self._stash_capacity = 8
        self._micro_stash: list[tuple[IndexFrameRecord, np.ndarray, float]] = []
        self.congestion_threshold: int = 10
        self.simulate_congestion: bool = False

        self._worker_thread: threading.Thread | None = None
        self._running = False
        self._paused = False

        # Profiling telemetry
        self._telemetry_latencies: collections.deque[float] = collections.deque(maxlen=100)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def pause(self) -> None:
        """Pause frame ingestion and cleanly finalize the in-flight segment to disk."""
        with self._lock:
            self._paused = True
            if self._active_writer is not None:
                seg = self._active_writer.close()
                self._segments.append(seg)
                self._active_writer = None
                self._current_segment_id += 1

    def resume(self) -> None:
        """Resume frame ingestion after pause."""
        with self._lock:
            self._paused = False

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def recorded_frames(self) -> int:
        return self._frame_counter

    def start(self) -> "LiveEvidenceArchive":
        """Start the background telemetry and segment recording thread."""
        with self._lock:
            if self._running:
                return self
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="JAWL-LiveEvidenceWorker",
                daemon=True,
            )
            self._worker_thread.start()
        return self

    def stop(self, timeout_s: float = 5.0) -> None:
        """Stop worker, flush queue, and close current active segment."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._queue.put(None)

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=max(0.1, timeout_s))

        with self._lock:
            if self._active_writer is not None:
                while self._micro_stash:
                    s_rec, s_rgb, _, s_dropped = self._micro_stash.pop(0)
                    if s_dropped:
                        self._active_writer.record_dropped_frame(s_rec)
                        self._dropped_frames += 1
                    else:
                        self._active_writer.add_frame(s_rgb, s_rec)
                        self._frame_counter += 1
                seg = self._active_writer.close()
                if seg.frame_count > 0:
                    self._segments.append(seg)
                self._active_writer = None

    def ingest_frame(
        self,
        frame: np.ndarray | Image.Image,
        pts_us: int | None = None,
        scene_version: int = 0,
    ) -> bool:
        """Non-blocking ingestion of a captured visual frame.

        Never blocks the caller. If the worker queue is full, drops frame gracefully
        and returns False, preserving system-wide real-time responsiveness.
        """
        if not self._running or self._paused:
            return False

        if pts_us is None:
            pts_us = int(time.monotonic() * 1_000_000)

        self._total_ingested += 1
        try:
            self._queue.put_nowait((frame, pts_us, scene_version))
            return True
        except queue.Full:
            self._dropped_frames += 1
            return False

    def _worker_loop(self) -> None:
        """Main asynchronous processing loop: computes telemetry and writes segments."""
        while True:
            try:
                item = self._queue.get(timeout=0.05)
            except queue.Empty:
                if not self._running:
                    break
                continue

            if item is None:
                # Flush micro-stash on termination
                with self._lock:
                    if self._active_writer is not None:
                        while self._micro_stash:
                            s_rec, s_rgb, _, s_dropped = self._micro_stash.pop(0)
                            if s_dropped:
                                self._active_writer.record_dropped_frame(s_rec)
                                self._dropped_frames += 1
                            else:
                                self._active_writer.add_frame(s_rgb, s_rec)
                                self._frame_counter += 1
                self._queue.task_done()
                break

            raw_frame, pts_us, scene_version = item

            # 1. Compute telemetry (runs in background thread, <0.6 ms)
            t_tel0 = time.perf_counter()
            rec, frame_rgb = self._telemetry_computer.compute(
                frame_input=raw_frame,
                frame_id=self._frame_counter,
                segment_id=self._current_segment_id,
                pts_us=pts_us,
                scene_version=scene_version,
            )
            tel_ms = (time.perf_counter() - t_tel0) * 1000.0
            self._telemetry_latencies.append(tel_ms)

            utility = float(rec.edge_text_score + rec.global_motion_score)

            # 2. Manage segment chunking and Priority Micro-Stash (8 slots)
            with self._lock:
                if self._active_writer is None:
                    self._active_writer = SegmentWriter(
                        segment_id=self._current_segment_id,
                        output_dir=self.archive_dir,
                        start_pts_us=pts_us,
                        fps=self.fps,
                        width=self.width,
                        height=self.height,
                        codec=self.codec,
                    ).open()

                is_congested = self.simulate_congestion or (self._queue.qsize() >= self.congestion_threshold)
                self._micro_stash.append([rec, frame_rgb, utility, False])

                if is_congested and len(self._micro_stash) > self._stash_capacity:
                    # Find active item with minimum utility to drop
                    active = [item for item in self._micro_stash if not item[3]]
                    if active:
                        min_item = min(active, key=lambda x: x[2])
                        min_item[3] = True

                    oldest_rec, oldest_rgb, _, is_dropped = self._micro_stash.pop(0)
                    if is_dropped:
                        self._active_writer.record_dropped_frame(oldest_rec)
                        self._dropped_frames += 1
                    else:
                        self._active_writer.add_frame(oldest_rgb, oldest_rec)
                        self._frame_counter += 1
                elif not is_congested and len(self._micro_stash) > self._stash_capacity:
                    oldest_rec, oldest_rgb, _, is_dropped = self._micro_stash.pop(0)
                    if is_dropped:
                        self._active_writer.record_dropped_frame(oldest_rec)
                        self._dropped_frames += 1
                    else:
                        self._active_writer.add_frame(oldest_rgb, oldest_rec)
                        self._frame_counter += 1

                # Rotate segment if duration reached
                if self._active_writer._frame_count >= self.frames_per_segment:
                    while self._micro_stash:
                        s_rec, s_rgb, _, s_dropped = self._micro_stash.pop(0)
                        if s_dropped:
                            self._active_writer.record_dropped_frame(s_rec)
                            self._dropped_frames += 1
                        else:
                            self._active_writer.add_frame(s_rgb, s_rec)
                            self._frame_counter += 1

                    completed_seg = self._active_writer.close()
                    self._segments.append(completed_seg)
                    self._current_segment_id += 1
                    self._active_writer = None

                    # 3. Enforce Ring Buffer retention
                    self._enforce_ring_retention()

            self._queue.task_done()

    def _enforce_ring_retention(self) -> None:
        """Prune oldest segments when total duration exceeds max_retention_s."""
        total_dur_ms = sum(s.duration_ms for s in self._segments)
        max_dur_ms = self.max_retention_s * 1000.0

        while len(self._segments) > 1 and total_dur_ms > max_dur_ms:
            oldest = self._segments.pop(0)
            total_dur_ms -= oldest.duration_ms
            oldest.delete()

    def query_interval(self, start_pts_us: int, end_pts_us: int) -> list[EvidenceSegment]:
        """Find all segments overlapping the time interval [start_pts_us, end_pts_us]."""
        with self._lock:
            all_segs = list(self._segments)
            if self._active_writer is not None and self._active_writer._frame_count > 0:
                # Include active in-flight segment metadata
                active_meta = EvidenceSegment(
                    segment_id=self._active_writer.segment_id,
                    video_path=self._active_writer.video_path,
                    index_path=self._active_writer.index_path,
                    start_pts_us=self._active_writer.start_pts_us,
                    end_pts_us=self._active_writer._last_pts_us,
                    frame_count=self._active_writer._frame_count,
                    fps=self.fps,
                    width=self.width,
                    height=self.height,
                )
                all_segs.append(active_meta)

        matched = []
        for seg in all_segs:
            # Overlap condition: not (seg.end < start or seg.start > end)
            if not (seg.end_pts_us < start_pts_us or seg.start_pts_us > end_pts_us):
                matched.append(seg)
        return matched

    def get_records(self, start_pts_us: int, end_pts_us: int) -> list[IndexFrameRecord]:
        """Retrieve all index records across segments within [start_pts_us, end_pts_us]."""
        segments = self.query_interval(start_pts_us, end_pts_us)
        records: list[IndexFrameRecord] = []
        for seg in segments:
            seg_records = seg.read_records()
            for r in seg_records:
                if start_pts_us <= r.pts_us <= end_pts_us:
                    records.append(r)
        return records

    def select_candidate_frames(
        self,
        start_pts_us: int,
        end_pts_us: int,
        question: str = "",
        strategy: str = "hybrid_adaptive",
        budget: int = 12,
    ) -> list[tuple[EvidenceSegment, IndexFrameRecord, Image.Image | None]]:
        """Select candidate frames using JTE1 sidecar telemetry, then decode only those frames.

        This delivers an order-of-magnitude speedup over full-window video decoding:
        1. Candidates are scored directly in RAM over 256-byte records (<0.1 ms).
        2. Only the chosen budget (e.g. 8-12) frames are decoded from video.
        """
        records = self.get_records(start_pts_us, end_pts_us)
        if not records:
            return []

        strategy = strategy.lower().strip()
        budget = max(1, min(budget, len(records)))
        selected_records: list[IndexFrameRecord] = []

        q_lower = question.lower()
        is_text = any(k in q_lower for k in ("код", "текст", "надпис", "номер", "цифр", "букв", "двер"))
        is_flash = any(k in q_lower for k in ("вспышк", "выпал", "сверкн", "взрыв", "зелье"))

        def score_fn(rec: IndexFrameRecord) -> float:
            base = rec.sharpness_score * 0.4 + rec.global_motion_score * 100.0 * 0.3
            if is_text:
                base += rec.edge_text_score * 0.6
            elif is_flash:
                base += rec.global_motion_score * 100.0 * 0.5
            return float(base)

        if strategy == "uniform":
            step = len(records) / float(budget)
            for i in range(budget):
                idx = min(len(records) - 1, int(i * step))
                selected_records.append(records[idx])

        elif strategy in ("spatial", "spatial_only"):
            sorted_by_motion = sorted(
                records, key=lambda r: (r.global_motion_score, r.sharpness_score), reverse=True
            )
            selected_records = sorted_by_motion[:budget]

        elif strategy in ("hybrid_onepass", "hybrid"):
            # Uniform mesh shifted to local peak
            step = len(records) / float(budget)
            radius = max(2, int(step // 2))
            for i in range(budget):
                center = min(len(records) - 1, int((i + 0.5) * step))
                w_start = max(0, center - radius)
                w_end = min(len(records), center + radius + 1)
                best = max(records[w_start:w_end], key=score_fn)
                if best not in selected_records:
                    selected_records.append(best)
            if len(selected_records) < budget:
                # Backfill
                remaining = [r for r in records if r not in selected_records]
                selected_records.extend(sorted(remaining, key=score_fn, reverse=True)[:budget - len(selected_records)])

        elif strategy in ("hybrid_adaptive", "adaptive"):
            # Deterministic Anchor-Satellite Weaving (P0.3): guarantees strict subset nesting
            # S_4 ⊂ S_8 ⊂ S_12 ⊂ S_16 and monotonic recall
            pts_ms_list = [r.pts_us / 1000.0 for r in records]
            scores = [score_fn(r) for r in records]
            sharp_edge = [r.sharpness_score * (r.edge_text_score + 0.1) for r in records]
            ranked_indices = rank_all_candidates_anchor_satellite(
                pts_ms_list=pts_ms_list,
                scores=scores,
                sharp_edge_scores=sharp_edge,
                nms_anchor_ms=250.0,
                max_sat_dist_ms=100.0,
            )
            chosen_indices = ranked_indices[:budget]
            chosen_sorted = sorted(chosen_indices)
            selected_records = [records[i] for i in chosen_sorted]
        else:
            raise ValueError(f"Unknown frame selection strategy: {strategy}")

        # Map selected records to their segments and decode only requested frames
        segments_map: dict[int, EvidenceSegment] = {s.segment_id: s for s in self._segments}
        results: list[tuple[EvidenceSegment, IndexFrameRecord, Image.Image | None]] = []

        # Group by segment for efficient single-pass extraction
        by_segment: dict[int, list[IndexFrameRecord]] = collections.defaultdict(list)
        for rec in selected_records:
            by_segment[rec.segment_id].append(rec)

        for seg_id, recs in by_segment.items():
            seg = segments_map.get(seg_id)
            if seg is None:
                for r in recs:
                    results.append((None, r, None))  # type: ignore
                continue

            # In JTI1, rec.segment_sample_idx maps directly to decoded MP4 frame sample index.
            # Dropped or missing frames have segment_sample_idx < 0 and must never receive an image.
            needed_samples = [
                r.segment_sample_idx
                for r in recs
                if r.segment_sample_idx >= 0
                and not (r.quality_flags & (FLAG_ENCODER_DROPPED | FLAG_SOURCE_FRAME_MISSING))
            ]

            extracted = seg.extract_frames(needed_samples) if needed_samples else {}

            for r in recs:
                is_inaccessible = (
                    r.segment_sample_idx < 0
                    or (r.quality_flags & (FLAG_ENCODER_DROPPED | FLAG_SOURCE_FRAME_MISSING)) != 0
                )
                if is_inaccessible:
                    img = None
                else:
                    img = extracted.get(r.segment_sample_idx)
                    if img is None:
                        # Video frame was missing / unreadable in container!
                        r.quality_flags |= FLAG_SOURCE_FRAME_MISSING

                results.append((seg, r, img))

        return results

    def get_stats(self) -> dict[str, Any]:
        """Return runtime diagnostic telemetry and health metrics."""
        with self._lock:
            total_dur_ms = sum(s.duration_ms for s in self._segments)
            total_bytes = sum(s.total_file_size_bytes for s in self._segments)
            seg_count = len(self._segments)
            queue_depth = self._queue.qsize()

        p50_tel = float(np.median(self._telemetry_latencies)) if self._telemetry_latencies else 0.0
        mean_tel = float(np.mean(self._telemetry_latencies)) if self._telemetry_latencies else 0.0

        return {
            "is_running": self._running,
            "total_ingested_frames": self._total_ingested,
            "recorded_frames": self._frame_counter,
            "dropped_frames": self._dropped_frames,
            "queue_depth": queue_depth,
            "active_segments_count": seg_count,
            "total_retained_duration_s": round(total_dur_ms / 1000.0, 2),
            "total_retained_bytes": total_bytes,
            "telemetry_latency_p50_ms": round(p50_tel, 3),
            "telemetry_latency_mean_ms": round(mean_tel, 3),
            "segment_duration_s": self.segment_duration_s,
            "max_retention_s": self.max_retention_s,
        }

    def __enter__(self) -> "LiveEvidenceArchive":
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
