"""Step 2.1 Person Detector Benchmark.

Evaluates torchvision SSDLite320 MobileNetV3 (person class, COCO label=1)
across all 360 benchmark frames of the 180s episode segment.

Measures:
  1. CPU Latency: p50, p95, mean (ms)
  2. Detection Performance: Precision, Recall, F1, Mean IoU (IoU >= 0.30 and IoU >= 0.50)
  3. Static vs Moving Character Recall:
     - Recall on frames where characters are "idle" / "speaking"
     - vs Recall on frames where characters are "moving"
  4. Integration with SceneState Tracker:
     - Replays the tracker with SSDLite detections instead of dirty-tile bbox
     - Keeps Re-ID (48-dim) and Speaker Binding unchanged
     - Evaluates impact on IDF1, ID Switches, and Speaker Attribution

Saves:
  runtime/instances/daily/data/sensory/youtube_watch/step21_ssdlite_predictions.json
  runtime/instances/daily/data/sensory/youtube_watch/step21_ssdlite_metrics.json
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import torch
import torchvision.models.detection as d
from PIL import Image
import torchvision.transforms.functional as TF

from jawl_voicecompanion.scene_state import (
    HypothesisDrivenEntityTracker,
    NarrativeSpeechEvent,
)
from jawl_voicecompanion.visual_stream import IncrementalSpatialMatrix, SceneDeltaDetector


def compute_iou(b1: list[float], b2: list[float]) -> float:
    # Normalized bbox: [ymin, xmin, ymax, xmax]
    y1 = max(b1[0], b2[0])
    x1 = max(b1[1], b2[1])
    y2 = min(b1[2], b2[2])
    x2 = min(b1[3], b2[3])

    inter_h = max(0.0, y2 - y1)
    inter_w = max(0.0, x2 - x1)
    inter_area = inter_h * inter_w
    if inter_area <= 0.0:
        return 0.0

    area1 = max(0.0, b1[2] - b1[0]) * max(0.0, b1[3] - b1[1])
    area2 = max(0.0, b2[2] - b2[0]) * max(0.0, b2[3] - b2[1])
    denom = area1 + area2 - inter_area
    return inter_area / denom if denom > 0.0 else 0.0


def solve_max_weight_bipartite(cost_matrix: np.ndarray) -> list[tuple[int, int]]:
    pairs = []
    matrix = cost_matrix.copy()
    for _ in range(min(matrix.shape)):
        r, c = np.unravel_index(np.argmax(matrix), matrix.shape)
        if matrix[r, c] <= 0:
            break
        pairs.append((int(r), int(c)))
        matrix[r, :] = -1
        matrix[:, c] = -1
    return pairs


def run_ssdlite_benchmark(conf_threshold: float = 0.20):
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    frames_dir = Path("runtime/instances/daily/data/sensory/youtube_watch/gt_frames_180s")
    out_preds_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step21_ssdlite_predictions.json")
    out_metrics_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step21_ssdlite_metrics.json")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    # 1. Load SSDLite model
    print("Loading SSDLite320 MobileNetV3 Large...")
    model = d.ssdlite320_mobilenet_v3_large(weights=d.SSDLite320_MobileNet_V3_Large_Weights.DEFAULT).eval()

    # Tracker & Stream components
    spatial_matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64, keyframe_interval=60)
    delta_detector = SceneDeltaDetector(grid_size=64, change_threshold=0.08)
    tracker = HypothesisDrivenEntityTracker(
        iou_match_threshold=0.35,
        reid_hypothesis_threshold=0.70,
        reid_confirm_threshold=0.85,
        track_retention_sec=10.0,
    )

    speech_turns = gt_data["speech_events"]
    latencies = []
    raw_detections = []
    frame_predictions = []
    attributed_speech = []

    print(f"Running SSDLite inference across 360 frames (conf >= {conf_threshold})...")
    for f_idx in range(1, 361):
        t_sec = round(f_idx * 0.5, 2)
        frame_file = frames_dir / f"frame_{f_idx:04d}.jpg"
        if not frame_file.exists():
            continue

        img = Image.open(frame_file).convert("RGB")
        frame_np = np.array(img, dtype=np.uint8)
        h, w = frame_np.shape[:2]

        # SSDLite inference + Latency timing
        tensor = TF.to_tensor(img).unsqueeze(0)
        t0 = time.perf_counter()
        with torch.no_grad():
            preds = model(tensor)[0]
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt_ms)

        boxes = preds["boxes"].numpy()
        labels = preds["labels"].numpy()
        scores = preds["scores"].numpy()

        det_boxes = []
        frame_raw_dets = []
        for b, l, s in zip(boxes, labels, scores):
            if l == 1 and s >= conf_threshold:  # COCO person = 1
                ymin = float(b[1] / h)
                xmin = float(b[0] / w)
                ymax = float(b[3] / h)
                xmax = float(b[2] / w)
                norm_bbox = [round(ymin, 4), round(xmin, 4), round(ymax, 4), round(xmax, 4)]
                det_boxes.append({
                    "bbox": norm_bbox,
                    "label": "персонаж",
                    "conf": float(round(s, 3)),
                })
                frame_raw_dets.append({
                    "bbox": norm_bbox,
                    "conf": float(round(s, 3)),
                })

        raw_detections.append({
            "frame_idx": f_idx,
            "timestamp_sec": t_sec,
            "latency_ms": round(dt_ms, 2),
            "detections": frame_raw_dets,
        })

        # Matrix update (Level 1 remains active)
        matrix_changed, dirty_count, matrix_bbox = spatial_matrix.update(frame_np, commit=True)
        delta, changed, sid = delta_detector.compute_delta(frame_np, commit=True)

        # Check speech turn
        active_sp = None
        for sp in speech_turns:
            if sp["start_sec"] <= t_sec <= sp["end_sec"]:
                active_sp = NarrativeSpeechEvent(
                    text=sp["text"],
                    start_ms=sp["start_sec"] * 1000.0,
                    end_ms=sp["end_sec"] * 1000.0,
                )
                break

        # Level 2 Tracker Update with SSDLite detected boxes!
        scene_state = tracker.update_frame(
            frame_np,
            timestamp_ms=t_sec * 1000.0,
            detected_boxes=det_boxes,  # Real person detections!
            spatial_delta_bbox=matrix_bbox,
            dirty_ratio=dirty_count / 630.0,
            dirty_count=dirty_count,
            active_speech=active_sp,
        )

        # Check speech attribution
        if scene_state.active_dialogue and scene_state.active_dialogue.speaker_track_id:
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
            "predicted_entities": active_in_frame,
            "active_hypotheses": [h.to_dict() for h in scene_state.hypotheses],
        })

    hyp_history = [h.to_dict() for h in tracker._hypotheses_history]

    # Save predictions
    out_preds = {
        "step": "Step 2.1 Person Detector (SSDLite320 MobileNetV3)",
        "conf_threshold": conf_threshold,
        "total_frames": len(frame_predictions),
        "raw_detections": raw_detections,
        "attributed_speech_turns": attributed_speech,
        "frame_predictions": frame_predictions,
        "hypotheses_log": hyp_history,
    }
    with open(out_preds_path, "w", encoding="utf-8") as f:
        json.dump(out_preds, f, ensure_ascii=False, indent=2)

    # ---------------------------------------------------------
    # Evaluation against Ground Truth
    # ---------------------------------------------------------
    gt_frames = {f["frame_idx"]: f for f in gt_data["frames"]}
    det_frames = {d["frame_idx"]: d["detections"] for d in raw_detections}

    iou_threshold = 0.30
    total_gt_boxes = 0
    total_pred_boxes = 0
    tp_boxes = 0
    fp_boxes = 0
    fn_boxes = 0
    matched_ious = []

    # Breakdown by visual state (static vs moving)
    static_gt = 0
    static_tp = 0
    moving_gt = 0
    moving_tp = 0

    frame_matches = []

    for f_idx in sorted(gt_frames.keys()):
        gt_chars = gt_frames[f_idx].get("characters", [])
        dets = det_frames.get(f_idx, [])

        total_gt_boxes += len(gt_chars)
        total_pred_boxes += len(dets)

        matched_d = set()
        for gt_c in gt_chars:
            gt_b = gt_c["bbox"]
            vstate = gt_c.get("visual_state", "idle")
            is_moving = (vstate == "moving")

            if is_moving:
                moving_gt += 1
            else:
                static_gt += 1

            best_iou = 0.0
            best_d_idx = -1
            for d_idx, d_box in enumerate(dets):
                if d_idx in matched_d:
                    continue
                iou = compute_iou(gt_b, d_box["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_d_idx = d_idx

            if best_iou >= iou_threshold and best_d_idx >= 0:
                tp_boxes += 1
                matched_d.add(best_d_idx)
                matched_ious.append(best_iou)
                if is_moving:
                    moving_tp += 1
                else:
                    static_tp += 1
                frame_matches.append((f_idx, gt_c["character_id"], dets[best_d_idx]))
            else:
                fn_boxes += 1

        fp_boxes += (len(dets) - len(matched_d))

    det_prec = tp_boxes / (tp_boxes + fp_boxes) if (tp_boxes + fp_boxes) > 0 else 0.0
    det_rec = tp_boxes / (tp_boxes + fn_boxes) if (tp_boxes + fn_boxes) > 0 else 0.0
    det_f1 = (2 * det_prec * det_rec) / (det_prec + det_rec) if (det_prec + det_rec) > 0 else 0.0
    mean_iou = float(np.mean(matched_ious)) if matched_ious else 0.0

    static_rec = static_tp / static_gt if static_gt > 0 else 0.0
    moving_rec = moving_tp / moving_gt if moving_gt > 0 else 0.0

    # Latency stats
    lat_sorted = sorted(latencies)
    lat_p50 = lat_sorted[int(len(lat_sorted) * 0.50)]
    lat_p95 = lat_sorted[int(len(lat_sorted) * 0.95)]
    lat_mean = float(np.mean(latencies))

    # Evaluate Tracking IDF1 with SSDLite detections
    pred_frames_dict = {f["frame_idx"]: f for f in frame_predictions}
    tracker_frame_matches = []
    tot_tracker_pred_boxes = 0

    for f_idx in sorted(gt_frames.keys()):
        gt_chars = gt_frames[f_idx].get("characters", [])
        pr_ents = pred_frames_dict.get(f_idx, {}).get("predicted_entities", [])
        tot_tracker_pred_boxes += len(pr_ents)

        matched_pr = set()
        for gt_c in gt_chars:
            best_iou = 0.0
            best_p_idx = -1
            for p_idx, p_e in enumerate(pr_ents):
                if p_idx in matched_pr:
                    continue
                iou = compute_iou(gt_c["bbox"], p_e["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_p_idx = p_idx

            if best_iou >= iou_threshold and best_p_idx >= 0:
                matched_pr.add(best_p_idx)
                tracker_frame_matches.append((f_idx, gt_c["character_id"], pr_ents[best_p_idx]["track_id"]))

    all_gt_ids = sorted(list(gt_data["character_catalog"].keys()))
    all_pred_ids = sorted(list({p[2] for p in tracker_frame_matches}))
    gt_to_idx = {gid: i for i, gid in enumerate(all_gt_ids)}
    pred_to_idx = {pid: i for i, pid in enumerate(all_pred_ids)}

    overlap_matrix = np.zeros((len(all_gt_ids), len(all_pred_ids)), dtype=np.int32)
    for _, gid, pid in tracker_frame_matches:
        overlap_matrix[gt_to_idx[gid], pred_to_idx[pid]] += 1

    matched_pairs = solve_max_weight_bipartite(overlap_matrix)
    gt_best_pred = {all_gt_ids[r]: all_pred_ids[c] for r, c in matched_pairs if overlap_matrix[r, c] > 0}
    pred_best_gt = {all_pred_ids[c]: all_gt_ids[r] for r, c in matched_pairs if overlap_matrix[r, c] > 0}

    id_tp = sum(1 for _, gid, pid in tracker_frame_matches if gt_best_pred.get(gid) == pid)
    id_fp = tot_tracker_pred_boxes - id_tp
    id_fn = total_gt_boxes - id_tp
    id_f1 = (2 * id_tp) / (2 * id_tp + id_fp + id_fn) if (2 * id_tp + id_fp + id_fn) > 0 else 0.0

    # ID switches
    gt_hist = defaultdict(list)
    for f_idx, gid, pid in tracker_frame_matches:
        gt_hist[gid].append((f_idx, pid))
    id_switches = 0
    for gid, tr in gt_hist.items():
        for i in range(1, len(tr)):
            if tr[i][1] != tr[i-1][1]:
                id_switches += 1

    # Cross character merges
    pred_to_gts = defaultdict(set)
    for _, gid, pid in tracker_frame_matches:
        pred_to_gts[pid].add(gid)
    false_merges = {pid: list(gts) for pid, gts in pred_to_gts.items() if len(gts) > 1}

    # Speaker Attribution
    attributed_dict = {a["turn_id"]: a for a in attributed_speech}
    correct_spk = 0
    for sp in speech_turns:
        tid = sp["turn_id"]
        true_spk = sp["speaker"]
        att = attributed_dict.get(tid)
        if att and not sp["is_offscreen"]:
            resolved = pred_best_gt.get(att["attributed_speaker_track_id"])
            if resolved == true_spk:
                correct_spk += 1

    spk_acc = correct_spk / len(speech_turns)

    metrics_result = {
        "model_name": "SSDLite320 MobileNetV3 Large (COCO weights)",
        "conf_threshold": conf_threshold,
        "iou_threshold": iou_threshold,
        "latency_ms": {
            "p50": round(lat_p50, 2),
            "p95": round(lat_p95, 2),
            "mean": round(lat_mean, 2),
        },
        "detection_metrics": {
            "precision": round(det_prec, 4),
            "recall": round(det_rec, 4),
            "f1_score": round(det_f1, 4),
            "mean_iou": round(mean_iou, 4),
            "tp": tp_boxes,
            "fp": fp_boxes,
            "fn": fn_boxes,
            "static_characters_recall": round(static_rec, 4),
            "moving_characters_recall": round(moving_rec, 4),
        },
        "tracking_impact": {
            "idf1": round(id_f1, 4),
            "id_switches": id_switches,
            "false_merges_count": len(false_merges),
            "false_merges": false_merges,
        },
        "speaker_attribution_impact": {
            "accuracy": round(spk_acc, 4),
            "correct_turns": correct_spk,
            "total_turns": len(speech_turns),
        },
    }

    with open(out_metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print("STEP 2.1 EVALUATION: SSDLite320 MobileNetV3 Person Detector")
    print("=" * 75)
    print(f"Latency: p50={lat_p50:.1f}ms, p95={lat_p95:.1f}ms, mean={lat_mean:.1f}ms")
    print(f"Detection Precision: {det_prec * 100:.2f}% | Recall: {det_rec * 100:.2f}% | Mean IoU: {mean_iou:.3f}")
    print(f"  * Static Characters Recall (idle/speaking): {static_rec * 100:.2f}% ({static_tp}/{static_gt})")
    print(f"  * Moving Characters Recall: {moving_rec * 100:.2f}% ({moving_tp}/{moving_gt})")
    print(f"Tracking IDF1: {id_f1 * 100:.2f}% | ID Switches: {id_switches}")
    print(f"Identity Collisions (False Merges): {len(false_merges)}")
    print(f"Speaker Attribution Accuracy: {spk_acc * 100:.2f}% ({correct_spk}/{len(speech_turns)})")
    print(f"Saved to: {out_metrics_path}")
    print("=" * 75)


if __name__ == "__main__":
    run_ssdlite_benchmark(conf_threshold=0.20)
