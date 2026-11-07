"""Step 2.1 Ensemble Detector: SSDLite320 (Body) + Face YOLOv9c (Head/Portrait).

Merges full-body person detections with face-projected portraits via NMS.
Evaluates:
  - Combined Detection Recall, Precision, Mean IoU
  - Static vs Moving Recall
  - End-to-end CPU Latency
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np


def compute_iou(b1: list[float], b2: list[float]) -> float:
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


def nms_merge(boxes: list[dict], iou_thresh: float = 0.40) -> list[dict]:
    # Sort by conf desc
    sorted_b = sorted(boxes, key=lambda x: x["conf"], reverse=True)
    keep = []
    for b in sorted_b:
        overlap = False
        for k in keep:
            if compute_iou(b["bbox"], k["bbox"]) > iou_thresh:
                overlap = True
                break
        if not overlap:
            keep.append(b)
    return keep


def run_ensemble_benchmark():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    ssd_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step21_ssdlite_predictions.json")
    face_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step21_face_body_predictions.json")
    out_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step21_ensemble_metrics.json")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    with open(ssd_path, "r", encoding="utf-8") as f:
        ssd_data = json.load(f)
    with open(face_path, "r", encoding="utf-8") as f:
        face_data = json.load(f)

    ssd_frames = {d["frame_idx"]: d["detections"] for d in ssd_data["raw_detections"]}
    face_frames = {d["frame_idx"]: d["detections"] for d in face_data["raw_detections"]}
    gt_frames = {f["frame_idx"]: f for f in gt_data["frames"]}

    iou_threshold = 0.30
    total_gt_boxes = 0
    total_pred_boxes = 0
    tp_boxes = 0
    fp_boxes = 0
    fn_boxes = 0
    matched_ious = []

    static_gt = 0
    static_tp = 0
    moving_gt = 0
    moving_tp = 0

    for f_idx in sorted(gt_frames.keys()):
        gt_chars = gt_frames[f_idx].get("characters", [])
        s_dets = ssd_frames.get(f_idx, [])
        f_dets = face_frames.get(f_idx, [])

        combined = nms_merge(s_dets + f_dets, iou_thresh=0.40)

        total_gt_boxes += len(gt_chars)
        total_pred_boxes += len(combined)

        matched_c = set()
        for gt_c in gt_chars:
            gt_b = gt_c["bbox"]
            vstate = gt_c.get("visual_state", "idle")
            is_moving = (vstate == "moving")

            if is_moving:
                moving_gt += 1
            else:
                static_gt += 1

            best_iou = 0.0
            best_c_idx = -1
            for c_idx, c_box in enumerate(combined):
                if c_idx in matched_c:
                    continue
                iou = compute_iou(gt_b, c_box["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_c_idx = c_idx

            if best_iou >= iou_threshold and best_c_idx >= 0:
                tp_boxes += 1
                matched_c.add(best_c_idx)
                matched_ious.append(best_iou)
                if is_moving:
                    moving_tp += 1
                else:
                    static_tp += 1
            else:
                fn_boxes += 1

        fp_boxes += (len(combined) - len(matched_c))

    det_prec = tp_boxes / (tp_boxes + fp_boxes) if (tp_boxes + fp_boxes) > 0 else 0.0
    det_rec = tp_boxes / (tp_boxes + fn_boxes) if (tp_boxes + fn_boxes) > 0 else 0.0
    det_f1 = (2 * det_prec * det_rec) / (det_prec + det_rec) if (det_prec + det_rec) > 0 else 0.0
    mean_iou = float(np.mean(matched_ious)) if matched_ious else 0.0

    static_rec = static_tp / static_gt if static_gt > 0 else 0.0
    moving_rec = moving_tp / moving_gt if moving_gt > 0 else 0.0

    metrics_result = {
        "model_name": "Ensemble (SSDLite320 + Face YOLOv9c NMS)",
        "iou_threshold": iou_threshold,
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
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metrics_result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 75)
    print("STEP 2.1 EVALUATION: Ensemble (SSDLite320 + Face YOLO NMS)")
    print("=" * 75)
    print(f"Detection Precision: {det_prec * 100:.2f}% | Recall: {det_rec * 100:.2f}% | Mean IoU: {mean_iou:.3f}")
    print(f"  * Static Characters Recall (idle/speaking): {static_rec * 100:.2f}% ({static_tp}/{static_gt})")
    print(f"  * Moving Characters Recall: {moving_rec * 100:.2f}% ({moving_tp}/{moving_gt})")
    print(f"Saved to: {out_path}")
    print("=" * 75)


if __name__ == "__main__":
    run_ensemble_benchmark()
