"""Retrospective Frame Selector for JAWL (Round 11, Step 1).

Implements the multi-level retrospective perception contract:
  Level A: Temporal Window Triangulation (context anchors -> window)
  Level B: Retrospective Frame Selection (video -> K candidate frames/ROIs)
  Level C: Recognition Hand-Off (candidate frames -> OCR / VLM)

Strategies implemented for Level B:
  A — Uniform: Equidistant time mesh across search window
  B — Spatial: Pure Spatial Matrix (21x30) delta/dirty-tile extrema
  C — Hybrid One-Pass: Uniform grid + local time-window shift to peak
      world-sharpness/edge-density outside soft UI/HUD mask
  D — Hybrid Adaptive: Two-pass (K/2 coarse sweep -> candidate detection ->
      temporal refinement / foveated burst of remaining K/2 budget)
  Oracle: Theoretical upper bound picking the most legible frame from GT

Zero third-party desktop content is recorded. Runs fast on CPU with PyAV
(fallback to ffmpeg pipe if av is unavailable).
"""

from __future__ import annotations

import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

try:
    import av  # type: ignore
    _HAS_PYAV = True
except ImportError:
    _HAS_PYAV = False

from .visual_stream import IncrementalSpatialMatrix


@dataclass
class FrameCandidate:
    """A single candidate frame selected for downstream inspection."""
    frame_index: int
    pts_ms: float
    score: float
    roi: list[int] | None = None  # [x, y, w, h] in pixels
    features: dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    is_keyframe: bool = False


@dataclass
class FrameSelectionResult:
    """Outcome of retrospective frame selection."""
    strategy: str
    budget: int
    search_window_ms: tuple[float, float]
    selected_frames: list[FrameCandidate]
    target_status: str  # "observed_present" | "not_found_in_sample"
    detail_status: str  # "observed_readable" | "observed_unreadable" | "unknown"
    coverage_status: str  # "complete" | "partial" | "sparse"
    decode_ms: float
    scoring_ms: float
    total_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def frame_indices(self) -> list[int]:
        return [f.frame_index for f in self.selected_frames]

    def pts_list_ms(self) -> list[float]:
        return [f.pts_ms for f in self.selected_frames]


def rank_all_candidates_anchor_satellite(
    pts_ms_list: Sequence[float],
    scores: Sequence[float],
    sharp_edge_scores: Sequence[float],
    nms_anchor_ms: float = 250.0,
    max_sat_dist_ms: float = 100.0,
) -> list[int]:
    """Deterministically rank all candidate indices using Anchor-Satellite Weaving.

    Invariants:
      1. Monotonic nesting: ordered_indices[:K1] is a strict subset of ordered_indices[:K2]
         for any K1 < K2 (S_4 ⊂ S_8 ⊂ S_12 ⊂ S_16).
      2. Wide coverage: Anchors cover distinct information peaks across the window (NMS >= 250ms).
      3. Dense burst: Satellites around top peaks capture short (100-150ms) text/damage transitions.
    """
    n = len(pts_ms_list)
    if n == 0:
        return []

    # 1. Rank candidate indices by primary score
    ranked_by_score = sorted(range(n), key=lambda i: scores[i], reverse=True)

    # 2. Extract independent anchors with NMS
    anchors: list[int] = []
    for idx in ranked_by_score:
        pts = pts_ms_list[idx]
        if not any(abs(pts - pts_ms_list[a]) < nms_anchor_ms for a in anchors):
            anchors.append(idx)

    # Fill large temporal gaps (> 600ms) with equidistant anchors to ensure baseline coverage
    sorted_anchors = sorted(anchors, key=lambda a: pts_ms_list[a])
    extra_anchors: list[int] = []
    for j in range(len(sorted_anchors) - 1):
        gap = pts_ms_list[sorted_anchors[j + 1]] - pts_ms_list[sorted_anchors[j]]
        if gap > 600.0:
            mid_pts = (pts_ms_list[sorted_anchors[j]] + pts_ms_list[sorted_anchors[j + 1]]) / 2.0
            best_mid = min(range(n), key=lambda i: abs(pts_ms_list[i] - mid_pts))
            if best_mid not in anchors and best_mid not in extra_anchors:
                extra_anchors.append(best_mid)
    anchors.extend(extra_anchors)

    # 3. Satellites for each anchor: nearest sharpest frames within ±100ms
    satellites: dict[int, list[int]] = {}
    for a_idx in anchors:
        a_pts = pts_ms_list[a_idx]
        # Pool frames within 15ms .. max_sat_dist_ms
        pool = [
            i for i in range(n)
            if i != a_idx and 15.0 <= abs(pts_ms_list[i] - a_pts) <= max_sat_dist_ms
        ]
        pool.sort(key=lambda i: sharp_edge_scores[i], reverse=True)
        satellites[a_idx] = pool

    # 4. Weave anchors and satellites into a single deterministic ordered list
    ordered: list[int] = []
    seen: set[int] = set()

    def add(idx: int) -> bool:
        if idx is not None and idx not in seen and 0 <= idx < n:
            ordered.append(idx)
            seen.add(idx)
            return True
        return False

    # Standard schedule for positions 1..16
    schedule = [
        ('a', 0), ('a', 1), ('a', 2), ('a', 3),        # Top 4 independent anchors
        ('s', 0, 0), ('s', 1, 0),                       # Best sharp satellites of top 2 anchors
        ('a', 4), ('s', 0, 1),                          # Anchor 5 + second satellite of top peak
        ('a', 5), ('s', 2, 0), ('a', 6), ('s', 1, 1),  # Anchors 6, 7 + satellites
        ('a', 7), ('s', 3, 0), ('a', 8), ('s', 2, 1),  # Anchors 8, 9 + satellites -> K=16
    ]

    for item in schedule:
        if item[0] == 'a':
            a_idx_pos = item[1]
            if a_idx_pos < len(anchors):
                add(anchors[a_idx_pos])
        elif item[0] == 's':
            a_idx_pos, sat_pos = item[1], item[2]
            if a_idx_pos < len(anchors):
                a_id = anchors[a_idx_pos]
                sats = satellites.get(a_id, [])
                if sat_pos < len(sats):
                    add(sats[sat_pos])

    # Fallback / overflow: remaining anchors, then remaining satellites, then remaining ranked
    for a in anchors:
        add(a)
    for a in anchors:
        for s in satellites.get(a, []):
            add(s)
    for idx in ranked_by_score:
        add(idx)

    return ordered


class VideoWindowDecoder:
    """Efficient frame extraction for a bounded temporal window [start_ms, end_ms]."""

    def __init__(self, video_path: str | Path, target_fps: float = 60.0) -> None:
        self.video_path = Path(video_path).resolve()
        self.target_fps = float(target_fps)
        if not self.video_path.is_file():
            raise FileNotFoundError(f"Video file not found: {self.video_path}")

    def decode_window(
        self, start_ms: float, end_ms: float, stride: int = 1
    ) -> list[tuple[int, float, np.ndarray]]:
        """Decode frames in [start_ms, end_ms].

        Returns list of (frame_index, pts_ms, rgb_np_uint8).
        """
        if _HAS_PYAV:
            return self._decode_pyav(start_ms, end_ms, stride)
        return self._decode_ffmpeg(start_ms, end_ms, stride)

    def _decode_pyav(
        self, start_ms: float, end_ms: float, stride: int
    ) -> list[tuple[int, float, np.ndarray]]:
        frames: list[tuple[int, float, np.ndarray]] = []
        container = av.open(str(self.video_path))
        stream = container.streams.video[0]
        stream.codec_context.thread_type = "AUTO"

        time_base = float(stream.time_base)
        fps = float(stream.average_rate) if stream.average_rate else self.target_fps

        start_sec = max(0.0, (start_ms - 200.0) / 1000.0)
        target_pts = int(start_sec / time_base) if time_base > 0 else 0
        container.seek(target_pts, stream=stream, backward=True)

        count = 0
        for frame in container.decode(stream):
            pts_ms = float(frame.pts * time_base * 1000.0)
            if pts_ms < start_ms - 10.0:
                continue
            if pts_ms > end_ms + 10.0:
                break
            count += 1
            if stride > 1 and (count % stride != 0):
                continue

            frame_idx = int(round(pts_ms / 1000.0 * fps))
            rgb = frame.to_ndarray(format="rgb24")
            frames.append((frame_idx, pts_ms, rgb))

        container.close()
        return frames

    def _decode_ffmpeg(
        self, start_ms: float, end_ms: float, stride: int
    ) -> list[tuple[int, float, np.ndarray]]:
        # Fallback via ffmpeg pipe
        start_sec = max(0.0, start_ms / 1000.0)
        dur_sec = max(0.1, (end_ms - start_ms) / 1000.0)
        cmd = [
            "ffmpeg", "-ss", f"{start_sec:.3f}", "-t", f"{dur_sec:.3f}",
            "-i", str(self.video_path),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-vsync", "0", "-",
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        assert proc.stdout is not None

        # Read dimensions
        w, h = 1280, 720
        frame_bytes = w * h * 3
        frames: list[tuple[int, float, np.ndarray]] = []
        fi = int(round(start_sec * self.target_fps))

        step_ms = 1000.0 / self.target_fps
        cur_pts = start_ms
        c = 0
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if len(chunk) < frame_bytes:
                break
            c += 1
            if stride == 1 or (c % stride == 0):
                arr = np.frombuffer(chunk, dtype=np.uint8).reshape((h, w, 3))
                frames.append((fi, cur_pts, arr))
            fi += 1
            cur_pts += step_ms

        proc.stdout.close()
        proc.wait()
        return frames


class RetrospectiveFrameSelector:
    """Evaluates and selects candidate frames from a temporal search window."""

    def __init__(self, grid_shape: tuple[int, int] = (21, 30)) -> None:
        self.grid_h, self.grid_w = grid_shape
        self.spatial_matrix = IncrementalSpatialMatrix(grid_shape=grid_shape)

    def select_frames(
        self,
        video_path: str | Path,
        start_ms: float,
        end_ms: float,
        question: str,
        strategy: str = "hybrid_adaptive",
        budget_frames: int = 12,
        oracle_gt: dict[str, Any] | None = None,
        pre_decoded_frames: list[tuple[int, float, np.ndarray]] | None = None,
    ) -> FrameSelectionResult:
        """Select up to budget_frames candidates in [start_ms, end_ms].

        Args:
            video_path: Path to raw/encoded video file.
            start_ms: Start of temporal window in ms.
            end_ms: End of temporal window in ms.
            question: User inquiry driving intent routing (e.g. text vs object).
            strategy: "uniform", "spatial", "hybrid_onepass", "hybrid_adaptive", "oracle".
            budget_frames: Strict limit on selected frames (e.g. 8 or 12).
            oracle_gt: Ground truth dict for oracle baseline only.
            pre_decoded_frames: Optional cached list of (frame_idx, pts_ms, frame_rgb).
        """
        t0 = time.perf_counter()
        strategy = strategy.lower().strip()
        budget = max(1, int(budget_frames))

        if strategy == "oracle":
            return self._select_oracle(
                video_path, start_ms, end_ms, budget, oracle_gt, t0
            )

        if pre_decoded_frames is not None:
            raw_frames = pre_decoded_frames
            decode_ms = 0.0
        else:
            decoder = VideoWindowDecoder(video_path)
            t_dec0 = time.perf_counter()
            # Full decode of the search window
            raw_frames = decoder.decode_window(start_ms, end_ms, stride=1)
            decode_ms = (time.perf_counter() - t_dec0) * 1000.0

        if not raw_frames:
            t_total = (time.perf_counter() - t0) * 1000.0
            return FrameSelectionResult(
                strategy=strategy,
                budget=budget,
                search_window_ms=(start_ms, end_ms),
                selected_frames=[],
                target_status="not_found_in_sample",
                detail_status="unknown",
                coverage_status="sparse",
                decode_ms=decode_ms,
                scoring_ms=0.0,
                total_ms=t_total,
                metadata={"error": "no_frames_decoded"},
            )

        t_score0 = time.perf_counter()

        # Parse question intent
        q_lower = question.lower()
        is_text_intent = any(k in q_lower for k in ("код", "текст", "надпис", "номер", "цифр", "букв", "двер"))
        is_flash_intent = any(k in q_lower for k in ("вспышк", "выпал", "сверкн", "взрыв", "зелье"))
        is_ui_target = any(k in q_lower for k in ("уведомлен", "интерфейс", "чат", "сообщен", "система"))

        if strategy == "uniform":
            candidates, meta = self._strategy_uniform(raw_frames, budget)
        elif strategy in ("spatial", "spatial_only"):
            candidates, meta = self._strategy_spatial_only(raw_frames, budget)
        elif strategy in ("hybrid", "hybrid_onepass"):
            candidates, meta = self._strategy_hybrid_onepass(
                raw_frames, budget, is_text_intent, is_flash_intent, is_ui_target
            )
        elif strategy in ("old_hybrid_adaptive", "hybrid_adaptive_v1"):
            candidates, meta = self._strategy_old_hybrid_adaptive(
                raw_frames, budget, is_text_intent, is_flash_intent, is_ui_target
            )
        elif strategy in ("weaving_scalar", "scalar_weaving"):
            candidates, meta = self._strategy_hybrid_adaptive(
                raw_frames, budget, is_text_intent, is_flash_intent, is_ui_target, roi_boost=False
            )
        elif strategy in ("adaptive", "hybrid_adaptive", "weaving_roi_boosted", "weaving_roi"):
            candidates, meta = self._strategy_hybrid_adaptive(
                raw_frames, budget, is_text_intent, is_flash_intent, is_ui_target, roi_boost=True
            )
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        scoring_ms = (time.perf_counter() - t_score0) * 1000.0
        total_ms = (time.perf_counter() - t0) * 1000.0

        # Assess epistemic detail status
        target_status = "observed_present" if candidates else "not_found_in_sample"
        # Check readability across chosen candidates
        detail_status = "unknown"
        if candidates:
            max_sharpness = max(c.features.get("world_sharpness", 0.0) for c in candidates)
            # High motion blur flag: if maximum sharpness is below threshold
            if max_sharpness < 25.0 and is_text_intent:
                detail_status = "observed_unreadable"
            else:
                detail_status = "observed_readable"

        coverage_status = "complete" if len(candidates) >= budget else "partial"

        return FrameSelectionResult(
            strategy=strategy,
            budget=budget,
            search_window_ms=(start_ms, end_ms),
            selected_frames=candidates,
            target_status=target_status,
            detail_status=detail_status,
            coverage_status=coverage_status,
            decode_ms=decode_ms,
            scoring_ms=scoring_ms,
            total_ms=total_ms,
            metadata=meta,
        )

    # -------------------------------------------------------------------------
    # UI / HUD Mask & Feature Extraction
    # -------------------------------------------------------------------------

    def _estimate_ui_likelihood_map(
        self, frames: list[tuple[int, float, np.ndarray]]
    ) -> np.ndarray:
        """Compute spatial UI likelihood map (grid_h, grid_w) in [0.0, 1.0].

        Tiles that remain static while the surrounding world moves are assigned
        high ui_likelihood. This prevents motion-blurred frames from getting
        selected merely because the HUD ammo counter / HP bar is razor sharp.
        """
        gh, gw = self.grid_h, self.grid_w
        if len(frames) < 4:
            # Fallback to static spatial heuristic: top and bottom borders have higher prior
            prior = np.zeros((gh, gw), dtype=np.float32)
            prior[0, :] = 0.5
            prior[-1, :] = 0.5
            return prior

        # Subsample up to 24 frames for fast variance estimation
        stride = max(1, len(frames) // 24)
        sample = [f[2] for f in frames[::stride][:24]]

        # Downsample each to (gh, gw) grayscale
        tile_lumas = []
        for img in sample:
            # integer luminance: (R + 2G + B) >> 2
            lum = (
                (img[:, :, 0].astype(np.uint16) +
                 (img[:, :, 1].astype(np.uint16) << 1) +
                 img[:, :, 2].astype(np.uint16)) >> 2
            ).astype(np.float32)
            # block average
            th, tw = lum.shape[0] // gh, lum.shape[1] // gw
            lum_trimmed = lum[:gh * th, :gw * tw]
            b_means = lum_trimmed.reshape(gh, th, gw, tw).mean(axis=(1, 3))
            tile_lumas.append(b_means)

        stack = np.stack(tile_lumas, axis=0)  # (N, gh, gw)
        temporal_var = stack.var(axis=0)      # (gh, gw)
        mean_var = float(temporal_var.mean()) + 1e-5

        # Invert variance relative to scene motion: very low variance relative to mean -> UI
        ui_score = np.exp(-temporal_var / (mean_var * 0.45 + 1e-4))
        # Clip and normalize
        ui_score = np.clip(ui_score, 0.0, 1.0)
        return ui_score.astype(np.float32)

    def _compute_frame_features(
        self,
        img: np.ndarray,
        ui_mask: np.ndarray,
        is_ui_target: bool = False,
    ) -> tuple[float, float, float, list[int] | None]:
        """Extract sharpness, edge density, and contrast outside (or inside) UI.

        Returns: (world_sharpness, world_edges, contrast, candidate_roi_px)
        """
        gh, gw = self.grid_h, self.grid_w
        h, w = img.shape[:2]
        th, tw = h // gh, w // gw

        # Fast luma
        luma = (
            (img[:, :, 0].astype(np.uint16) +
             (img[:, :, 1].astype(np.uint16) << 1) +
             img[:, :, 2].astype(np.uint16)) >> 2
        ).astype(np.float32)

        # Gradients (approximation to Sobel/Laplacian)
        gx = np.abs(luma[:, 2:] - luma[:, :-2])
        gy = np.abs(luma[2:, :] - luma[:-2, :])
        # Pad to match original shape
        grad = np.zeros_like(luma)
        grad[1:-1, 1:-1] = (gx[1:-1, :] + gy[:, 1:-1]) * 0.5

        # Block pooling
        grad_trimmed = grad[:gh * th, :gw * tw]
        tile_grad = grad_trimmed.reshape(gh, th, gw, tw).mean(axis=(1, 3))

        # Weight by UI mask
        if is_ui_target:
            weights = ui_mask
        else:
            weights = 1.0 - ui_mask * 0.85  # soft suppression of HUD

        weighted_grad = tile_grad * weights

        # World sharpness: variance of gradient across world tiles
        world_sharpness = float(weighted_grad.var())
        world_edges = float(weighted_grad.mean())

        # Candidate ROI: tile with highest weighted gradient
        best_pos = np.unravel_index(np.argmax(weighted_grad), weighted_grad.shape)
        by, bx = int(best_pos[0]), int(best_pos[1])
        roi_px = [bx * tw, by * th, tw * 2, th * 2]

        contrast = float(tile_grad.max() - tile_grad.min())
        roi_peak = float(weighted_grad[by, bx])
        roi_saliency = roi_peak / (world_edges + 1e-4)
        return world_sharpness, world_edges, contrast, roi_px, roi_saliency

    # -------------------------------------------------------------------------
    # Strategy A: Uniform
    # -------------------------------------------------------------------------

    def _strategy_uniform(
        self, frames: list[tuple[int, float, np.ndarray]], budget: int
    ) -> tuple[list[FrameCandidate], dict[str, Any]]:
        n = len(frames)
        if budget >= n:
            indices = list(range(n))
        else:
            # Equidistant sampling
            step = n / float(budget)
            indices = [min(n - 1, int((i + 0.5) * step)) for i in range(budget)]
            indices = sorted(list(dict.fromkeys(indices)))

        candidates = [
            FrameCandidate(
                frame_index=frames[idx][0],
                pts_ms=frames[idx][1],
                score=1.0,
                features={"sample_index": float(idx)},
                rationale="uniform_grid",
            )
            for idx in indices
        ]
        return candidates, {"strategy": "uniform", "sampled_count": len(candidates)}

    # -------------------------------------------------------------------------
    # Strategy B: Spatial-Only
    # -------------------------------------------------------------------------

    def _strategy_spatial_only(
        self, frames: list[tuple[int, float, np.ndarray]], budget: int
    ) -> tuple[list[FrameCandidate], dict[str, Any]]:
        """Select frames using pure IncrementalSpatialMatrix dirty tile peaks."""
        matrix = IncrementalSpatialMatrix(grid_shape=(self.grid_h, self.grid_w))
        deltas = []

        for fi, pts, arr in frames:
            _, dirty_count, bbox = matrix.update(arr, commit=True)
            deltas.append((dirty_count, bbox))

        # Score by dirty tile count + rate of change
        scored: list[tuple[float, int, tuple[int, float, np.ndarray], list[float] | None]] = []
        for i in range(len(frames)):
            d_curr = deltas[i][0]
            d_prev = deltas[i - 1][0] if i > 0 else d_curr
            delta_diff = abs(d_curr - d_prev)
            # High dirty tiles = large scene motion/change
            score = float(d_curr * 0.7 + delta_diff * 0.3)
            scored.append((score, i, frames[i], deltas[i][1]))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)

        # Temporal Non-Maximum Suppression (min 150ms distance)
        min_dist_ms = 150.0
        selected: list[FrameCandidate] = []
        for score, idx, f_data, s_bbox in scored:
            if len(selected) >= budget:
                break
            pts = f_data[1]
            if any(abs(pts - s.pts_ms) < min_dist_ms for s in selected):
                continue
            roi_px = None
            if s_bbox:
                # normalize to px
                h, w = f_data[2].shape[:2]
                roi_px = [
                    int(s_bbox[0] * w), int(s_bbox[1] * h),
                    int((s_bbox[2] - s_bbox[0]) * w), int((s_bbox[3] - s_bbox[1]) * h),
                ]
            selected.append(
                FrameCandidate(
                    frame_index=f_data[0],
                    pts_ms=pts,
                    score=score,
                    roi=roi_px,
                    features={"dirty_tiles": float(deltas[idx][0])},
                    rationale="spatial_matrix_dirty_peak",
                )
            )

        # Sort back chronologically
        selected.sort(key=lambda c: c.pts_ms)
        return selected, {"strategy": "spatial_only", "scored_frames": len(frames)}

    # -------------------------------------------------------------------------
    # Strategy C: Hybrid One-Pass
    # -------------------------------------------------------------------------

    def _strategy_hybrid_onepass(
        self,
        frames: list[tuple[int, float, np.ndarray]],
        budget: int,
        is_text: bool,
        is_flash: bool,
        is_ui: bool,
    ) -> tuple[list[FrameCandidate], dict[str, Any]]:
        """Uniform base grid + local search for sharpest/most informative frame."""
        ui_mask = self._estimate_ui_likelihood_map(frames)
        n = len(frames)

        # Precompute features per frame
        frame_feats: list[dict[str, Any]] = []
        for fi, pts, arr in frames:
            sh, ed, cont, roi, roi_sal = self._compute_frame_features(arr, ui_mask, is_ui)
            # Compose weighted score based on question intent
            if is_text:
                score = sh * 0.6 + ed * 0.3 + cont * 0.1
            elif is_flash:
                score = cont * 0.5 + ed * 0.3 + sh * 0.2
            else:
                score = sh * 0.4 + ed * 0.4 + cont * 0.2
            frame_feats.append({
                "score": score,
                "world_sharpness": sh,
                "world_edges": ed,
                "contrast": cont,
                "roi": roi,
            })

        # Uniform base slots
        step = n / float(budget)
        slot_half = max(1, int(step * 0.5))
        chosen_indices: list[int] = []

        for i in range(budget):
            center = int((i + 0.5) * step)
            win_start = max(0, center - slot_half)
            win_end = min(n, center + slot_half + 1)
            # Find argmax score in this temporal slot
            best_idx = win_start
            best_score = -1.0
            for idx in range(win_start, win_end):
                if frame_feats[idx]["score"] > best_score:
                    best_score = frame_feats[idx]["score"]
                    best_idx = idx
            if best_idx not in chosen_indices:
                chosen_indices.append(best_idx)

        chosen_indices.sort()
        candidates = [
            FrameCandidate(
                frame_index=frames[idx][0],
                pts_ms=frames[idx][1],
                score=frame_feats[idx]["score"],
                roi=frame_feats[idx]["roi"],
                features={
                    "world_sharpness": frame_feats[idx]["world_sharpness"],
                    "world_edges": frame_feats[idx]["world_edges"],
                },
                rationale="hybrid_onepass_slot_peak",
            )
            for idx in chosen_indices
        ]
        return candidates, {"strategy": "hybrid_onepass", "ui_suppression_active": not is_ui}

    # -------------------------------------------------------------------------
    # Strategy D: Hybrid Adaptive (Deterministic Anchor-Satellite Weaving)
    # -------------------------------------------------------------------------

    def _strategy_old_hybrid_adaptive(
        self,
        frames: list[tuple[int, float, np.ndarray]],
        budget: int,
        is_text: bool,
        is_flash: bool,
        is_ui: bool,
    ) -> tuple[list[FrameCandidate], dict[str, Any]]:
        """Old Hybrid Adaptive (v1): coarse grid sweep + temporal refinement burst.

        Note: Does NOT guarantee subset nesting S_{K1} ⊂ S_{K2} due to
        independent stride and peak shifts at different budgets.
        """
        n = len(frames)
        if n == 0:
            return [], {"strategy": "old_hybrid_adaptive"}

        ui_mask = self._estimate_ui_likelihood_map(frames)
        k_coarse = max(2, budget // 2)
        k_burst = budget - k_coarse
        step = max(1, n // k_coarse)
        coarse_indices = [min(n - 1, i * step) for i in range(k_coarse)]

        # Score coarse frames
        coarse_scores = []
        for idx in coarse_indices:
            arr = frames[idx][2]
            sh, ed, cont, _, _ = self._compute_frame_features(arr, ui_mask, is_ui)
            sc = sh * 0.6 + ed * 0.3 + cont * 0.1 if is_text else sh * 0.4 + ed * 0.4 + cont * 0.2
            coarse_scores.append(sc)

        best_coarse_idx = coarse_indices[int(np.argmax(coarse_scores))]
        # Refinement burst around best coarse peak
        burst_half = max(1, k_burst // 2)
        burst_indices = [
            i for i in range(max(0, best_coarse_idx - burst_half), min(n, best_coarse_idx + burst_half + 1))
            if i not in coarse_indices
        ][:k_burst]

        selected_indices = sorted(set(coarse_indices + burst_indices))[:budget]
        candidates = [
            FrameCandidate(
                frame_index=frames[i][0],
                pts_ms=frames[i][1],
                score=coarse_scores[coarse_indices.index(i)] if i in coarse_indices else 0.5,
                rationale="coarse" if i in coarse_indices else "burst",
            )
            for i in selected_indices
        ]
        return candidates, {"strategy": "old_hybrid_adaptive"}

    def _strategy_hybrid_adaptive(
        self,
        frames: list[tuple[int, float, np.ndarray]],
        budget: int,
        is_text: bool,
        is_flash: bool,
        is_ui: bool,
        roi_boost: bool = True,
    ) -> tuple[list[FrameCandidate], dict[str, Any]]:
        """Unified deterministic ranking using Anchor-Satellite Weaving.

        Guarantees strict subset nesting: S_{K1} ⊂ S_{K2} for all K1 < K2.
        Combines broad temporal coverage (anchors with NMS >= 250ms) with dense
        burst coverage (sharp satellites within ±100ms) around high-saliency events.
        """
        ui_mask = self._estimate_ui_likelihood_map(frames)
        n = len(frames)
        if n == 0:
            return [], {"strategy": "hybrid_adaptive"}

        # Precompute features for all decoded frames
        frame_feats: list[dict[str, Any]] = []
        scores: list[float] = []
        sharp_edge_scores: list[float] = []
        pts_list: list[float] = []

        for fi, pts, arr in frames:
            pts_list.append(pts)
            sh, ed, cont, roi, roi_sal = self._compute_frame_features(arr, ui_mask, is_ui)
            if is_text:
                score = sh * 0.6 + ed * 0.3 + cont * 0.1
            elif is_flash:
                score = cont * 0.5 + ed * 0.3 + sh * 0.2
            else:
                score = sh * 0.4 + ed * 0.4 + cont * 0.2

            if roi_boost:
                score = score * (1.0 + 0.35 * min(roi_sal, 5.0))

            scores.append(score)
            sharp_edge_scores.append(sh * (ed + 0.1))
            frame_feats.append({
                "score": score,
                "world_sharpness": sh,
                "world_edges": ed,
                "contrast": cont,
                "roi": roi,
            })

        # Global deterministic ordering of all candidates via Anchor-Satellite Weaving
        ordered_indices = rank_all_candidates_anchor_satellite(
            pts_ms_list=pts_list,
            scores=scores,
            sharp_edge_scores=sharp_edge_scores,
            nms_anchor_ms=250.0,
            max_sat_dist_ms=100.0,
        )

        chosen_indices = ordered_indices[:budget]
        # Preserve chronological order in final selected candidates for downstream processing
        sorted_indices = sorted(chosen_indices)

        candidates = [
            FrameCandidate(
                frame_index=frames[idx][0],
                pts_ms=frames[idx][1],
                score=scores[idx],
                roi=frame_feats[idx]["roi"],
                features={
                    "world_sharpness": frame_feats[idx]["world_sharpness"],
                    "world_edges": frame_feats[idx]["world_edges"],
                },
                rationale="anchor" if idx in ordered_indices[:5] else "satellite_or_gap",
            )
            for idx in sorted_indices
        ]

        strat_name = "weaving_roi_boosted" if roi_boost else "weaving_scalar"
        return candidates, {
            "strategy": strat_name,
            "expansion_mode": "anchor_satellite_weaving",
            "ordered_count": len(ordered_indices),
            "chosen_count": len(candidates),
        }

    # -------------------------------------------------------------------------
    # Baseline: Oracle Best-Frame
    # -------------------------------------------------------------------------

    def _select_oracle(
        self,
        video_path: str | Path,
        start_ms: float,
        end_ms: float,
        budget: int,
        oracle_gt: dict[str, Any] | None,
        t0: float,
    ) -> FrameSelectionResult:
        """Oracle baseline: picks frames directly from ground-truth interval."""
        if not oracle_gt or "start_frame" not in oracle_gt:
            raise ValueError("Oracle strategy requires oracle_gt with start_frame and end_frame")

        gt_start_f = oracle_gt["start_frame"]
        gt_end_f = oracle_gt["end_frame"]

        decoder = VideoWindowDecoder(video_path)
        t_dec0 = time.perf_counter()
        # Decode only the ground truth interval
        frames = decoder.decode_window(
            oracle_gt.get("start_ms", start_ms),
            oracle_gt.get("start_ms", start_ms) + oracle_gt.get("duration_ms", 500.0),
        )
        decode_ms = (time.perf_counter() - t_dec0) * 1000.0

        if not frames:
            total_ms = (time.perf_counter() - t0) * 1000.0
            return FrameSelectionResult(
                strategy="oracle",
                budget=budget,
                search_window_ms=(start_ms, end_ms),
                selected_frames=[],
                target_status="not_found_in_sample",
                detail_status="unknown",
                coverage_status="sparse",
                decode_ms=decode_ms,
                scoring_ms=0.0,
                total_ms=total_ms,
            )

        t_score0 = time.perf_counter()
        # Filter to frames strictly in GT
        gt_frames = [f for f in frames if gt_start_f <= f[0] <= gt_end_f]
        if not gt_frames:
            gt_frames = frames

        # Score by luma contrast / Laplacian sharpness
        scored: list[tuple[float, tuple[int, float, np.ndarray]]] = []
        for f in gt_frames:
            img = f[2]
            luma = (
                (img[:, :, 0].astype(np.uint16) +
                 (img[:, :, 1].astype(np.uint16) << 1) +
                 img[:, :, 2].astype(np.uint16)) >> 2
            ).astype(np.float32)
            gx = np.abs(luma[:, 2:] - luma[:, :-2])
            gy = np.abs(luma[2:, :] - luma[:-2, :])
            sh = float((gx[1:-1, :] + gy[:, 1:-1]).var())
            scored.append((sh, f))

        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = scored[:budget]
        chosen.sort(key=lambda x: x[1][1])

        candidates = [
            FrameCandidate(
                frame_index=f_data[0],
                pts_ms=f_data[1],
                score=sh,
                roi=oracle_gt.get("roi"),
                features={"oracle_sharpness": sh},
                rationale="oracle_ground_truth_best_frame",
            )
            for sh, f_data in chosen
        ]
        scoring_ms = (time.perf_counter() - t_score0) * 1000.0
        total_ms = (time.perf_counter() - t0) * 1000.0

        detail_status = "observed_readable" if oracle_gt.get("readable", True) else "observed_unreadable"

        return FrameSelectionResult(
            strategy="oracle",
            budget=budget,
            search_window_ms=(start_ms, end_ms),
            selected_frames=candidates,
            target_status="observed_present",
            detail_status=detail_status,
            coverage_status="complete",
            decode_ms=decode_ms,
            scoring_ms=scoring_ms,
            total_ms=total_ms,
            metadata={"oracle_event_id": oracle_gt.get("event_id")},
        )
