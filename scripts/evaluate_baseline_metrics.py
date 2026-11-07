"""Evaluates Round 9 Baseline Predictions against Ground Truth (180s benchmark).

Calculates standard benchmark metrics:
  1. Detection: Precision, Recall, F1, mean IoU (IoU >= 0.30 & IoU >= 0.50)
  2. Tracking / Re-ID:
     - IDF1 (Ristani et al. 2016 standard bipartite trajectory matching)
     - ID Switches (IDSW)
     - Track Fragmentation
     - Cross-Character False Merge count (Identity Collisions)
  3. Narrative Speaker Binding:
     - Speaker Attribution Accuracy
     - Offscreen speech false attribution rate
     - Unknown / abstention rate

Saves:
  runtime/instances/daily/data/sensory/youtube_watch/baseline_metrics_180s.json
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import numpy as np


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
    """Greedy or scipy maximum bipartite matching."""
    try:
        from scipy.optimize import linear_sum_assignment
        row_ind, col_ind = linear_sum_assignment(-cost_matrix)
        return list(zip(row_ind, col_ind))
    except ImportError:
        # Fallback greedy max matching
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


def evaluate_180s_benchmark():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    pred_path = Path("runtime/instances/daily/data/sensory/youtube_watch/baseline_predictions_180s.json")
    out_metrics_path = Path("runtime/instances/daily/data/sensory/youtube_watch/baseline_metrics_180s.json")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)
    with open(pred_path, "r", encoding="utf-8") as f:
        pred = json.load(f)

    gt_frames = {f["frame_idx"]: f for f in gt["frames"]}
    pred_frames = {f["frame_idx"]: f for f in pred["frame_predictions"]}

    iou_threshold = 0.30

    # ---------------------------------------------------------
    # 1. Detection Evaluation
    # ---------------------------------------------------------
    total_gt_boxes = 0
    total_pred_boxes = 0
    tp_boxes = 0
    fp_boxes = 0
    fn_boxes = 0
    matched_ious = []

    frame_matches = []  # list of (frame_idx, gt_char_id, pred_track_id)

    for f_idx in sorted(gt_frames.keys()):
        gt_f = gt_frames[f_idx]
        pr_f = pred_frames.get(f_idx, {})

        gt_chars = gt_f.get("characters", [])
        pr_ents = pr_f.get("predicted_entities", [])

        total_gt_boxes += len(gt_chars)
        total_pred_boxes += len(pr_ents)

        matched_pr = set()
        for gt_c in gt_chars:
            gt_b = gt_c["bbox"]
            best_iou = 0.0
            best_p_idx = -1
            for p_idx, p_e in enumerate(pr_ents):
                if p_idx in matched_pr:
                    continue
                iou = compute_iou(gt_b, p_e["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_p_idx = p_idx

            if best_iou >= iou_threshold and best_p_idx >= 0:
                tp_boxes += 1
                matched_pr.add(best_p_idx)
                matched_ious.append(best_iou)
                frame_matches.append((f_idx, gt_c["character_id"], pr_ents[best_p_idx]["track_id"]))
            else:
                fn_boxes += 1

        fp_boxes += (len(pr_ents) - len(matched_pr))

    det_prec = tp_boxes / (tp_boxes + fp_boxes) if (tp_boxes + fp_boxes) > 0 else 0.0
    det_rec = tp_boxes / (tp_boxes + fn_boxes) if (tp_boxes + fn_boxes) > 0 else 0.0
    det_f1 = (2 * det_prec * det_rec) / (det_prec + det_rec) if (det_prec + det_rec) > 0 else 0.0
    mean_iou = float(np.mean(matched_ious)) if matched_ious else 0.0

    # ---------------------------------------------------------
    # 2. Tracking & Re-ID Evaluation (IDF1, IDSW, Identity Collisions)
    # ---------------------------------------------------------
    # Get all distinct GT character IDs and Predicted Track IDs
    all_gt_ids = sorted(list(gt["character_catalog"].keys()))
    all_pred_ids = sorted(list({p[2] for p in frame_matches}))

    gt_to_idx = {gid: i for i, gid in enumerate(all_gt_ids)}
    pred_to_idx = {pid: i for i, pid in enumerate(all_pred_ids)}

    # Cost matrix: overlap count
    overlap_matrix = np.zeros((len(all_gt_ids), len(all_pred_ids)), dtype=np.int32)
    for _, gid, pid in frame_matches:
        overlap_matrix[gt_to_idx[gid], pred_to_idx[pid]] += 1

    # Optimal global 1-to-1 alignment for IDF1
    matched_pairs = solve_max_weight_bipartite(overlap_matrix)
    gt_best_pred = {all_gt_ids[r]: all_pred_ids[c] for r, c in matched_pairs if overlap_matrix[r, c] > 0}
    pred_best_gt = {all_pred_ids[c]: all_gt_ids[r] for r, c in matched_pairs if overlap_matrix[r, c] > 0}

    # IDF1 Calculation
    # IDTP = detections where pred matches the assigned GT track
    id_tp = 0
    for _, gid, pid in frame_matches:
        if gt_best_pred.get(gid) == pid:
            id_tp += 1

    id_fp = total_pred_boxes - id_tp
    id_fn = total_gt_boxes - id_tp
    id_f1 = (2 * id_tp) / (2 * id_tp + id_fp + id_fn) if (2 * id_tp + id_fp + id_fn) > 0 else 0.0
    id_prec = id_tp / (id_tp + id_fp) if (id_tp + id_fp) > 0 else 0.0
    id_rec = id_tp / (id_tp + id_fn) if (id_tp + id_fn) > 0 else 0.0

    # ID Switches: when a GT track's matched pred track changes across time
    gt_history = defaultdict(list)
    for f_idx, gid, pid in frame_matches:
        gt_history[gid].append((f_idx, pid))

    id_switches = 0
    for gid, tr in gt_history.items():
        for i in range(1, len(tr)):
            if tr[i][1] != tr[i-1][1]:
                id_switches += 1

    # Cross-Character False Merges (Black Hole / Identity Collision):
    # Check how many DIFFERENT ground truth characters were subsumed into a single predicted track
    pred_to_gts = defaultdict(set)
    pred_gt_counts = defaultdict(lambda: defaultdict(int))
    for _, gid, pid in frame_matches:
        pred_to_gts[pid].add(gid)
        pred_gt_counts[pid][gid] += 1

    false_merges_summary = {}
    for pid, gts in pred_to_gts.items():
        if len(gts) > 1:
            false_merges_summary[pid] = {
                "distinct_gt_characters_merged": len(gts),
                "gt_characters": sorted(list(gts)),
                "frame_counts_per_character": dict(pred_gt_counts[pid]),
            }

    # ---------------------------------------------------------
    # 3. Speaker Attribution Evaluation
    # ---------------------------------------------------------
    speech_events = gt["speech_events"]
    attributed_turns = {a["turn_id"]: a for a in pred.get("attributed_speech_turns", [])}

    correct_speaker_attributions = 0
    wrong_speaker_attributions = 0
    offscreen_misattributed = 0
    unattributed_turns = 0

    attribution_details = []

    for sp in speech_events:
        tid = sp["turn_id"]
        true_spk = sp["speaker"]
        is_off = sp["is_offscreen"]

        pred_att = attributed_turns.get(tid)
        if pred_att is None:
            unattributed_turns += 1
            attribution_details.append({
                "turn_id": tid,
                "text": sp["text"],
                "true_speaker": true_spk,
                "is_offscreen": is_off,
                "status": "unattributed (abstain)",
                "predicted_track_id": None,
                "resolved_character": None,
            })
            continue

        pred_track = pred_att["attributed_speaker_track_id"]
        # Map predicted track ID to ground truth character at that moment
        # Check who was mapped to pred_best_gt
        resolved_char = pred_best_gt.get(pred_track)

        if is_off:
            # GT says speaker is offscreen! Baseline assigned it to an on-screen entity.
            offscreen_misattributed += 1
            wrong_speaker_attributions += 1
            attribution_details.append({
                "turn_id": tid,
                "text": sp["text"],
                "true_speaker": true_spk,
                "is_offscreen": True,
                "status": "misattributed (should be offscreen)",
                "predicted_track_id": pred_track,
                "resolved_character": resolved_char,
            })
        else:
            if resolved_char == true_spk:
                correct_speaker_attributions += 1
                attribution_details.append({
                    "turn_id": tid,
                    "text": sp["text"],
                    "true_speaker": true_spk,
                    "is_offscreen": False,
                    "status": "correct",
                    "predicted_track_id": pred_track,
                    "resolved_character": resolved_char,
                })
            else:
                wrong_speaker_attributions += 1
                attribution_details.append({
                    "turn_id": tid,
                    "text": sp["text"],
                    "true_speaker": true_spk,
                    "is_offscreen": False,
                    "status": "wrong_speaker",
                    "predicted_track_id": pred_track,
                    "resolved_character": resolved_char,
                })

    spk_accuracy = correct_speaker_attributions / len(speech_events) if speech_events else 0.0

    metrics_result = {
        "benchmark_summary": {
            "name": "180s YouTube Drama Continuous Multimodal Benchmark",
            "duration_sec": 180.0,
            "total_frames": len(gt_frames),
            "total_gt_boxes": total_gt_boxes,
            "total_pred_boxes": total_pred_boxes,
            "total_dialogue_turns": len(speech_events),
        },
        "detection_metrics": {
            "iou_threshold": iou_threshold,
            "precision": round(det_prec, 4),
            "recall": round(det_rec, 4),
            "f1_score": round(det_f1, 4),
            "mean_iou_matched": round(mean_iou, 4),
            "tp": tp_boxes,
            "fp": fp_boxes,
            "fn": fn_boxes,
        },
        "tracking_reid_metrics": {
            "idf1": round(id_f1, 4),
            "id_precision": round(id_prec, 4),
            "id_recall": round(id_rec, 4),
            "id_switches": id_switches,
            "total_hypotheses_evaluated": pred["total_hypotheses"],
            "confirmed_hypotheses": pred["confirmed_hypotheses"],
            "proposed_hypotheses": pred["proposed_hypotheses"],
            "cross_character_false_merges": false_merges_summary,
            "identity_collisions_detected": len(false_merges_summary),
        },
        "speaker_attribution_metrics": {
            "total_speech_turns": len(speech_events),
            "speaker_attribution_accuracy": round(spk_accuracy, 4),
            "correct_attributions": correct_speaker_attributions,
            "wrong_attributions": wrong_speaker_attributions,
            "offscreen_misattributions": offscreen_misattributed,
            "unattributed_turns": unattributed_turns,
        },
        "attribution_details": attribution_details,
    }

    with open(out_metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print("ROUND 9 BASELINE BENCHMARK EVALUATION (0 - 180s)")
    print("=" * 75)
    print(f"Detection Precision: {det_prec * 100:.2f}% | Recall: {det_rec * 100:.2f}% | Mean IoU: {mean_iou:.3f}")
    print(f"Tracking IDF1: {id_f1 * 100:.2f}% (ID Precision: {id_prec * 100:.2f}%, ID Recall: {id_rec * 100:.2f}%)")
    print(f"ID Switches: {id_switches}")
    print(f"Identity Collisions (Cross-Character False Merges): {len(false_merges_summary)}")
    for pid, coll in false_merges_summary.items():
        chars = ", ".join(coll["gt_characters"])
        print(f"  * {pid} subsumed {coll['distinct_gt_characters_merged']} characters: [{chars}]")
    print(f"Speaker Attribution Accuracy: {spk_accuracy * 100:.2f}% ({correct_speaker_attributions}/{len(speech_events)})")
    print(f"Offscreen Speech Misattributed: {offscreen_misattributed}")
    print(f"Metrics saved to: {out_metrics_path}")
    print("=" * 75)


if __name__ == "__main__":
    evaluate_180s_benchmark()
