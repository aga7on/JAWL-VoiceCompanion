"""SceneState: 3-Level Living Cognitive World Representation with Hypothesis-Driven Entity Tracking.

Architecture:
Level 1: Spatial State (30-60 Hz CPU: dirty tiles, motion vectors, spatial coordinates)
Level 2: Entity State (Asynchronous: objects, track_id, appearance Re-ID, actions, confidence, BBox, aliases)
Level 3: Narrative State (Dialogue/speech events, speaker binding, causal links, episodes, visual evidence IDs)

Core principles:
1. Dual-Attention: Reactive (motion/dirty tiles) + Targeted (goal/user-query directed).
2. Hypothesis-Driven Tracking: Track continuity across movements, occlusions, and camera cuts
   without naive premature merging.
3. Semantic Delta: diff(SceneState_t, SceneState_{t-1}) yields concise event updates for LLM/SenseNova.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class EpistemicObservationState:
    """Three explicit states of scene observation for honest cognitive responses.

    Prevents false absence claims ('nothing is there') when a region or entity
    simply has not been actively inspected.
    """
    OBSERVED_PRESENT = "observed_present"  # Entity/attribute positively detected with valid evidence
    OBSERVED_ABSENT = "observed_absent"    # Region/target actively inspected; negative inspection result within bounded scope (not absolute absence proof)
    NOT_OBSERVED = "not_observed"          # Region/entity uninspected, out of FOV, inspection quality low, or observation expired/stale


@dataclasses.dataclass
class SpatialState:
    dirty_ratio: float = 0.0
    dirty_count: int = 0
    motion_vector: list[float] = dataclasses.field(default_factory=lambda: [0.0, 0.0])
    active_bbox: list[float] | None = None
    timestamp_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dirty_ratio": round(self.dirty_ratio, 4),
            "dirty_count": self.dirty_count,
            "motion_vector": [round(v, 2) for v in self.motion_vector],
            "active_bbox": [round(b, 4) for b in self.active_bbox] if self.active_bbox else None,
            "timestamp_ms": round(self.timestamp_ms, 1),
        }


@dataclasses.dataclass
class EntityObservation:
    track_id: str
    type: str = "person"  # "person", "character", "prop", "ui"
    label: str = "сущность"
    bbox: list[float] = dataclasses.field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    state: str = "idle"  # "speaking", "listening", "moving", "idle", "occluded", "lost"
    confidence: float = 1.0
    source: str = "visual_reactive"  # "visual_reactive", "visual_targeted", "reid_hypothesis"
    evidence_id: str = ""
    last_seen_ms: float = 0.0
    expires_at_ms: float = 0.0
    aliases: list[str] = dataclasses.field(default_factory=list)
    appearance_vector: list[float] = dataclasses.field(default_factory=list)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "aliases": list(self.aliases),
            "type": self.type,
            "label": self.label,
            "bbox": [round(b, 4) for b in self.bbox],
            "state": self.state,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "evidence_id": self.evidence_id,
            "last_seen_ms": round(self.last_seen_ms, 1),
            "expires_at_ms": round(self.expires_at_ms, 1),
            "metadata": dict(self.metadata),
        }


@dataclasses.dataclass
class ReIDHypothesis:
    candidate_id: str
    target_track_id: str
    similarity: float
    confidence: float
    status: str = "proposed"  # "proposed", "confirmed", "rejected"
    created_ms: float = 0.0
    resolved_ms: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "target_track_id": self.target_track_id,
            "similarity": round(self.similarity, 4),
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "created_ms": round(self.created_ms, 1),
            "resolved_ms": round(self.resolved_ms, 1) if self.resolved_ms is not None else None,
            "reason": self.reason,
        }


@dataclasses.dataclass
class NarrativeSpeechEvent:
    speaker_track_id: str | None = None
    spatial_track_id: str | None = None
    visual_identity_id: str | None = None
    audio_speaker_id: str | None = None
    is_offscreen: bool = False
    binding_status: str = "unbound"
    confidence: float = 0.85
    source: str = "asr_crossmodal_sync"
    text: str = ""
    start_ms: float = 0.0
    end_ms: float = 0.0
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if self.spatial_track_id is None and self.speaker_track_id is not None:
            self.spatial_track_id = self.speaker_track_id
        elif self.speaker_track_id is None and self.spatial_track_id is not None:
            self.speaker_track_id = self.spatial_track_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_track_id": self.speaker_track_id or self.spatial_track_id,
            "spatial_track_id": self.spatial_track_id,
            "visual_identity_id": self.visual_identity_id,
            "audio_speaker_id": self.audio_speaker_id,
            "is_offscreen": self.is_offscreen,
            "binding_status": self.binding_status,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "text": self.text,
            "start_ms": round(self.start_ms, 1),
            "end_ms": round(self.end_ms, 1),
            "evidence_id": self.evidence_id,
        }


class SceneState:
    """Snapshot and mutating container of the living world representation."""

    def __init__(self, scene_id: str = "scene_0", timestamp_ms: float | None = None) -> None:
        self.scene_id = str(scene_id)
        # A default runtime state uses the monotonic capture clock. Explicit
        # timestamps (including zero) represent an externally advanced timeline.
        self._live_clock = timestamp_ms is None
        self.timestamp_ms = float(timestamp_ms if timestamp_ms is not None else 0.0)
        self.spatial = SpatialState(timestamp_ms=self.timestamp_ms)
        self.entities: dict[str, EntityObservation] = {}
        self.hypotheses: list[ReIDHypothesis] = []
        self.speaker_bindings: dict[str, str] = {}  # visual_identity_id -> audio_speaker_id
        self.active_dialogue: NarrativeSpeechEvent | None = None
        self.narrative_summary: str = ""
        self.unlocalized_presences: list[dict[str, Any]] = []
        self.history_events: list[dict[str, Any]] = []
        self.active_inspections: list[dict[str, Any]] = []
        self.scene_version: int = 0
        self.frame_version: int = 0

    def _observation_now_ms(self) -> float:
        return time.monotonic() * 1000.0 if self._live_clock else self.timestamp_ms

    def advance_frame(self) -> int:
        """Advances the frame counter for localized motion without invalidating the active scene."""
        self.frame_version += 1
        return self.frame_version

    def transition_scene(self, new_scene_id: str) -> None:
        """Transitions scene state to a new scene, bumping version and clearing obsolete ephemeral inspections."""
        self.scene_id = str(new_scene_id)
        self.scene_version += 1
        self.frame_version += 1
        self.active_inspections.clear()
        self.unlocalized_presences.clear()

    def record_inspection(
        self,
        *,
        target: str,
        region: str = "full_frame",
        frame_id: str = "",
        captured_at_ms: float = 0.0,
        expires_at_ms: float = 0.0,
        source: str = "qwen_targeted",
        inspection_quality: float = 0.85,
        verified_absent: bool = True,
        details: str = "",
    ) -> dict[str, Any]:
        """Records a targeted visual inspection with provenance and quality bounds.

        Negative inspection results do not prove absolute absence: they represent
        a bounded negative observation for target in region with inspection_quality.
        """
        observation_time = float(captured_at_ms or self._observation_now_ms())
        record = {
            "target": str(target),
            "region": str(region),
            "inspected_scope": str(region),
            "frame_id": str(frame_id),
            "captured_at_ms": round(observation_time, 1),
            "timestamp_ms": round(observation_time, 1),
            "expires_at_ms": round(float(expires_at_ms or (observation_time + 4000.0)), 1),
            "source": str(source),
            "inspection_quality": round(float(inspection_quality), 3),
            "verified_absent": bool(verified_absent),
            "details": str(details),
        }
        self.active_inspections.append(record)
        if len(self.active_inspections) > 50:
            self.active_inspections.pop(0)
        return record

    def record_unlocalized_presence(
        self,
        *,
        traits: dict[str, Any],
        confidence: float = 0.85,
        evidence_id: str = "",
        timestamp_ms: float = 0.0,
    ) -> dict[str, Any]:
        """Records entity presence detected by VLM without localized BBox coordinates."""
        record = {
            "tag": "person_present_unlocalized",
            "traits": dict(traits),
            "confidence": round(float(confidence), 3),
            "evidence_id": str(evidence_id),
            "timestamp_ms": round(float(timestamp_ms or self._observation_now_ms()), 1),
        }
        self.unlocalized_presences.append(record)
        if len(self.unlocalized_presences) > 50:
            self.unlocalized_presences.pop(0)
        return record

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "timestamp_ms": round(self.timestamp_ms, 1),
            "level_1_spatial": self.spatial.to_dict(),
            "level_2_entities": [e.to_dict() for e in self.entities.values()],
            "unlocalized_presences": list(self.unlocalized_presences),
            "active_inspections": list(self.active_inspections),
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "speaker_bindings": dict(self.speaker_bindings),
            "level_3_narrative": {
                "active_dialogue": self.active_dialogue.to_dict() if self.active_dialogue else None,
                "narrative_summary": self.narrative_summary,
            },
        }

    def evaluate_observation_status(
        self,
        query_target: str,
        *,
        active_inspections: list[dict[str, Any]] | None = None,
        max_staleness_ms: float = 4000.0,
        min_quality_threshold: float = 0.70,
    ) -> dict[str, Any]:
        """Evaluates whether an entity, region, or prop is observed_present, observed_absent, or not_observed.

        Distinguishes:
        - observed_present: known entity or unlocalized presence matches target within max_staleness_ms.
        - observed_absent: an active inspection explicitly covered the target/region with high quality (>=0.70)
          and reported not detecting it. Absence is bounded to that inspection, not absolute.
        - not_observed: no inspection has examined this target/region recently or inspection quality was low;
          presence is UNKNOWN (not absent). Absence of evidence is not evidence of absence.
        """
        clean_target = str(query_target or "").lower().strip()
        now_ms = self._observation_now_ms()

        # 1. Check positive observations in entities and unlocalized_presences
        for ent in self.entities.values():
            if ent.state not in ("lost", "occluded"):
                staleness = now_ms - ent.last_seen_ms
                if 0.0 <= staleness <= max_staleness_ms:
                    ent_str = f"{ent.label} {' '.join(ent.aliases)} {json.dumps(ent.metadata, ensure_ascii=False)}".lower()
                    if clean_target in ent_str or any(clean_target in a.lower() for a in ent.aliases):
                        return {
                            "status": EpistemicObservationState.OBSERVED_PRESENT,
                            "target": query_target,
                            "evidence": ent.to_dict(),
                            "freshness_ms": round(staleness, 1),
                            "reason": f"Active entity {ent.track_id} positively detected",
                        }

        for unloc in self.unlocalized_presences:
            staleness = now_ms - float(unloc.get("timestamp_ms", 0.0))
            if 0.0 <= staleness <= max_staleness_ms:
                unloc_str = json.dumps(unloc.get("traits", {}), ensure_ascii=False).lower()
                if clean_target in unloc_str:
                    return {
                        "status": EpistemicObservationState.OBSERVED_PRESENT,
                        "target": query_target,
                        "evidence": unloc,
                        "freshness_ms": round(staleness, 1),
                        "reason": f"Unlocalized presence {unloc.get('evidence_id')} positively detected",
                    }

        # 2. Check if an active inspection explicitly checked this target/region
        inspections = active_inspections if active_inspections is not None else self.active_inspections
        if inspections:
            for insp in inspections:
                scope = str(insp.get("inspected_scope") or insp.get("region") or "").lower()
                target_str = str(insp.get("target") or "").lower()
                is_absent = bool(insp.get("verified_absent", False))
                quality = float(insp.get("inspection_quality", 0.85))
                insp_time = float(insp.get("captured_at_ms") or insp.get("timestamp_ms") or 0.0)
                expires_at = float(insp.get("expires_at_ms") or (insp_time + max_staleness_ms))

                if 0.0 <= (now_ms - insp_time) <= max_staleness_ms and now_ms <= expires_at:
                    if clean_target in target_str or target_str in clean_target or clean_target in scope or scope in clean_target:
                        if is_absent:
                            # CRITICAL: If inspection quality is low (< min_quality_threshold), do NOT claim observed_absent!
                            if quality < min_quality_threshold:
                                return {
                                    "status": EpistemicObservationState.NOT_OBSERVED,
                                    "target": query_target,
                                    "reason": f"Inspection quality ({quality:.2f}) too low to infer absence in '{scope}'; visual state remains unknown",
                                    "needs_visual_refresh": True,
                                    "bounded_inspection": insp,
                                }
                            return {
                                "status": EpistemicObservationState.OBSERVED_ABSENT,
                                "target": query_target,
                                "inspection": insp,
                                "freshness_ms": round(now_ms - insp_time, 1),
                                "inspection_quality": quality,
                                "bounded_scope": scope,
                                "reason": f"Target was actively inspected in '{scope}' and not detected (bounded quality: {quality:.2f}, not absolute absence)",
                            }

        # 3. Default: Not observed! (Absence of evidence != evidence of absence)
        return {
            "status": EpistemicObservationState.NOT_OBSERVED,
            "target": query_target,
            "reason": "Target has not been actively inspected in current window; visual state unknown",
            "needs_visual_refresh": True,
        }

    def compute_semantic_diff(self, prev_state: Optional[SceneState]) -> dict[str, Any]:
        """Calculates semantic delta for LLM event notification (Language-Out-of-the-Loop)."""
        if prev_state is None:
            return {
                "has_change": True,
                "type": "scene_init",
                "summary": f"Инициализация сцены {self.scene_id}",
                "entities_added": list(self.entities.keys()),
                "entities_modified": [],
                "entities_lost": [],
                "unlocalized_presences": list(self.unlocalized_presences),
                "speech_event": self.active_dialogue.to_dict() if self.active_dialogue else None,
            }

        added = [k for k in self.entities if k not in prev_state.entities]
        lost = [k for k, v in self.entities.items() if v.state in ("lost", "occluded") and prev_state.entities.get(k, None) and prev_state.entities[k].state not in ("lost", "occluded")]
        
        # New unlocalized presences
        new_unloc = [
            u for u in self.unlocalized_presences
            if not any(
                pu.get("evidence_id") == u.get("evidence_id") and pu.get("tag") == u.get("tag")
                for pu in prev_state.unlocalized_presences
            )
        ]
        
        modified = []
        for k, curr_ent in self.entities.items():
            if k in prev_state.entities:
                prev_ent = prev_state.entities[k]
                if curr_ent.state != prev_ent.state:
                    modified.append({
                        "track_id": k,
                        "change": f"state: {prev_ent.state} -> {curr_ent.state}",
                        "label": curr_ent.label,
                    })
                # Check significant spatial movement (> 15% screen shift)
                cy_prev = (prev_ent.bbox[0] + prev_ent.bbox[2]) / 2.0
                cx_prev = (prev_ent.bbox[1] + prev_ent.bbox[3]) / 2.0
                cy_curr = (curr_ent.bbox[0] + curr_ent.bbox[2]) / 2.0
                cx_curr = (curr_ent.bbox[1] + curr_ent.bbox[3]) / 2.0
                dist = math.hypot(cy_curr - cy_prev, cx_curr - cx_prev)
                if dist > 0.15:
                    modified.append({
                        "track_id": k,
                        "change": f"movement: delta={dist:.2f}",
                        "from_pos": [round(cy_prev, 2), round(cx_prev, 2)],
                        "to_pos": [round(cy_curr, 2), round(cx_curr, 2)],
                    })

        new_speech = None
        if self.active_dialogue and (
            not prev_state.active_dialogue 
            or self.active_dialogue.start_ms != prev_state.active_dialogue.start_ms
        ):
            new_speech = self.active_dialogue.to_dict()

        has_change = bool(added or lost or modified or new_speech or new_unloc)
        return {
            "has_change": has_change,
            "type": "state_update",
            "entities_added": added,
            "entities_modified": modified,
            "entities_lost": lost,
            "unlocalized_presences": new_unloc,
            "speech_event": new_speech,
            "active_hypotheses": [h.to_dict() for h in self.hypotheses if h.status == "proposed"],
        }


class HypothesisDrivenEntityTracker:
    """Manages temporal persistence, candidate hypotheses, and Re-ID continuity."""

    def __init__(
        self,
        *,
        iou_match_threshold: float = 0.35,
        reid_hypothesis_threshold: float = 0.70,
        reid_confirm_threshold: float = 0.85,
        track_retention_sec: float = 10.0,
        appearance_dim: int = 48,
    ) -> None:
        self.iou_match_threshold = max(0.1, min(0.9, float(iou_match_threshold)))
        self.reid_hypothesis_threshold = max(0.4, min(0.95, float(reid_hypothesis_threshold)))
        self.reid_confirm_threshold = max(0.6, min(0.99, float(reid_confirm_threshold)))
        self.track_retention_ms = max(1.0, float(track_retention_sec)) * 1000.0
        self.appearance_dim = appearance_dim

        self.current_state = SceneState(timestamp_ms=0.0)
        self.prev_state: Optional[SceneState] = None
        self._next_entity_id = 1
        self._next_candidate_id = 1
        self._hypotheses_history: list[ReIDHypothesis] = []

    def _extract_appearance_feature(self, crop_np: np.ndarray) -> list[float]:
        """Fast morphology & color distribution embedding for appearance matching."""
        if crop_np is None or crop_np.size == 0:
            return [0.0] * self.appearance_dim

        h, w = crop_np.shape[:2]
        if h < 4 or w < 4:
            return [0.0] * self.appearance_dim

        # 1. 3-channel color means and stds (6 dims)
        means = crop_np.mean(axis=(0, 1)) / 255.0
        stds = crop_np.std(axis=(0, 1)) / 255.0

        # 2. 3x3 spatial quadrant color means (27 dims)
        qh = max(1, h // 3)
        qw = max(1, w // 3)
        quad_feats = []
        for r in range(3):
            for c in range(3):
                cell = crop_np[r * qh : (r + 1) * qh, c * qw : (c + 1) * qw]
                if cell.size > 0:
                    quad_feats.extend((cell.mean(axis=(0, 1)) / 255.0).tolist())
                else:
                    quad_feats.extend([0.0, 0.0, 0.0])

        # 3. Opponent chromatic ratios & aspect ratio (15 dims)
        aspect = float(h) / float(w) if w > 0 else 1.0
        r_mean, g_mean, b_mean = means[:3] if len(means) >= 3 else (0.5, 0.5, 0.5)
        rg = r_mean - g_mean
        by = b_mean - (r_mean + g_mean) * 0.5

        raw_vec = np.array(
            means.tolist() + stds.tolist() + quad_feats[:27] + [aspect, rg, by],
            dtype=np.float32,
        )
        if len(raw_vec) < self.appearance_dim:
            raw_vec = np.pad(raw_vec, (0, self.appearance_dim - len(raw_vec)))
        else:
            raw_vec = raw_vec[: self.appearance_dim]

        norm = np.linalg.norm(raw_vec) + 1e-6
        return (raw_vec / norm).tolist()

    @staticmethod
    def _compute_iou(b1: list[float], b2: list[float]) -> float:
        """Computes Intersection over Union of two normalized bboxes [ymin, xmin, ymax, xmax]."""
        y1 = max(b1[0], b2[0])
        x1 = max(b1[1], b2[1])
        y2 = min(b1[2], b2[2])
        x2 = min(b1[3], b2[3])

        inter_h = max(0.0, y2 - y1)
        inter_w = max(0.0, x2 - x1)
        inter_area = inter_h * inter_w
        if inter_area <= 0.0:
            return 0.0

        area1 = max(1e-6, (b1[2] - b1[0]) * (b1[3] - b1[1]))
        area2 = max(1e-6, (b2[2] - b2[0]) * (b2[3] - b2[1]))
        union = area1 + area2 - inter_area
        return inter_area / union if union > 0 else 0.0

    @staticmethod
    def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        a1 = np.array(v1, dtype=np.float32)
        a2 = np.array(v2, dtype=np.float32)
        dot = float(np.dot(a1, a2))
        norm1 = float(np.linalg.norm(a1))
        norm2 = float(np.linalg.norm(a2))
        return dot / (norm1 * norm2 + 1e-6)

    def update_frame(
        self,
        frame_np: np.ndarray,
        *,
        timestamp_ms: float,
        detected_boxes: list[dict[str, Any]],  # [{"bbox": [ymin, xmin, ymax, xmax], "label": str, "conf": float}]
        spatial_delta_bbox: list[float] | None = None,
        dirty_ratio: float = 0.0,
        dirty_count: int = 0,
        active_speech: NarrativeSpeechEvent | None = None,
    ) -> SceneState:
        """Processes one visual observation tick and updates SceneState."""
        self.prev_state = copy.deepcopy(self.current_state)
        self.current_state.timestamp_ms = timestamp_ms

        # 1. Update Level 1: Spatial State
        self.current_state.spatial = SpatialState(
            dirty_ratio=dirty_ratio,
            dirty_count=dirty_count,
            active_bbox=spatial_delta_bbox,
            timestamp_ms=timestamp_ms,
        )

        h, w = frame_np.shape[:2]
        unmatched_detections = list(detected_boxes)
        matched_tracks = set()

        # 2. Level 2: Short-term spatial matching for existing active entities
        for track_id, entity in list(self.current_state.entities.items()):
            best_iou = 0.0
            best_idx = -1
            for idx, det in enumerate(unmatched_detections):
                iou = self._compute_iou(entity.bbox, det["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_idx = idx

            if best_iou >= self.iou_match_threshold and best_idx >= 0:
                det = unmatched_detections.pop(best_idx)
                # Crop appearance
                ymin_px = max(0, int(det["bbox"][0] * h))
                xmin_px = max(0, int(det["bbox"][1] * w))
                ymax_px = min(h, int(det["bbox"][2] * h))
                xmax_px = min(w, int(det["bbox"][3] * w))
                crop = frame_np[ymin_px:ymax_px, xmin_px:xmax_px]
                app_vec = self._extract_appearance_feature(crop)

                # Smoothly update entity
                entity.bbox = det["bbox"]
                entity.confidence = det.get("conf", entity.confidence)
                entity.last_seen_ms = timestamp_ms
                entity.expires_at_ms = timestamp_ms + self.track_retention_ms
                entity.state = det.get(
                    "state",
                    "speaking" if (active_speech and active_speech.speaker_track_id == track_id) else "moving" if best_iou < 0.85 else "idle"
                )
                if app_vec and any(app_vec):
                    entity.appearance_vector = app_vec
                matched_tracks.add(track_id)
            else:
                # Entity not detected in this frame
                if entity.state != "lost":
                    entity.state = "occluded" if (timestamp_ms - entity.last_seen_ms < 2000.0) else "lost"
                if timestamp_ms > entity.expires_at_ms:
                    entity.state = "lost"

        # 3. Level 2: Hypothesis-Driven Re-ID for new/unmatched detections
        for det in unmatched_detections:
            ymin_px = max(0, int(det["bbox"][0] * h))
            xmin_px = max(0, int(det["bbox"][1] * w))
            ymax_px = min(h, int(det["bbox"][2] * h))
            xmax_px = min(w, int(det["bbox"][3] * w))
            crop = frame_np[ymin_px:ymax_px, xmin_px:xmax_px]
            cand_app = self._extract_appearance_feature(crop)

            # Evaluate against occluded / lost / existing entities
            best_sim = 0.0
            best_target_id = None

            for track_id, entity in self.current_state.entities.items():
                if track_id in matched_tracks:
                    continue  # Entity already occupied on this frame
                sim = self._cosine_similarity(cand_app, entity.appearance_vector)
                if sim > best_sim:
                    best_sim = sim
                    best_target_id = track_id

            if best_target_id and best_sim >= self.reid_confirm_threshold:
                # Strong match -> Confirm Re-ID immediately
                target = self.current_state.entities[best_target_id]
                cand_alias = f"cand_{self._next_candidate_id}"
                self._next_candidate_id += 1
                target.aliases.append(cand_alias)
                target.bbox = det["bbox"]
                target.state = "idle"
                target.last_seen_ms = timestamp_ms
                target.expires_at_ms = timestamp_ms + self.track_retention_ms
                target.appearance_vector = cand_app
                matched_tracks.add(best_target_id)

                hyp = ReIDHypothesis(
                    candidate_id=cand_alias,
                    target_track_id=best_target_id,
                    similarity=best_sim,
                    confidence=0.92,
                    status="confirmed",
                    created_ms=timestamp_ms,
                    resolved_ms=timestamp_ms,
                    reason=f"Strong appearance match (cosine={best_sim:.3f}) across shot/occlusion",
                )
                self.current_state.hypotheses.append(hyp)
                self._hypotheses_history.append(hyp)

            elif best_target_id and best_sim >= self.reid_hypothesis_threshold:
                # Moderate match -> Create tentative candidate and register Hypothesis
                cand_id = f"person_{self._next_entity_id}"
                self._next_entity_id += 1
                cand_ent = EntityObservation(
                    track_id=cand_id,
                    type=det.get("type", "person"),
                    label=det.get("label", "персонаж"),
                    bbox=det["bbox"],
                    state="idle",
                    confidence=det.get("conf", 0.75),
                    source="reid_hypothesis",
                    last_seen_ms=timestamp_ms,
                    expires_at_ms=timestamp_ms + self.track_retention_ms,
                    appearance_vector=cand_app,
                )
                self.current_state.entities[cand_id] = cand_ent
                matched_tracks.add(cand_id)

                hyp = ReIDHypothesis(
                    candidate_id=cand_id,
                    target_track_id=best_target_id,
                    similarity=best_sim,
                    confidence=0.72,
                    status="proposed",
                    created_ms=timestamp_ms,
                    reason=f"Tentative candidate (cosine={best_sim:.3f}); keeping distinct until semantic confirmation",
                )
                self.current_state.hypotheses.append(hyp)
                self._hypotheses_history.append(hyp)
            else:
                # Brand new entity
                new_id = f"person_{self._next_entity_id}"
                self._next_entity_id += 1
                new_ent = EntityObservation(
                    track_id=new_id,
                    type=det.get("type", "person"),
                    label=det.get("label", "персонаж"),
                    bbox=det["bbox"],
                    state="idle",
                    confidence=det.get("conf", 0.90),
                    source="visual_reactive",
                    last_seen_ms=timestamp_ms,
                    expires_at_ms=timestamp_ms + self.track_retention_ms,
                    appearance_vector=cand_app,
                )
                self.current_state.entities[new_id] = new_ent
                matched_tracks.add(new_id)

        # 4. Level 3: Narrative State & Active Speaker Binding (Decoupled 3 Identities)
        if active_speech:
            self.current_state.active_dialogue = active_speech

            if active_speech.is_offscreen:
                # Offscreen speech: never greedily assign to visible listeners
                active_speech.spatial_track_id = None
                active_speech.speaker_track_id = None
                if active_speech.binding_status == "unbound":
                    active_speech.binding_status = "unbound_offscreen"
            else:
                # Onscreen candidate evaluation
                speaking_entities = [
                    (tid, ent)
                    for tid, ent in self.current_state.entities.items()
                    if ent.type == "person" and ent.state == "speaking"
                ]

                if len(speaking_entities) == 1:
                    tid, ent = speaking_entities[0]
                    active_speech.spatial_track_id = tid
                    active_speech.speaker_track_id = tid
                    if active_speech.visual_identity_id is None and ent.metadata.get("character_id"):
                        active_speech.visual_identity_id = ent.metadata["character_id"]
                    active_speech.binding_status = "active_speaker_present"
                elif len(speaking_entities) > 1:
                    # Ambiguous: multiple entities simultaneously speaking -> abstain
                    active_speech.spatial_track_id = None
                    active_speech.speaker_track_id = None
                    active_speech.binding_status = "ambiguous_multiple_speakers"
                else:
                    # No entity explicitly in 'speaking' state
                    if active_speech.speaker_track_id or active_speech.spatial_track_id:
                        tid = active_speech.spatial_track_id or active_speech.speaker_track_id
                        if tid in self.current_state.entities:
                            self.current_state.entities[tid].state = "speaking"
                            if active_speech.binding_status == "unbound":
                                active_speech.binding_status = "confirmed_present_idle_lips"
                    else:
                        # Solitary idle entity check (for unit tests / clean single-actor shots)
                        idle_entities = [
                            (tid, ent)
                            for tid, ent in self.current_state.entities.items()
                            if ent.type == "person" and ent.state == "idle"
                        ]
                        if len(idle_entities) == 1 and not active_speech.is_offscreen:
                            tid, ent = idle_entities[0]
                            active_speech.spatial_track_id = tid
                            active_speech.speaker_track_id = tid
                            ent.state = "speaking"
                            active_speech.binding_status = "active_speaker_present"
                        else:
                            active_speech.binding_status = "unbound" if not active_speech.is_offscreen else "unbound_offscreen"
        else:
            self.current_state.active_dialogue = None

        return copy.deepcopy(self.current_state)

    def query_attention(
        self,
        frame_np: np.ndarray,
        target_bbox: list[float],
        label: str = "целевой_объект",
        *,
        timestamp_ms: float,
    ) -> EntityObservation:
        """Targeted / Top-Down Attention: inspects static or query-directed region regardless of motion."""
        h, w = frame_np.shape[:2]
        ymin_px = max(0, int(target_bbox[0] * h))
        xmin_px = max(0, int(target_bbox[1] * w))
        ymax_px = min(h, int(target_bbox[2] * h))
        xmax_px = min(w, int(target_bbox[3] * w))
        crop = frame_np[ymin_px:ymax_px, xmin_px:xmax_px]
        app_vec = self._extract_appearance_feature(crop)

        tid = f"targeted_{label}_{self._next_entity_id}"
        self._next_entity_id += 1
        obs = EntityObservation(
            track_id=tid,
            type="prop",
            label=label,
            bbox=target_bbox,
            state="idle",
            confidence=0.95,
            source="visual_targeted",
            last_seen_ms=timestamp_ms,
            expires_at_ms=timestamp_ms + self.track_retention_ms * 2,
            appearance_vector=app_vec,
        )
        self.current_state.entities[tid] = obs
        return obs

    def record_unlocalized_presence(
        self,
        *,
        traits: dict[str, Any],
        confidence: float = 0.85,
        evidence_id: str = "",
        timestamp_ms: float = 0.0,
    ) -> dict[str, Any]:
        """Records person presence detected by VLM without localized BBox coordinates.

        Prevents corrupting spatial tracking while informing narrative cognition that a character
        is present (person_present_unlocalized).
        """
        record = {
            "tag": "person_present_unlocalized",
            "traits": dict(traits),
            "confidence": round(float(confidence), 3),
            "evidence_id": str(evidence_id),
            "timestamp_ms": round(float(timestamp_ms), 1),
        }
        self.current_state.unlocalized_presences.append(record)
        return record

    @staticmethod
    def check_semantic_contradiction(
        traits_a: dict[str, Any],
        traits_b: dict[str, Any],
    ) -> tuple[bool, str]:
        """Evaluates whether two sets of semantic traits constitute a hard contradiction.

        Distinguishes:
        1. Hard contradiction (veto):
           - Conflicting gender (e.g. 'парень'/'male' vs 'девушка'/'female')
           - Mutually exclusive attire (e.g. 'курьерская куртка' vs 'школьная форма')
           - Conflicting hair color (e.g. 'блондинка' vs 'темные/черные волосы')
        2. Incomplete observation (no veto):
           - Glasses observed in A, but absent/not mentioned in B (might be profile angle or occluded)
           - Lighting/shadow shift
        """
        str_a = str(traits_a).lower()
        str_b = str(traits_b).lower()

        # 1. Gender check
        g_a = traits_a.get("gender") or ("male" if any(w in str_a for w in ["парень", "муж"]) else "female" if any(w in str_a for w in ["девушк", "женщ"]) else None)
        g_b = traits_b.get("gender") or ("male" if any(w in str_b for w in ["парень", "муж"]) else "female" if any(w in str_b for w in ["девушк", "женщ"]) else None)
        if g_a and g_b and g_a != g_b:
            return True, f"Hard contradiction: gender mismatch ({g_a} vs {g_b})"

        # 2. Attire / Role check
        role_a = traits_a.get("role") or ("courier" if any(w in str_a for w in ["курьер", "кепка", "куртка"]) else "student" if any(w in str_a for w in ["школьн", "форма"]) else None)
        role_b = traits_b.get("role") or ("courier" if any(w in str_b for w in ["курьер", "кепка", "куртка"]) else "student" if any(w in str_b for w in ["школьн", "форма"]) else None)
        if role_a and role_b and role_a != role_b:
            return True, f"Hard contradiction: distinct attire/role ({role_a} vs {role_b})"

        # 3. Distinct hair colors
        hair_a = "blonde" if any(w in str_a for w in ["блондин", "светл"]) else "dark" if any(w in str_a for w in ["темн", "черн", "брюнет"]) else None
        hair_b = "blonde" if any(w in str_b for w in ["блондин", "светл"]) else "dark" if any(w in str_b for w in ["темн", "черн", "брюнет"]) else None
        if hair_a and hair_b and hair_a != hair_b:
            return True, f"Hard contradiction: hair color mismatch ({hair_a} vs {hair_b})"

        # Incomplete observation: glasses or hair style differences alone do NOT trigger hard veto
        return False, "Compatible or incomplete observation"

    def apply_async_vlm_evidence(
        self,
        *,
        vlm_characters: list[dict[str, Any]],
        frame_timestamp_ms: float,
        current_timestamp_ms: float,
        evidence_id: str = "",
    ) -> dict[str, Any]:
        """Applies asynchronous VLM observations adhering to strict temporal causality.

        Rule: A late VLM result (frame_timestamp_ms < current_timestamp_ms) MUST NOT
        overwrite current spatial coordinates (bbox) of active entities.
        It can enrich character traits/labels, validate Re-ID hypotheses, or register unlocalized presence.
        """
        applied_enrichments = []
        unlocalized_added = []
        is_stale = frame_timestamp_ms < (current_timestamp_ms - 200.0)

        for v_char in vlm_characters:
            app_text = v_char.get("appearance", "")
            action_text = v_char.get("action", "")
            raw_bbox = v_char.get("bbox")

            # Check if this matches an existing entity by spatial overlap
            matched_ent = None
            if not is_stale and raw_bbox and len(raw_bbox) == 4:
                for ent in self.current_state.entities.values():
                    if ent.state != "lost" and self._compute_iou(ent.bbox, raw_bbox) >= 0.3:
                        matched_ent = ent
                        break

            if matched_ent:
                # Enrich entity traits without changing its real-time bbox
                matched_ent.metadata["vlm_appearance"] = app_text
                matched_ent.metadata["vlm_action"] = action_text
                matched_ent.metadata["vlm_evidence_id"] = evidence_id
                applied_enrichments.append({"track_id": matched_ent.track_id, "enriched": True})
            else:
                # Do NOT create a pseudo-spatial BBox with inaccurate coordinates!
                # Instead, record as unlocalized presence evidence
                traits = {
                    "appearance": app_text,
                    "action": action_text,
                    "raw_vlm_bbox": raw_bbox,
                }
                unloc = self.record_unlocalized_presence(
                    traits=traits,
                    confidence=v_char.get("confidence", 0.85),
                    evidence_id=evidence_id,
                    timestamp_ms=frame_timestamp_ms,
                )
                unlocalized_added.append(unloc)

        return {
            "is_stale": is_stale,
            "applied_enrichments": applied_enrichments,
            "unlocalized_added": unlocalized_added,
        }
