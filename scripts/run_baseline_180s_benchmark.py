"""Replays the exact Round 9 baseline pipeline on the 180s benchmark frames and speech.

Inputs:
  - Ground truth definition: runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json
  - Extracted 2 FPS frames: runtime/instances/daily/data/sensory/youtube_watch/gt_frames_180s/frame_%04d.jpg

Outputs:
  - runtime/instances/daily/data/sensory/youtube_watch/baseline_predictions_180s.json
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from PIL import Image

from jawl_voicecompanion.scene_state import (
    HypothesisDrivenEntityTracker,
    NarrativeSpeechEvent,
)
from jawl_voicecompanion.visual_stream import IncrementalSpatialMatrix, SceneDeltaDetector


def run_baseline_180s():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    frames_dir = Path("runtime/instances/daily/data/sensory/youtube_watch/gt_frames_180s")
    out_path = Path("runtime/instances/daily/data/sensory/youtube_watch/baseline_predictions_180s.json")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    speech_turns = gt_data["speech_events"]
    speech_queue = list(speech_turns)

    # Initialize exact Round 9 components
    spatial_matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64, keyframe_interval=60)
    delta_detector = SceneDeltaDetector(grid_size=64, change_threshold=0.08)
    tracker = HypothesisDrivenEntityTracker(
        iou_match_threshold=0.35,
        reid_hypothesis_threshold=0.70,
        reid_confirm_threshold=0.85,
        track_retention_sec=10.0,
    )

    frame_predictions = []
    attributed_speech = []

    print("Replaying Round 9 baseline across 360 frames (0.0s - 180.0s)...")
    for f_idx in range(1, 361):
        t_sec = round(f_idx * 0.5, 2)
        frame_file = frames_dir / f"frame_{f_idx:04d}.jpg"
        if not frame_file.exists():
            continue

        img = Image.open(frame_file).convert("RGB")
        frame_np = np.array(img, dtype=np.uint8)

        # 1. Level 1 Spatial Matrix Update (Round 9 logic)
        matrix_changed, dirty_count, matrix_bbox = spatial_matrix.update(frame_np, commit=True)
        delta, changed, sid = delta_detector.compute_delta(frame_np, commit=True)

        # 2. Level 2 Motion/Dirty-Tile BBox heuristic
        det_boxes = []
        if matrix_bbox is not None and dirty_count >= 4:
            det_boxes.append({
                "bbox": matrix_bbox,
                "label": "персонаж" if (matrix_bbox[2] - matrix_bbox[0]) > 0.12 else "деталь",
                "conf": 0.88,
            })

        # 3. Check if any speech turn is active at this timestamp
        active_sp = None
        for sp in speech_queue:
            if sp["start_sec"] <= t_sec <= sp["end_sec"]:
                active_sp = NarrativeSpeechEvent(
                    text=sp["text"],
                    start_ms=sp["start_sec"] * 1000.0,
                    end_ms=sp["end_sec"] * 1000.0,
                )
                break

        # 4. Level 2 & 3 Tracker update
        scene_state = tracker.update_frame(
            frame_np,
            timestamp_ms=t_sec * 1000.0,
            detected_boxes=det_boxes,
            spatial_delta_bbox=matrix_bbox,
            dirty_ratio=dirty_count / 630.0,
            dirty_count=dirty_count,
            active_speech=active_sp,
        )

        # If active dialogue was processed and attributed, record attribution
        if scene_state.active_dialogue and scene_state.active_dialogue.speaker_track_id:
            # Check if this speech turn was already attributed
            cur_turn_id = None
            for sp in speech_turns:
                if sp["start_sec"] <= t_sec <= sp["end_sec"]:
                    cur_turn_id = sp["turn_id"]
                    break
            if cur_turn_id is not None and not any(a["turn_id"] == cur_turn_id for a in attributed_speech):
                attributed_speech.append({
                    "turn_id": cur_turn_id,
                    "timestamp_sec": t_sec,
                    "attributed_speaker_track_id": scene_state.active_dialogue.speaker_track_id,
                })

        # Record predicted entities in this frame
        active_in_frame = []
        for tid, ent in scene_state.entities.items():
            if ent.state in ("idle", "speaking", "moving"):
                active_in_frame.append({
                    "track_id": tid,
                    "label": ent.label,
                    "bbox": ent.bbox,
                    "state": ent.state,
                    "confidence": ent.confidence,
                })

        frame_predictions.append({
            "frame_idx": f_idx,
            "timestamp_sec": t_sec,
            "dirty_count": dirty_count,
            "matrix_bbox": matrix_bbox,
            "predicted_entities": active_in_frame,
            "active_hypotheses": [h.to_dict() for h in scene_state.hypotheses],
        })

    # Summary of hypotheses
    hyp_history = [h.to_dict() for h in tracker._hypotheses_history]
    active_summary = {
        tid: {
            "track_id": e.track_id,
            "aliases": e.aliases,
            "last_seen_ms": e.last_seen_ms,
        }
        for tid, e in tracker.current_state.entities.items()
    }

    out_data = {
        "pipeline_version": "Round 9 Baseline (dirty-tile BBox + 48-dim color Re-ID + greedy speaker binding)",
        "duration_sec": 180.0,
        "total_frames_evaluated": len(frame_predictions),
        "total_hypotheses": len(hyp_history),
        "confirmed_hypotheses": sum(1 for h in hyp_history if h["status"] == "confirmed"),
        "proposed_hypotheses": sum(1 for h in hyp_history if h["status"] == "proposed"),
        "attributed_speech_turns": attributed_speech,
        "frame_predictions": frame_predictions,
        "hypotheses_log": hyp_history,
        "entities_summary": active_summary,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"Baseline predictions saved to: {out_path}")
    print(f"Total hypotheses: {len(hyp_history)} (Confirmed: {out_data['confirmed_hypotheses']}, Proposed: {out_data['proposed_hypotheses']})")
    print(f"Attributed dialogue turns: {len(attributed_speech)} / {len(speech_turns)}")


if __name__ == "__main__":
    run_baseline_180s()
