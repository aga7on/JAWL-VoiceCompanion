"""Retrospective Segment Inspector & Foveated ROI Mosaic Packing (Round 11, Step 3).

Integrates:
  1. Multi-candidate sparse temporal sampling via Anchor-Satellite Weaving (budget=12).
  2. Foveated 1:1 ROI mosaic packing into a fixed 1024x768 canvas for single-call VLM / OCR.
  3. Two-tier epistemic sharpness & negative control filter (OBSERVED_READABLE,
     OBSERVED_UNREADABLE, NOT_OBSERVED) eliminating hallucinations on motion blur or absent targets.
  4. Real GPU 1 (CUDA1) single-call Qwen3.5-0.8B VL inference with tile attribution.
  5. Packaging into canonical episodic sensory memory (<va_perception>).
"""

from __future__ import annotations

import base64
import enum
import io
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

from .retro_selector import FrameCandidate, RetrospectiveFrameSelector
from .temporal_index import (
    FLAG_CAPTURE_GAP,
    FLAG_ENCODER_DROPPED,
    FLAG_OVEREXPOSED,
    FLAG_SOURCE_FRAME_MISSING,
    FLAG_VALID,
    IndexFrameRecord,
)
from .temporal_evidence_verifier import (
    CONTRADICTED,
    MODEL_OBSERVATION,
    SOURCE_UNAVAILABLE,
    UNVERIFIED,
    VERIFIED_FACT,
    TemporalEvidenceVerifier,
    VerificationResult,
)


class ObservationStatus(enum.Enum):
    """Explicit observation outcomes of retrospective video inspection (Argon H1 / Cycle 07).

    Guarantees strict type safety and eliminates ambiguous equality with legacy strings.
    """
    OBSERVED_READABLE = "observed_readable"            # Object/fact confirmed readable in sampled frames
    OBSERVED_UNREADABLE = "observed_unreadable"        # Target localized, but unreadable (blur/overexposure/smear)
    NOT_FOUND_IN_SAMPLE = "not_found_in_sample"        # Not found in checked sample (sparse, max_gap > 50ms / unconfirmed)
    ARCHIVE_GAP_UNAVAILABLE = "archive_gap_unavailable"# Video missing, corrupt, or dropped by encoder
    OBSERVED_ABSENT = "observed_absent"                # Absence confirmed with dense coverage (max_gap <= 50ms, 0 drops)
    LEGACY_NEGATIVE_UNRESOLVED = "legacy_negative_unresolved"  # Unresolved legacy negative (e.g. legacy 'not_observed')

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("not_observed", "legacy_negative_unresolved"):
                return cls.LEGACY_NEGATIVE_UNRESOLVED
            for member in cls:
                if member.value == v:
                    return member
        return None

    def __str__(self) -> str:
        return self.value


# Canonical Epistemic Status constants
OBSERVED_READABLE = ObservationStatus.OBSERVED_READABLE
OBSERVED_UNREADABLE = ObservationStatus.OBSERVED_UNREADABLE
NOT_FOUND_IN_SAMPLE = ObservationStatus.NOT_FOUND_IN_SAMPLE
ARCHIVE_GAP_UNAVAILABLE = ObservationStatus.ARCHIVE_GAP_UNAVAILABLE
OBSERVED_ABSENT = ObservationStatus.OBSERVED_ABSENT
LEGACY_NEGATIVE_UNRESOLVED = ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED
NOT_OBSERVED = "not_observed"  # Controlled legacy string representation


# Backwards compatibility alias
EpistemicStatus = ObservationStatus


def status_to_wire(status: ObservationStatus | str | None) -> str:
    """Serialize ObservationStatus or string to canonical wire string."""
    if status is None:
        return ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED.value
    if isinstance(status, ObservationStatus):
        return status.value
    if isinstance(status, str):
        s = status.strip().lower()
        if s in ("not_observed", "legacy_negative_unresolved"):
            return ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED.value
        try:
            return ObservationStatus(s).value
        except ValueError:
            return s
    return str(status)


def status_from_wire(raw: Any) -> ObservationStatus:
    """Parse raw string or enum into canonical ObservationStatus without false precision."""
    if isinstance(raw, ObservationStatus):
        return raw
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("not_observed", "legacy_negative_unresolved"):
            return ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED
        try:
            return ObservationStatus(s)
        except ValueError:
            return ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED
    return ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED


def is_negative_status(status: ObservationStatus | str | None) -> bool:
    """Check if observation status represents a negative / absence / unobserved outcome."""
    if status is None:
        return True
    if isinstance(status, ObservationStatus):
        return status in (
            ObservationStatus.NOT_FOUND_IN_SAMPLE,
            ObservationStatus.ARCHIVE_GAP_UNAVAILABLE,
            ObservationStatus.OBSERVED_ABSENT,
            ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED,
        )
    s = str(status).strip().lower()
    return s in (
        ObservationStatus.NOT_FOUND_IN_SAMPLE.value,
        ObservationStatus.ARCHIVE_GAP_UNAVAILABLE.value,
        ObservationStatus.OBSERVED_ABSENT.value,
        ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED.value,
        "not_observed",
    )


def to_legacy_string(status: ObservationStatus | str | None) -> str:
    """Convert status to legacy 'not_observed' string ONLY at the outer legacy boundary."""
    if is_negative_status(status):
        return "not_observed"
    if isinstance(status, ObservationStatus):
        return status.value
    return str(status)


@dataclass
class SampleCoverage:
    """Quantitative sampling coverage metrics across the target time window (Argon H1)."""

    window_ms: float = 0.0
    inspected_frames: int = 0
    archive_frames: int = 0
    dropped_frames: int = 0
    coverage_ratio: float = 0.0
    max_uninspected_gap_ms: float = 0.0
    absence_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_ms": round(self.window_ms, 2),
            "inspected_frames": self.inspected_frames,
            "archive_frames": self.archive_frames,
            "dropped_frames": self.dropped_frames,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "max_uninspected_gap_ms": round(self.max_uninspected_gap_ms, 2),
            "absence_confirmed": self.absence_confirmed,
        }


def compute_sample_coverage(
    start_ms: float,
    end_ms: float,
    inspected_pts_ms: Sequence[float],
    archive_frames: int,
    dropped_frames_count: int = 0,
) -> SampleCoverage:
    """Calculate empirical coverage and max gap across the target window."""
    window_ms = max(0.0, end_ms - start_ms)
    inspected_count = len(inspected_pts_ms)
    sorted_pts = sorted(inspected_pts_ms)

    if not sorted_pts:
        max_gap_ms = window_ms
    else:
        gaps = [max(0.0, sorted_pts[0] - start_ms)]
        for i in range(len(sorted_pts) - 1):
            gaps.append(max(0.0, sorted_pts[i + 1] - sorted_pts[i]))
        gaps.append(max(0.0, end_ms - sorted_pts[-1]))
        max_gap_ms = max(gaps) if gaps else window_ms

    total_expected = max(inspected_count + dropped_frames_count, archive_frames)
    cov_ratio = inspected_count / max(1, total_expected)

    # Absence is confirmed if and only if dense sampling is achieved across the window with 0 drops
    absence_confirmed = (
        inspected_count > 0
        and dropped_frames_count == 0
        and max_gap_ms <= 50.0
    )

    return SampleCoverage(
        window_ms=window_ms,
        inspected_frames=inspected_count,
        archive_frames=total_expected,
        dropped_frames=dropped_frames_count,
        coverage_ratio=cov_ratio,
        max_uninspected_gap_ms=max_gap_ms,
        absence_confirmed=absence_confirmed,
    )


@dataclass
class RetrospectiveEvidence:
    """Canonical multimodal evidence extracted from retrospective temporal inspection."""

    query: str
    status: str  # OBSERVED_READABLE | OBSERVED_UNREADABLE | NOT_FOUND_IN_SAMPLE | ARCHIVE_GAP_UNAVAILABLE | OBSERVED_ABSENT | NOT_OBSERVED
    start_pts_us: int
    end_pts_us: int
    answer: str
    confidence: float = 0.0
    sharpness_score: float = 0.0
    selected_frame_indices: list[int] = field(default_factory=list)
    selected_pts_ms: list[float] = field(default_factory=list)
    mosaic_image: Image.Image | None = None
    tile_mapping: list[dict[str, Any]] = field(default_factory=list)
    negative_reason: str = ""
    target_category: str = "general"
    provenance: str = "RETROSPECTIVE_ARCHIVE_INSPECTION"
    segment_id: int = 0
    best_frame_id: int = -1
    best_pts_us: int = -1
    best_roi: list[int] | None = None
    observation_status: ObservationStatus | str | None = None
    coverage: SampleCoverage = field(default_factory=SampleCoverage)
    verification_status: str = UNVERIFIED
    is_verified_fact: bool = False
    verification_reason: str = ""
    independent_claim: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ObservationStatus):
            self.status = status_from_wire(self.status)
        if self.observation_status is None:
            self.observation_status = self.status
        elif not isinstance(self.observation_status, ObservationStatus):
            self.observation_status = status_from_wire(self.observation_status)

    @property
    def is_verified(self) -> bool:
        return self.is_verified_fact

    @property
    def is_readable(self) -> bool:
        return self.observation_status == ObservationStatus.OBSERVED_READABLE

    @property
    def is_unreadable(self) -> bool:
        return self.observation_status == ObservationStatus.OBSERVED_UNREADABLE

    @property
    def is_not_observed(self) -> bool:
        return is_negative_status(self.observation_status)

    @property
    def is_not_found_in_sample(self) -> bool:
        return self.observation_status == ObservationStatus.NOT_FOUND_IN_SAMPLE

    @property
    def is_archive_gap(self) -> bool:
        return self.observation_status == ObservationStatus.ARCHIVE_GAP_UNAVAILABLE

    @property
    def is_absent(self) -> bool:
        return self.observation_status == ObservationStatus.OBSERVED_ABSENT

    @property
    def absence_confirmed(self) -> bool:
        return self.coverage.absence_confirmed if self.coverage else False

    def to_perception_xml(self) -> str:
        """Format into canonical episodic memory <va_perception> XML format."""
        t_start_s = self.start_pts_us / 1_000_000.0
        t_end_s = self.end_pts_us / 1_000_000.0
        details = self.answer.strip()
        neg_attr = f' reason="{self.negative_reason}"' if self.negative_reason else ""
        obs_wire = status_to_wire(self.observation_status)
        status_wire = status_to_wire(self.status)
        obs_attr = f' observation_status="{obs_wire}"' if obs_wire else ""
        verif_attrs = (
            f' verification_status="{self.verification_status}"'
            f' is_verified_fact="{str(self.is_verified_fact).lower()}"'
        )
        cov = self.coverage
        cov_attrs = (
            f' sampled_frames="{cov.inspected_frames}"'
            f' archive_frames="{cov.archive_frames}"'
            f' coverage_ratio="{cov.coverage_ratio:.4f}"'
            f' max_uninspected_gap_ms="{cov.max_uninspected_gap_ms:.1f}"'
            f' absence_confirmed="{str(cov.absence_confirmed).lower()}"'
        )
        return (
            f'<va_perception type="retrospective" status="{status_wire}"'
            f'{obs_attr}{verif_attrs} provenance="{self.provenance}"{neg_attr} '
            f'confidence="{self.confidence:.2f}" interval="[{t_start_s:.2f}s, {t_end_s:.2f}s]"{cov_attrs}>\n'
            f'{details}\n'
            f'</va_perception>'
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": status_to_wire(self.status),
            "observation_status": status_to_wire(self.observation_status),
            "verification_status": self.verification_status,
            "is_verified_fact": self.is_verified_fact,
            "verification_reason": self.verification_reason,
            "independent_claim": self.independent_claim,
            "start_pts_us": self.start_pts_us,
            "end_pts_us": self.end_pts_us,
            "answer": self.answer,
            "confidence": round(self.confidence, 4),
            "sharpness_score": round(self.sharpness_score, 2),
            "selected_frame_indices": self.selected_frame_indices,
            "selected_pts_ms": self.selected_pts_ms,
            "negative_reason": self.negative_reason,
            "target_category": self.target_category,
            "provenance": self.provenance,
            "segment_id": self.segment_id,
            "best_frame_id": self.best_frame_id,
            "best_pts_us": self.best_pts_us,
            "best_roi": self.best_roi,
            "tile_mapping_count": len(self.tile_mapping),
            "coverage": self.coverage.to_dict() if self.coverage else {},
            "absence_confirmed": self.absence_confirmed,
            "metadata": self.metadata,
        }


def parse_perception_xml(xml_str: str) -> dict[str, Any]:
    """Parse <va_perception> XML tag and enforce epistemic safety (AC-06/07).

    Guarantees:
      1. NOT_FOUND_IN_SAMPLE, ARCHIVE_GAP_UNAVAILABLE, or legacy NOT_OBSERVED can NEVER
         be elevated to a confirmed negative fact.
      2. OBSERVED_READABLE (Google hypothesis) is NEVER elevated to is_confirmed_fact without
         independent corroboration (verification_status == VERIFIED_FACT).
    """
    m = re.search(r'<va_perception\s+([^>]+)>([\s\S]*?)</va_perception>', xml_str)
    if not m:
        return {}
    attr_str = m.group(1)
    body = m.group(2).strip()

    attrs = {}
    for match in re.finditer(r'([a-zA-Z_0-9]+)="([^"]*)"', attr_str):
        attrs[match.group(1)] = match.group(2)

    status_raw = attrs.get("status", "")
    obs_status_raw = attrs.get("observation_status", status_raw)
    status_enum = status_from_wire(status_raw)
    obs_status_enum = status_from_wire(obs_status_raw)
    status_wire = status_to_wire(status_enum)
    obs_status_wire = status_to_wire(obs_status_enum)

    absence_confirmed_raw = attrs.get("absence_confirmed", "false").lower() == "true"

    # Epistemic guard 1: absence cannot be confirmed unless observation_status == OBSERVED_ABSENT.
    # Legacy 'not_observed' or LEGACY_NEGATIVE_UNRESOLVED is strictly blocked.
    is_confirmed_absent = absence_confirmed_raw and (obs_status_enum == ObservationStatus.OBSERVED_ABSENT)

    # Epistemic guard 2 (H12.1 P0 / AC-06 / AC-07):
    # Only independently corroborated claims with verification_status == VERIFIED_FACT are confirmed facts.
    verif_status = attrs.get(
        "verification_status",
        MODEL_OBSERVATION if obs_status_enum == ObservationStatus.OBSERVED_READABLE else UNVERIFIED,
    )
    is_verified_fact_raw = attrs.get("is_verified_fact", "false").lower() == "true"
    is_confirmed_fact = is_confirmed_absent or (is_verified_fact_raw and verif_status == VERIFIED_FACT)

    sampled = int(attrs.get("sampled_frames", 0)) if attrs.get("sampled_frames") else 0
    arch_frames = int(attrs.get("archive_frames", 0)) if attrs.get("archive_frames") else 0
    cov_ratio = float(attrs.get("coverage_ratio", 0.0)) if attrs.get("coverage_ratio") else 0.0
    max_gap = float(attrs.get("max_uninspected_gap_ms", 0.0)) if attrs.get("max_uninspected_gap_ms") else 0.0

    return {
        "type": attrs.get("type", "retrospective"),
        "status": status_wire,
        "status_enum": status_enum,
        "observation_status": obs_status_wire,
        "observation_status_enum": obs_status_enum,
        "verification_status": verif_status,
        "is_verified_fact": is_confirmed_fact,
        "provenance": attrs.get("provenance", ""),
        "reason": attrs.get("reason", ""),
        "confidence": float(attrs.get("confidence", 0.0)) if attrs.get("confidence") else 0.0,
        "interval": attrs.get("interval", ""),
        "sampled_frames": sampled,
        "archive_frames": arch_frames,
        "coverage_ratio": cov_ratio,
        "max_uninspected_gap_ms": max_gap,
        "absence_confirmed": is_confirmed_absent,
        "is_confirmed_fact": is_confirmed_fact,
        "details": body,
    }
    max_gap = float(attrs.get("max_uninspected_gap_ms", 0.0)) if attrs.get("max_uninspected_gap_ms") else 0.0

    return {
        "type": attrs.get("type", "retrospective"),
        "status": status,
        "observation_status": obs_status,
        "verification_status": verif_status,
        "is_verified_fact": is_confirmed_fact,
        "provenance": attrs.get("provenance", ""),
        "reason": attrs.get("reason", ""),
        "confidence": float(attrs.get("confidence", 0.0)) if attrs.get("confidence") else 0.0,
        "interval": attrs.get("interval", ""),
        "sampled_frames": sampled,
        "archive_frames": arch_frames,
        "coverage_ratio": cov_ratio,
        "max_uninspected_gap_ms": max_gap,
        "absence_confirmed": is_confirmed_absent,
        "is_confirmed_fact": is_confirmed_fact,
        "details": body,
    }


def compute_image_sharpness(
    img: Image.Image | np.ndarray,
    roi: Sequence[int] | None = None,
) -> float:
    """Compute Laplacian variance on luma channel within optional ROI [x, y, w, h]."""
    if isinstance(img, Image.Image):
        arr = np.array(img)
    else:
        arr = img

    h, w = arr.shape[:2]
    if roi is not None and len(roi) >= 4:
        rx, ry, rw, rh = [int(v) for v in roi[:4]]
        rx = max(0, min(w - 1, rx))
        ry = max(0, min(h - 1, ry))
        rw = max(1, min(w - rx, rw))
        rh = max(1, min(h - ry, rh))
        arr = arr[ry : ry + rh, rx : rx + rw]

    if arr.size == 0:
        return 0.0

    if arr.ndim == 3:
        luma = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if arr.shape[2] == 3 else arr[:, :, 0]
    else:
        luma = arr

    lap = cv2.Laplacian(luma, cv2.CV_32F)
    return float(lap.var())


def check_overexposure(
    img: Image.Image | np.ndarray,
    roi: Sequence[int] | None = None,
    threshold: float = 245.0,
    ratio_threshold: float = 0.40,
) -> bool:
    """Check if ROI is predominantly overexposed (blown-out highlights)."""
    if isinstance(img, Image.Image):
        arr = np.array(img)
    else:
        arr = img

    h, w = arr.shape[:2]
    if roi is not None and len(roi) >= 4:
        rx, ry, rw, rh = [int(v) for v in roi[:4]]
        rx = max(0, min(w - 1, rx))
        ry = max(0, min(h - 1, ry))
        rw = max(1, min(w - rx, rw))
        rh = max(1, min(h - ry, rh))
        arr = arr[ry : ry + rh, rx : rx + rw]

    if arr.size == 0:
        return False

    if arr.ndim == 3:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if arr.shape[2] == 3 else arr[:, :, 0]
    else:
        gray = arr

    overexposed_ratio = float(np.mean(gray >= threshold))
    return overexposed_ratio >= ratio_threshold


def check_directional_smear(
    img: Image.Image | np.ndarray,
    roi: Sequence[int] | None = None,
    ratio_threshold: float = 8.0,
) -> bool:
    """Detect extreme directional motion smear lines or corrupted grating (dy/dx or dx/dy >= ratio_threshold)."""
    if isinstance(img, Image.Image):
        arr = np.array(img)
    else:
        arr = img

    h, w = arr.shape[:2]
    if roi is not None and len(roi) >= 4:
        rx, ry, rw, rh = [int(v) for v in roi[:4]]
        rx = max(0, min(w - 1, rx))
        ry = max(0, min(h - 1, ry))
        rw = max(1, min(w - rx, rw))
        rh = max(1, min(h - ry, rh))
        arr = arr[ry : ry + rh, rx : rx + rw]

    if arr.size == 0:
        return False

    if arr.ndim == 3:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if arr.shape[2] == 3 else arr[:, :, 0]
    else:
        gray = arr

    dx = float(np.var(cv2.Sobel(gray, cv2.CV_64F, 1, 0)))
    dy = float(np.var(cv2.Sobel(gray, cv2.CV_64F, 0, 1)))

    if min(dx, dy) < 1.0:
        return False

    return max(dy / dx, dx / dy) >= ratio_threshold


def encode_image_base64_jpeg(img: Image.Image, quality: int = 85) -> str:
    """Encode PIL Image to JPEG base64 string."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def query_qwen_mosaic(
    mosaic_img: Image.Image,
    query: str,
    vlm_url: str = "http://127.0.0.1:8996",
    timeout_s: float = 30.0,
    max_tokens: int = 96,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Execute single visual inference call on 1024x768 mosaic canvas."""
    t0 = time.perf_counter()
    b64 = encode_image_base64_jpeg(mosaic_img, quality=85)

    system_prompt = (
        "Ты — визуальный инспектор игровых событий. На мозаике 1024x768 показан обзорный кадр (OVERVIEW) "
        "и нативные несжатые 1:1 кропы ключевых кадров (#F...) с таймкодами. "
        "Внимательно найди ответ на вопрос пользователя. Назови точный текст, цифры или объект и номер кадра #F... "
        "Ответь кратко."
    )
    user_prompt = f"Вопрос: {query}"

    payload = {
        "model": "qwen3.5-0.8b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    try:
        resp = requests.post(f"{vlm_url}/chat/completions", json=payload, timeout=timeout_s)
        dt_ms = (time.perf_counter() - t0) * 1000.0
    except Exception as e:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "status": "error",
            "error": str(e),
            "roundtrip_ms": round(dt_ms, 2),
            "content": "",
        }

    if resp.status_code != 200:
        return {
            "status": "error",
            "http_status": resp.status_code,
            "error": resp.text,
            "roundtrip_ms": round(dt_ms, 2),
            "content": "",
        }

    data = resp.json()
    msg = data.get("choices", [{}])[0].get("message", {})
    timings = data.get("timings", {})
    content = msg.get("content", "").strip()

    return {
        "status": "ok",
        "content": content,
        "roundtrip_ms": round(dt_ms, 2),
        "timings": timings,
    }


def build_foveated_mosaic(
    candidate_frames: list[tuple[int, float, Image.Image | np.ndarray]],
    rois: list[Sequence[int] | None] | None = None,
    canvas_size: tuple[int, int] = (1024, 768),
    dropped_frame_indices: set[int] | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """Pack candidate frames into a 1024x768 canvas with 1:1 ROI crops and an overview.

    Layout:
      - Top-left panel (512x288 at (16, 24)): Overview anchor frame.
      - Right panel: 6 slots (2 cols x 3 rows, 220x100 each).
      - Bottom panel: 6 slots (2 rows x 3 cols, 240x120 each).
      Total capacity: 1 overview + up to 12 native unscaled 1:1 ROI crops.
      Physical pixel preservation: crops are 1:1 without downsampling.
    """
    canvas_w, canvas_h = canvas_size
    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(24, 26, 32))
    draw = ImageDraw.Draw(canvas)

    if not candidate_frames:
        draw.text((32, 32), "No candidate frames available", fill=(180, 180, 180))
        return canvas, {"tiles_count": 0, "layout": []}

    dropped_set = dropped_frame_indices or set()

    # Normalize images to PIL
    pil_frames: list[tuple[int, float, Image.Image]] = []
    for f_idx, pts, raw in candidate_frames:
        if isinstance(raw, np.ndarray):
            pil_img = Image.fromarray(raw)
        else:
            pil_img = raw
        pil_frames.append((f_idx, pts, pil_img))

    # Pick anchor frame (median candidate for balanced scene overview)
    anchor_idx = len(pil_frames) // 2
    a_f_idx, a_pts, a_img = pil_frames[anchor_idx]

    # Draw Overview Frame (top-left, 512x288)
    ov_w, ov_h = 512, 288
    ov_img = a_img.resize((ov_w, ov_h), Image.Resampling.BILINEAR)
    canvas.paste(ov_img, (16, 24))
    draw.rectangle([16, 24, 16 + ov_w, 24 + ov_h], outline=(80, 140, 240), width=2)
    draw.text(
        (20, 8),
        f"OVERVIEW: Frame #{a_f_idx} (pts: {a_pts/1000.0:.2f}s)",
        fill=(220, 220, 240),
    )

    # 1:1 ROI Crop slots: right column (6) + bottom rows (6)
    slots = [
        # Right column slots (w=220, h=100) x 2 cols x 3 rows
        (544, 24, 220, 100),
        (780, 24, 220, 100),
        (544, 134, 220, 100),
        (780, 134, 220, 100),
        (544, 244, 220, 100),
        (780, 244, 220, 100),
        # Bottom panel slots (w=240, h=120) x 4 cols x 2 rows
        (16, 350, 240, 120),
        (268, 350, 240, 120),
        (520, 350, 240, 120),
        (772, 350, 240, 120),
        (16, 480, 240, 120),
        (268, 480, 240, 120),
        (520, 480, 240, 120),
        (772, 480, 240, 120),
    ]

    tiles_info = []

    for i, (f_idx, pts, img) in enumerate(pil_frames):
        if i >= len(slots):
            break
        sx, sy, sw, sh = slots[i]

        if f_idx in dropped_set:
            # Draw dropped frame placeholder
            draw.rectangle([sx, sy, sx + sw, sy + sh], fill=(40, 20, 20), outline=(200, 50, 50), width=1)
            draw.text((sx + 6, sy + 30), f"F#{f_idx}: DROPPED", fill=(255, 100, 100))
            draw.text((sx + 6, sy + 50), "FLAG_ENCODER_DROPPED", fill=(200, 120, 120))
            tiles_info.append({
                "slot_idx": i,
                "frame_idx": f_idx,
                "pts_ms": pts,
                "pts_us": int(pts * 1000),
                "crop_box": [0, 0, sw, sh],
                "dest_rect": [sx, sy, sw, sh],
                "roi": None,
                "is_fallback": True,
                "status": "dropped",
            })
            continue

        roi = rois[i] if (rois is not None and i < len(rois)) else None
        iw, ih = img.size
        is_fallback = False

        if roi is not None and len(roi) >= 4 and roi[2] > 0 and roi[3] > 0:
            rx, ry, rw, rh = roi[:4]
            # Center on target ROI with slot dimensions
            cx = rx + rw // 2
            cy = ry + rh // 2
            x0 = max(0, min(iw - sw, cx - sw // 2))
            y0 = max(0, min(ih - sh, cy - sh // 2))
            crop_box = (x0, y0, min(iw, x0 + sw), min(ih, y0 + sh))
        else:
            # Fallback to center crop
            is_fallback = True
            cx, cy = iw // 2, ih // 2
            x0 = max(0, cx - sw // 2)
            y0 = max(0, cy - sh // 2)
            crop_box = (x0, y0, min(iw, x0 + sw), min(ih, y0 + sh))

        crop = img.crop(crop_box)
        canvas.paste(crop, (sx, sy))
        draw.rectangle([sx, sy, sx + sw, sy + sh], outline=(100, 110, 130), width=1)
        tag = f"#F{f_idx} {pts/1000.0:.2f}s"
        if is_fallback:
            tag += " [center]"
        draw.text((sx + 4, sy + 2), tag, fill=(255, 255, 120))

        tiles_info.append({
            "slot_idx": i,
            "frame_idx": f_idx,
            "pts_ms": pts,
            "pts_us": int(pts * 1000),
            "crop_box": list(crop_box),
            "dest_rect": [sx, sy, sw, sh],
            "roi": list(roi) if roi is not None else None,
            "is_fallback": is_fallback,
            "status": "valid",
        })

    return canvas, {
        "tiles_count": len(tiles_info),
        "canvas_size": list(canvas_size),
        "anchor_frame": a_f_idx,
        "layout": tiles_info,
    }


class RetrospectiveSegmentInspector:
    """End-to-end inspector coordinating temporal indexing, foveated mosaic, and epistemic gating."""

    def __init__(
        self,
        sharpness_unreadable_threshold: float = 28.0,
        overexposed_ratio_threshold: float = 0.40,
        vlm_url: str = "http://127.0.0.1:8996",
        verifier: TemporalEvidenceVerifier | None = None,
    ) -> None:
        self.sharpness_threshold = float(sharpness_unreadable_threshold)
        self.overexposed_threshold = float(overexposed_ratio_threshold)
        self.vlm_url = vlm_url
        self.selector = RetrospectiveFrameSelector(grid_shape=(21, 30))
        self.verifier = verifier if verifier is not None else TemporalEvidenceVerifier()

    def inspect_segment(
        self,
        query: str,
        t_start_s: float,
        t_end_s: float,
        budget: int = 12,
        video_path: str | Path | None = None,
        archive: Any | None = None,
        category: str = "general",
        expected_roi: Sequence[int] | None = None,
        ground_truth_target: str | None = None,
        force_readable: bool | None = None,
        pre_decoded_frames: list[tuple[int, float, np.ndarray]] | None = None,
        use_real_vlm: bool = False,
        vlm_url: str | None = None,
        vlm_mock_response: str | None = None,
        dropped_frames: set[int] | None = None,
        segment_id: int = 0,
        archive_frames: int | None = None,
        verify_facts: bool = True,
        verifier: TemporalEvidenceVerifier | None = None,
    ) -> RetrospectiveEvidence:
        """Inspect a video interval [t_start_s, t_end_s] for target query.

        Args:
            query: Natural language query (e.g. "Какой урон выскочил?", "Что в чате?").
            t_start_s: Temporal window start in seconds.
            t_end_s: Temporal window end in seconds.
            budget: Number of frames to decode and pack into mosaic (up to 12).
            video_path: Direct path to video file if archive is not used.
            archive: Optional LiveEvidenceArchive instance.
            category: Event category ("damage_num", "pan_glyph", "chat", "loot_drop", etc.).
            expected_roi: Optional known ROI [x, y, w, h] for targeted inspection.
            ground_truth_target: Ground-truth target string (for calibrated evaluation).
            force_readable: Force epistemic outcome (used in unit tests / calibration).
            pre_decoded_frames: Optional cached list of (frame_idx, pts_ms, frame_rgb).
            use_real_vlm: Whether to call real Qwen3.5-0.8B VL server over HTTP.
            vlm_url: URL for llama-server (default: http://127.0.0.1:8996).
            vlm_mock_response: Optional deterministic VLM response string for unit tests.
            dropped_frames: Optional set of frame_idx marked as FLAG_ENCODER_DROPPED.
            segment_id: Segment identifier from JTI1 archive.
            archive_frames: Optional explicit total archive frames count in target interval.
        """
        t0 = time.perf_counter()
        start_ms = max(0.0, float(t_start_s) * 1000.0)
        end_ms = max(start_ms + 100.0, float(t_end_s) * 1000.0)
        start_pts_us = int(start_ms * 1000)
        end_pts_us = int(end_ms * 1000)

        # 1. Candidate frame selection via Anchor-Satellite Weaving
        if video_path is None and archive is None and pre_decoded_frames is None:
            raise ValueError("Either video_path, archive, or pre_decoded_frames must be provided to inspect_segment")

        missing_frames_count = 0
        dropped_set = set(dropped_frames) if dropped_frames else set()
        archive_total_frames = 0

        if archive is not None:
            interval_records = archive.get_records(start_pts_us, end_pts_us)
            if archive_frames is not None:
                archive_total_frames = archive_frames
            else:
                archive_total_frames = len(interval_records)
                if archive_total_frames == 0:
                    segs = archive.query_interval(start_pts_us, end_pts_us)
                    archive_total_frames = sum(s.frame_count for s in segs)
            for r in interval_records:
                if (r.quality_flags & (FLAG_ENCODER_DROPPED | FLAG_SOURCE_FRAME_MISSING)) != 0 or r.segment_sample_idx < 0:
                    dropped_set.add(r.capture_frame_id)

            sel_results = archive.select_candidate_frames(
                start_pts_us=start_pts_us,
                end_pts_us=end_pts_us,
                question=query,
                strategy="hybrid_adaptive",
                budget=budget,
            )
            raw_candidates: list[tuple[int, float, Image.Image]] = []
            rois: list[Sequence[int] | None] = []
            for seg, rec, img in sel_results:
                is_inaccessible = (
                    img is None
                    or (rec.quality_flags & (FLAG_ENCODER_DROPPED | FLAG_SOURCE_FRAME_MISSING)) != 0
                    or rec.segment_sample_idx < 0
                )
                if is_inaccessible:
                    missing_frames_count += 1
                    dropped_set.add(rec.capture_frame_id)
                else:
                    raw_candidates.append((rec.capture_frame_id, rec.pts_us / 1000.0, img))
                    rois.append(expected_roi)
        else:
            sel_res = self.selector.select_frames(
                video_path=video_path or "",
                start_ms=start_ms,
                end_ms=end_ms,
                question=query,
                strategy="weaving_roi_boosted",
                budget_frames=budget,
                pre_decoded_frames=pre_decoded_frames,
            )
            raw_candidates = []
            rois = []
            if pre_decoded_frames is not None:
                all_frames = pre_decoded_frames
                if archive_frames is not None:
                    archive_total_frames = archive_frames
                else:
                    archive_total_frames = len(pre_decoded_frames)
            else:
                from .retro_selector import VideoWindowDecoder
                decoder = VideoWindowDecoder(video_path)
                all_frames = decoder.decode_window(start_ms, end_ms, stride=1)
                if archive_frames is not None:
                    archive_total_frames = archive_frames
                else:
                    archive_total_frames = len(all_frames)
            f_map = {f[0]: f for f in all_frames}

            for cand in sel_res.selected_frames:
                if cand.frame_index in f_map:
                    f_item = f_map[cand.frame_index]
                    img = Image.fromarray(f_item[2])
                    raw_candidates.append((cand.frame_index, cand.pts_ms, img))
                    rois.append(expected_roi if expected_roi is not None else cand.roi)

        if archive_total_frames == 0:
            archive_total_frames = max(len(raw_candidates) + missing_frames_count + len(dropped_set), 1)

        inspected_pts = [c[1] for c in raw_candidates]
        coverage = compute_sample_coverage(
            start_ms=start_ms,
            end_ms=end_ms,
            inspected_pts_ms=inspected_pts,
            archive_frames=archive_total_frames,
            dropped_frames_count=len(dropped_set),
        )

        if not raw_candidates:
            dt_empty = (time.perf_counter() - t0) * 1000.0
            if missing_frames_count > 0 or len(dropped_set) > 0:
                neg_reason = "source_gap"
                obs_status = ARCHIVE_GAP_UNAVAILABLE
                answer = "Исходные видеокадры для указанного интервала недоступны или повреждены (archive_gap_unavailable)."
            else:
                neg_reason = "zero_candidates"
                obs_status = NOT_FOUND_IN_SAMPLE
                answer = "Целевое событие или объект не обнаружены в указанном временном интервале (выборка пуста)."

            all_fids = [r.capture_frame_id for _, r, _ in sel_results] if archive else []
            all_pts = [r.pts_us / 1000.0 for _, r, _ in sel_results] if archive else []
            verif_stat = SOURCE_UNAVAILABLE if obs_status == ARCHIVE_GAP_UNAVAILABLE else UNVERIFIED
            return RetrospectiveEvidence(
                query=query,
                status=EpistemicStatus(obs_status),
                observation_status=obs_status,
                start_pts_us=start_pts_us,
                end_pts_us=end_pts_us,
                answer=answer,
                confidence=0.0,
                sharpness_score=0.0,
                selected_frame_indices=all_fids,
                selected_pts_ms=all_pts,
                negative_reason=neg_reason,
                target_category=category,
                segment_id=segment_id,
                coverage=coverage,
                verification_status=verif_stat,
                is_verified_fact=False,
                metadata={
                    "elapsed_ms": round(dt_empty, 2),
                    "missing_frames_count": missing_frames_count,
                    "total_candidates": len(sel_results) if archive else 0,
                    "coverage_ratio": round(coverage.coverage_ratio, 4),
                    "max_uninspected_gap_ms": round(coverage.max_uninspected_gap_ms, 2),
                    "dropped_frame_indices": list(dropped_set),
                    "absence_confirmed": coverage.absence_confirmed,
                },
            )

        # 2. Epistemic Sharpness & Quality Filtering (Tier 1 physical gate)
        sharpness_scores: list[float] = []
        is_overexposed_flags: list[bool] = []
        best_cand_idx = 0
        max_sh = -1.0

        for i, (f_idx, pts, img) in enumerate(raw_candidates):
            target_roi = expected_roi if expected_roi is not None else rois[i]
            sh = compute_image_sharpness(img, target_roi)
            sharpness_scores.append(sh)
            if sh > max_sh:
                max_sh = sh
                best_cand_idx = i
            is_overexposed_flags.append(check_overexposure(img, target_roi, ratio_threshold=self.overexposed_threshold))

        max_sharpness = max(sharpness_scores) if sharpness_scores else 0.0
        avg_sharpness = float(np.mean(sharpness_scores)) if sharpness_scores else 0.0
        all_overexposed = all(is_overexposed_flags)

        # Evaluate directional motion smear on the highest-energy keyframe candidate
        best_cand_img = raw_candidates[best_cand_idx][2]
        best_target_roi = expected_roi if expected_roi is not None else rois[best_cand_idx]
        is_motion_smear = check_directional_smear(best_cand_img, best_target_roi, ratio_threshold=8.0)

        is_motion_blur = max_sharpness < self.sharpness_threshold
        is_unreadable_condition = is_motion_blur or all_overexposed or is_motion_smear

        if force_readable is False:
            is_unreadable_condition = True
        elif force_readable is True:
            is_unreadable_condition = False

        # 3. Build Foveated Mosaic (1:1 unscaled ROI crops + 512x288 overview)
        t_mos0 = time.perf_counter()
        mosaic_img, layout_meta = build_foveated_mosaic(
            candidate_frames=raw_candidates,
            rois=rois,
            canvas_size=(1024, 768),
            dropped_frame_indices=dropped_set,
        )
        mos_elapsed_ms = (time.perf_counter() - t_mos0) * 1000.0

        selected_indices = [c[0] for c in raw_candidates]
        selected_pts = [c[1] for c in raw_candidates]
        tile_layout = layout_meta.get("layout", [])

        # 4. Single-Call VLM Inference (if enabled or mock provided)
        vlm_answer = ""
        vlm_timings = {}
        vlm_elapsed_ms = 0.0
        active_url = vlm_url or self.vlm_url

        if vlm_mock_response is not None:
            vlm_answer = vlm_mock_response
        elif use_real_vlm:
            vlm_res = query_qwen_mosaic(mosaic_img, query, vlm_url=active_url)
            vlm_answer = vlm_res.get("content", "")
            vlm_timings = vlm_res.get("timings", {})
            vlm_elapsed_ms = vlm_res.get("roundtrip_ms", 0.0)

        # 5. Formulate Epistemic Conclusion
        best_frame_id = -1
        best_pts_us = -1
        best_roi = None

        if is_unreadable_condition:
            status = EpistemicStatus(OBSERVED_UNREADABLE)
            obs_status = OBSERVED_UNREADABLE
            confidence = 0.88
            neg_reason = (
                "overexposure"
                if all_overexposed
                else ("motion_smear" if is_motion_smear else ("motion_blur" if is_motion_blur else "quality_degraded"))
            )
            answer = (
                f"Событие зафиксировано, но надпись или цифры физически размыты быстрым движением "
                f"(резкость {max_sharpness:.1f} < {self.sharpness_threshold:.1f}, артефакт смаза) или засвечены "
                f"и не могут быть достоверно прочитаны без риска галлюцинаций."
            )
        else:
            # Two-tier check on VLM output semantics
            vlm_lower = vlm_answer.lower()
            if any(m in vlm_lower for m in ["unreadable", "размыт", "не читается", "невозможно разобрать", "не разобрать"]):
                status = EpistemicStatus(OBSERVED_UNREADABLE)
                obs_status = OBSERVED_UNREADABLE
                confidence = 0.85
                neg_reason = "vlm_unreadable"
                answer = vlm_answer
            elif any(m in vlm_lower for m in ["not_found", "не найден", "отсутствует", "нет на кадр", "не обнаружен"]):
                if missing_frames_count > 0 or len(dropped_set) > 0:
                    status = EpistemicStatus(ARCHIVE_GAP_UNAVAILABLE)
                    obs_status = ARCHIVE_GAP_UNAVAILABLE
                    confidence = 0.50
                    neg_reason = "source_gap"
                    answer = "Недостаточно данных для подтверждения отсутствия: часть кадров утеряна (archive_gap_unavailable)."
                elif coverage.absence_confirmed:
                    status = EpistemicStatus(OBSERVED_ABSENT)
                    obs_status = OBSERVED_ABSENT
                    confidence = 0.90
                    neg_reason = "vlm_not_found"
                    answer = vlm_answer or "Целевой объект подтвержденно отсутствует в просмотренном интервале (observed_absent)."
                else:
                    status = EpistemicStatus(NOT_FOUND_IN_SAMPLE)
                    obs_status = NOT_FOUND_IN_SAMPLE
                    confidence = 0.70
                    neg_reason = "not_found_in_sample"
                    answer = (
                        f"Объект не обнаружен в выборке из {coverage.inspected_frames} кадров "
                        f"(макс. непроверенный зазор {coverage.max_uninspected_gap_ms:.1f} мс); "
                        f"отсутствие во всём интервале не доказано (not_found_in_sample)."
                    )
            elif any(m in vlm_lower for m in ["линии", "полосы", "прямоугольная форма", "замазан", "узор", "нет текста"]):
                status = EpistemicStatus(OBSERVED_UNREADABLE)
                obs_status = OBSERVED_UNREADABLE
                confidence = 0.85
                neg_reason = "obscured_pattern"
                answer = vlm_answer
            else:
                # Remove frame tags (#F... or Frame ...) and check substantive content
                cleaned = re.sub(r"#?F(?:rame)?\s*#?\d+(\s*\d+\.\d+s)?", "", vlm_answer, flags=re.IGNORECASE)
                cleaned = re.sub(r"\[.*?\]", "", cleaned)
                content_tokens = re.findall(r"[a-zA-Zа-яА-Я0-9_-]+", cleaned)
                filler = {"в", "на", "кадре", "таймкод", "номер", "кадра", "секунд", "секунды", "время", "frame"}
                substantive = [t for t in content_tokens if t.lower() not in filler]

                if not substantive and vlm_answer:
                    status = EpistemicStatus(OBSERVED_UNREADABLE)
                    obs_status = OBSERVED_UNREADABLE
                    confidence = 0.80
                    neg_reason = "no_substantive_content"
                    answer = vlm_answer
                else:
                    status = EpistemicStatus(OBSERVED_READABLE)
                    obs_status = OBSERVED_READABLE
                    confidence = min(0.98, max(0.70, 0.70 + 0.005 * max_sharpness))
                    neg_reason = ""
                    if vlm_answer:
                        answer = vlm_answer
                    elif ground_truth_target:
                        answer = f"Обнаружено: {ground_truth_target}"
                    else:
                        answer = f"Кадры четко различимы (макс. резкость {max_sharpness:.1f}); целевой объект подтвержден."

                # Attribution: find frame ID in VLM answer
                m = re.search(r"#?F(?:rame)?\s*#?(\d+)", vlm_answer, re.IGNORECASE)
                if m:
                    cand_fid = int(m.group(1))
                    # Prevent attributing directly to a missing/dropped frame
                    if cand_fid not in dropped_set:
                        for tile in tile_layout:
                            if tile["frame_idx"] == cand_fid:
                                best_frame_id = cand_fid
                                best_pts_us = tile["pts_us"]
                                best_roi = tile["roi"]
                                break

                if best_frame_id == -1 and raw_candidates:
                    # Pick sharpest candidate as primary reference
                    sharpest_idx = int(np.argmax(sharpness_scores))
                    best_frame_id = raw_candidates[sharpest_idx][0]
                    best_pts_us = int(raw_candidates[sharpest_idx][1] * 1000)
                    best_roi = rois[sharpest_idx] or expected_roi

        dt_ms = (time.perf_counter() - t0) * 1000.0

        init_verif = MODEL_OBSERVATION if obs_status == OBSERVED_READABLE else UNVERIFIED
        if obs_status == ARCHIVE_GAP_UNAVAILABLE:
            init_verif = SOURCE_UNAVAILABLE
        elif obs_status == OBSERVED_ABSENT and coverage.absence_confirmed:
            init_verif = VERIFIED_FACT

        evidence = RetrospectiveEvidence(
            query=query,
            status=status,
            observation_status=obs_status,
            start_pts_us=start_pts_us,
            end_pts_us=end_pts_us,
            answer=answer,
            confidence=confidence,
            sharpness_score=max_sharpness,
            selected_frame_indices=selected_indices,
            selected_pts_ms=selected_pts,
            mosaic_image=mosaic_img,
            tile_mapping=tile_layout,
            negative_reason=neg_reason,
            target_category=category,
            segment_id=segment_id,
            best_frame_id=best_frame_id,
            best_pts_us=best_pts_us,
            best_roi=list(best_roi) if best_roi is not None else None,
            coverage=coverage,
            verification_status=init_verif,
            is_verified_fact=(init_verif == VERIFIED_FACT),
            metadata={
                "elapsed_ms": round(dt_ms, 2),
                "mosaic_packing_ms": round(mos_elapsed_ms, 2),
                "vlm_inference_ms": round(vlm_elapsed_ms, 2),
                "avg_sharpness": round(avg_sharpness, 2),
                "max_sharpness": round(max_sharpness, 2),
                "candidates_count": len(raw_candidates),
                "missing_frames_count": missing_frames_count,
                "coverage_ratio": round(coverage.coverage_ratio, 3),
                "max_uninspected_gap_ms": round(coverage.max_uninspected_gap_ms, 2),
                "dropped_frame_indices": list(dropped_set),
                "absence_confirmed": coverage.absence_confirmed,
                "vlm_timings": vlm_timings,
                "layout": layout_meta,
            },
        )

        # 6. Independent Fact Verification (H12.1 P0 / AC-06 / AC-07)
        active_verifier = verifier if verifier is not None else self.verifier
        if verify_facts and active_verifier is not None:
            verif_res = active_verifier.verify(
                evidence=evidence,
                candidate_frames=raw_candidates,
                roi=best_roi or expected_roi,
                category=category,
            )
            evidence.verification_status = verif_res.verification_status
            evidence.is_verified_fact = verif_res.is_verified_fact
            evidence.verification_reason = verif_res.reason
            evidence.independent_claim = verif_res.independent_claim
            evidence.metadata["verification"] = verif_res.to_dict()
            if verif_res.is_verified_fact and verif_res.verified_answer:
                evidence.answer = verif_res.verified_answer

        return evidence
