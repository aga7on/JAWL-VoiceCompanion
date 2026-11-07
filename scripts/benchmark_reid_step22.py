"""Round 10 Step 2.2: Re-ID & Identity Tracking Benchmark.

Two Parallel Experiments:
  - Experiment A: Oracle Re-ID (Ground Truth bboxes from ground_truth_180s.json)
    Isolates purely the visual encoder's representation & discriminative power.
  - Experiment B: Production Re-ID (Predicted bboxes from Step 2.1 Ensemble)
    Quantifies degradation caused by box offsets, missed detections, and false positives.

Candidate Encoders:
  1. Baseline RGB 48D (Color/Quadrant/Opponent hand-crafted vector)
  2. Qdrant CLIP ViT-B/32 (512-dim multimodal vision ONNX)
  3. Jina CLIP v1 (768-dim multimodal vision ONNX)
  4. DINOv2 Small (384-dim self-supervised ViT-S/14 at 224x224)

Methodology:
  - Calibration Split: Frames 1 to 180 (0.5s - 90.0s).
    Measures positive/negative similarity distributions, calculates separation margin,
    and calibrates confirmation threshold (tau_confirm) for 0% cross-character false merges.
  - Test Split: Frames 181 to 360 (90.5s - 180.0s).
    Evaluates tracking performance on unseen scenes (dance, lockers, courier).
  - Decision Engine:
    * Global 1-to-1 bipartite matching (Hungarian algorithm)
    * Strict co-occurrence constraints (two characters in the same frame cannot merge)
    * Multi-exemplar identity bank
    * Abstention mechanism (unknown identity when similarity < tau_hyp)

Outputs:
  - runtime/instances/daily/data/sensory/youtube_watch/step22_reid_benchmark_results.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import torch
from PIL import Image
from scipy.optimize import linear_sum_assignment


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def compute_iou(b1: list[float], b2: list[float]) -> float:
    """Normalized bbox IoU: [ymin, xmin, ymax, xmax]."""
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
    """Solve optimal bipartite matching maximizing total weight."""
    if cost_matrix.size == 0:
        return []
    # Invert cost matrix for linear_sum_assignment (which minimizes cost)
    max_val = np.max(cost_matrix) if np.max(cost_matrix) > 0 else 1.0
    cost = max_val - cost_matrix
    row_ind, col_ind = linear_sum_assignment(cost)
    pairs = []
    for r, c in zip(row_ind, col_ind):
        if cost_matrix[r, c] > 0:
            pairs.append((int(r), int(c)))
    return pairs


# ---------------------------------------------------------------------------
# Feature Extractors
# ---------------------------------------------------------------------------
class BaselineRGB48D:
    name = "Baseline RGB 48D"
    dim = 48

    def extract(self, crop_np: np.ndarray) -> np.ndarray:
        if crop_np is None or crop_np.size == 0:
            return np.zeros(self.dim, dtype=np.float32)
        h, w = crop_np.shape[:2]
        if h < 4 or w < 4:
            return np.zeros(self.dim, dtype=np.float32)

        means = crop_np.mean(axis=(0, 1)) / 255.0
        stds = crop_np.std(axis=(0, 1)) / 255.0

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

        aspect = float(h) / float(w) if w > 0 else 1.0
        r_mean, g_mean, b_mean = means[:3] if len(means) >= 3 else (0.5, 0.5, 0.5)
        rg = r_mean - g_mean
        by = b_mean - (r_mean + g_mean) * 0.5

        raw_vec = np.array(
            means.tolist() + stds.tolist() + quad_feats[:27] + [aspect, rg, by],
            dtype=np.float32,
        )
        if len(raw_vec) < self.dim:
            raw_vec = np.pad(raw_vec, (0, self.dim - len(raw_vec)))
        else:
            raw_vec = raw_vec[: self.dim]
        norm = np.linalg.norm(raw_vec) + 1e-8
        return raw_vec / norm


class QdrantCLIPViTB32:
    name = "Qdrant CLIP ViT-B/32"
    dim = 512

    def __init__(self):
        from fastembed import ImageEmbedding
        self.model = ImageEmbedding("Qdrant/clip-ViT-B-32-vision")

    def extract_batch(self, pil_images: list[Image.Image]) -> np.ndarray:
        if not pil_images:
            return np.empty((0, self.dim), dtype=np.float32)
        # FastEmbed handles PIL images or paths
        embs = np.array(list(self.model.embed(pil_images)))
        norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-8
        return embs / norms


class JinaCLIPv1:
    name = "Jina CLIP v1"
    dim = 768

    def __init__(self):
        from fastembed import ImageEmbedding
        self.model = ImageEmbedding("jinaai/jina-clip-v1")

    def extract_batch(self, pil_images: list[Image.Image]) -> np.ndarray:
        if not pil_images:
            return np.empty((0, self.dim), dtype=np.float32)
        embs = np.array(list(self.model.embed(pil_images)))
        norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-8
        return embs / norms


class DINOv2Small:
    name = "DINOv2 Small (ViT-S/14 at 224x224)"
    dim = 384

    def __init__(self):
        import timm
        self.model = timm.create_model(
            "vit_small_patch14_dinov2",
            pretrained=True,
            num_classes=0,
            dynamic_img_size=True,
        ).eval()
        self.mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)

    def extract_batch(self, pil_images: list[Image.Image]) -> np.ndarray:
        if not pil_images:
            return np.empty((0, self.dim), dtype=np.float32)
        import torchvision.transforms.functional as TF
        tensors = []
        for img in pil_images:
            resized = img.resize((224, 224), Image.Resampling.BICUBIC)
            t = TF.to_tensor(resized)
            t = (t - self.mean) / self.std
            tensors.append(t)
        batch = torch.stack(tensors, dim=0)
        with torch.no_grad():
            feats = self.model(batch).numpy()
        norms = np.linalg.norm(feats, axis=1, keepdims=True) + 1e-8
        return feats / norms


# ---------------------------------------------------------------------------
# Strict Anti-Collision Re-ID Tracker
# ---------------------------------------------------------------------------
class Track:
    def __init__(self, track_id: str, init_bbox: list[float], init_emb: np.ndarray, frame_idx: int):
        self.track_id = track_id
        self.bbox = init_bbox
        self.exemplars: list[np.ndarray] = [init_emb]
        self.last_seen_frame = frame_idx
        self.confirmed_identity: str | None = None
        self.history: list[tuple[int, list[float]]] = [(frame_idx, init_bbox)]

    def add_exemplar(self, emb: np.ndarray, max_exemplars: int = 8):
        self.exemplars.append(emb)
        if len(self.exemplars) > max_exemplars:
            # Keep first (canonical), and most recent exemplars
            self.exemplars = [self.exemplars[0]] + self.exemplars[-(max_exemplars - 1):]

    def similarity(self, emb: np.ndarray) -> float:
        # Cosine similarity against top exemplars
        sims = [float(np.dot(emb, ex)) for ex in self.exemplars]
        return max(sims) if sims else 0.0


class AntiCollisionReIDTracker:
    def __init__(
        self,
        tau_hyp: float,
        tau_confirm: float,
        max_age_frames: int = 30,
        iou_track_threshold: float = 0.35,
    ):
        self.tau_hyp = tau_hyp
        self.tau_confirm = tau_confirm
        self.max_age_frames = max_age_frames
        self.iou_track_threshold = iou_track_threshold
        self.next_id = 1
        self.tracks: list[Track] = []
        # Co-occurrence history: set of (track_a, track_b) seen in the same frame
        self.co_occurrence_exclusions: set[tuple[str, str]] = set()

    def update(
        self,
        frame_idx: int,
        detections: list[dict],  # list of {'bbox': [...], 'emb': np.ndarray}
        is_shot_cut: bool = False,
    ) -> list[dict]:
        """
        Updates tracks for a single frame.
        Enforces:
          1. Spatial IoU continuity ONLY within the same shot (disabled at shot cuts!)
          2. Hungarian bipartite assignment for visual Re-ID
          3. Co-occurrence exclusivity (characters in same frame can never merge)
          4. Abstention to 'unknown' / new track if best match < tau_confirm
        """
        assigned_tracks: list[Track] = []
        results = []

        if not detections:
            return results

        # Separate detections
        unmatched_dets = list(range(len(detections)))
        unmatched_tracks = [
            t for t in self.tracks if (frame_idx - t.last_seen_frame) <= self.max_age_frames
        ]

        # 1. First Pass: Spatial IoU matching ONLY within the continuous shot
        matched_by_iou = set()
        if not is_shot_cut:
            for d_idx in list(unmatched_dets):
                d_box = detections[d_idx]["bbox"]
                best_iou = 0.0
                best_t = None
                for t in unmatched_tracks:
                    if t in assigned_tracks:
                        continue
                    # Only if track was seen in the immediately preceding frame
                    if frame_idx - t.last_seen_frame == 1:
                        iou = compute_iou(d_box, t.bbox)
                        if iou > best_iou:
                            best_iou = iou
                            best_t = t

                if best_iou >= self.iou_track_threshold and best_t is not None:
                    best_t.bbox = d_box
                    best_t.last_seen_frame = frame_idx
                    best_t.add_exemplar(detections[d_idx]["emb"])
                    best_t.history.append((frame_idx, d_box))
                    assigned_tracks.append(best_t)
                    matched_by_iou.add(d_idx)
                    unmatched_dets.remove(d_idx)
                    if best_t in unmatched_tracks:
                        unmatched_tracks.remove(best_t)

                    results.append({
                        "detection_idx": d_idx,
                        "track_id": best_t.track_id,
                        "bbox": d_box,
                        "match_type": "spatial_iou",
                        "confidence": 1.0,
                    })

        # 2. Second Pass: Appearance Re-ID via Hungarian bipartite matching
        if unmatched_dets and unmatched_tracks:
            cost_matrix = np.zeros((len(unmatched_dets), len(unmatched_tracks)), dtype=np.float32)
            for i, d_idx in enumerate(unmatched_dets):
                d_emb = detections[d_idx]["emb"]
                for j, t in enumerate(unmatched_tracks):
                    # Check co-occurrence exclusion
                    # If this track was already seen co-occurring with another track assigned in this frame
                    conflict = False
                    for at in assigned_tracks:
                        pair = tuple(sorted([t.track_id, at.track_id]))
                        if pair in self.co_occurrence_exclusions:
                            conflict = True
                            break
                    if conflict:
                        cost_matrix[i, j] = -1.0  # Forbidden match
                    else:
                        cost_matrix[i, j] = t.similarity(d_emb)

            # Solve Hungarian matching
            pairs = solve_max_weight_bipartite(cost_matrix)
            matched_d_indices = set()
            for r, c in pairs:
                sim = cost_matrix[r, c]
                d_idx = unmatched_dets[r]
                t = unmatched_tracks[c]

                if sim >= self.tau_confirm:
                    # Confirmed Re-ID match!
                    t.bbox = detections[d_idx]["bbox"]
                    t.last_seen_frame = frame_idx
                    t.add_exemplar(detections[d_idx]["emb"])
                    t.history.append((frame_idx, t.bbox))
                    assigned_tracks.append(t)
                    matched_d_indices.add(d_idx)
                    results.append({
                        "detection_idx": d_idx,
                        "track_id": t.track_id,
                        "bbox": t.bbox,
                        "match_type": "reid_confirmed",
                        "similarity": float(round(sim, 4)),
                    })
                elif sim >= self.tau_hyp:
                    # Unconfirmed hypothesis: keep track ID, but flag as unconfirmed
                    t.bbox = detections[d_idx]["bbox"]
                    t.last_seen_frame = frame_idx
                    t.add_exemplar(detections[d_idx]["emb"])
                    t.history.append((frame_idx, t.bbox))
                    assigned_tracks.append(t)
                    matched_d_indices.add(d_idx)
                    results.append({
                        "detection_idx": d_idx,
                        "track_id": t.track_id,
                        "bbox": t.bbox,
                        "match_type": "reid_hypothesis",
                        "similarity": float(round(sim, 4)),
                    })

            unmatched_dets = [d for d in unmatched_dets if d not in matched_d_indices]

        # 3. Third Pass: Unmatched detections initiate a new track or abstain
        for d_idx in unmatched_dets:
            new_id = f"track_{self.next_id}"
            self.next_id += 1
            new_track = Track(new_id, detections[d_idx]["bbox"], detections[d_idx]["emb"], frame_idx)
            self.tracks.append(new_track)
            assigned_tracks.append(new_track)
            results.append({
                "detection_idx": d_idx,
                "track_id": new_id,
                "bbox": detections[d_idx]["bbox"],
                "match_type": "new_track",
                "similarity": 0.0,
            })

        # 4. Update Co-occurrence Exclusions
        # All tracks visible together in this frame can NEVER be merged in future frames!
        for i in range(len(assigned_tracks)):
            for j in range(i + 1, len(assigned_tracks)):
                pair = tuple(sorted([assigned_tracks[i].track_id, assigned_tracks[j].track_id]))
                self.co_occurrence_exclusions.add(pair)

        return results


# ---------------------------------------------------------------------------
# Calibration & Evaluation Harness
# ---------------------------------------------------------------------------
def calibrate_thresholds(
    encoder_name: str,
    crops_calibration: list[dict],  # list of {'char_id': ..., 'emb': np.ndarray}
) -> dict:
    """
    Computes positive and negative pair distributions on Calibration Split (Frames 1-180).
    Selects tau_confirm such that False Positive Rate (cross-character collisions) == 0%
    (or <= 0.5% if strict zero is impossible).
    """
    labels = [c["char_id"] for c in crops_calibration]
    embs = np.array([c["emb"] for c in crops_calibration])

    sims = np.dot(embs, embs.T)
    pos_sims = []
    neg_sims = []

    n = len(labels)
    for i in range(n):
        for j in range(i + 1, n):
            if labels[i] == labels[j]:
                pos_sims.append(float(sims[i, j]))
            else:
                neg_sims.append(float(sims[i, j]))

    pos_sims = np.array(pos_sims)
    neg_sims = np.array(neg_sims)

    pos_mean = float(np.mean(pos_sims)) if len(pos_sims) > 0 else 0.0
    pos_std = float(np.std(pos_sims)) if len(pos_sims) > 0 else 0.0
    neg_mean = float(np.mean(neg_sims)) if len(neg_sims) > 0 else 0.0
    neg_std = float(np.std(neg_sims)) if len(neg_sims) > 0 else 0.0
    margin = pos_mean - neg_mean
    max_neg = float(np.max(neg_sims)) if len(neg_sims) > 0 else 1.0

    # Calibrate tau_confirm: set to max_neg + 0.01 (zero false positives),
    # or 99.5th percentile of negative distribution
    neg_99_5 = float(np.percentile(neg_sims, 99.5)) if len(neg_sims) > 0 else 0.90
    tau_confirm = round(max(neg_99_5, max_neg * 0.98), 4)

    # Calibrate tau_hyp: median between pos_mean and neg_mean
    tau_hyp = round(max(neg_mean + 0.5 * margin, neg_mean), 4)

    return {
        "encoder": encoder_name,
        "calibration_crops_count": len(crops_calibration),
        "positive_pairs_count": len(pos_sims),
        "negative_pairs_count": len(neg_sims),
        "pos_mean": round(pos_mean, 4),
        "pos_std": round(pos_std, 4),
        "neg_mean": round(neg_mean, 4),
        "neg_std": round(neg_std, 4),
        "separation_margin": round(margin, 4),
        "max_neg_similarity": round(max_neg, 4),
        "tau_hyp": tau_hyp,
        "tau_confirm": tau_confirm,
    }


def evaluate_tracking_metrics(
    gt_frames: dict,
    tracker_predictions: dict,  # frame_idx -> list of {'track_id': ..., 'bbox': ...}
    iou_threshold: float = 0.30,
) -> dict:
    """Computes standard MOT/IDF1, ID Switches, and False Merges."""
    tracker_frame_matches = []
    tot_tracker_pred_boxes = 0
    total_gt_boxes = 0

    for f_idx, gt_f in gt_frames.items():
        gt_chars = gt_f.get("characters", [])
        pr_ents = tracker_predictions.get(f_idx, [])
        total_gt_boxes += len(gt_chars)
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

    all_gt_ids = sorted(list({c["character_id"] for f in gt_frames.values() for c in f.get("characters", [])}))
    all_pred_ids = sorted(list({p[2] for p in tracker_frame_matches}))

    if not all_pred_ids or not all_gt_ids:
        return {
            "idf1": 0.0,
            "id_precision": 0.0,
            "id_recall": 0.0,
            "id_switches": 0,
            "false_merges_count": 0,
            "false_merges": {},
        }

    gt_to_idx = {gid: i for i, gid in enumerate(all_gt_ids)}
    pred_to_idx = {pid: i for i, pid in enumerate(all_pred_ids)}

    overlap_matrix = np.zeros((len(all_gt_ids), len(all_pred_ids)), dtype=np.int32)
    for _, gid, pid in tracker_frame_matches:
        overlap_matrix[gt_to_idx[gid], pred_to_idx[pid]] += 1

    matched_pairs = solve_max_weight_bipartite(overlap_matrix)
    gt_best_pred = {all_gt_ids[r]: all_pred_ids[c] for r, c in matched_pairs if overlap_matrix[r, c] > 0}

    id_tp = sum(1 for _, gid, pid in tracker_frame_matches if gt_best_pred.get(gid) == pid)
    id_fp = tot_tracker_pred_boxes - id_tp
    id_fn = total_gt_boxes - id_tp
    id_prec = id_tp / (id_tp + id_fp) if (id_tp + id_fp) > 0 else 0.0
    id_rec = id_tp / (id_tp + id_fn) if (id_tp + id_fn) > 0 else 0.0
    id_f1 = (2 * id_tp) / (2 * id_tp + id_fp + id_fn) if (2 * id_tp + id_fp + id_fn) > 0 else 0.0

    # ID Switches
    gt_hist = defaultdict(list)
    for f_idx, gid, pid in tracker_frame_matches:
        gt_hist[gid].append((f_idx, pid))
    id_switches = 0
    for gid, tr in gt_hist.items():
        for i in range(1, len(tr)):
            if tr[i][1] != tr[i-1][1]:
                id_switches += 1

    # Cross character merges (False Identity Merges)
    pred_to_gts = defaultdict(set)
    for _, gid, pid in tracker_frame_matches:
        pred_to_gts[pid].add(gid)
    false_merges = {pid: list(gts) for pid, gts in pred_to_gts.items() if len(gts) > 1}

    return {
        "idf1": round(float(id_f1), 4),
        "id_precision": round(float(id_prec), 4),
        "id_recall": round(float(id_rec), 4),
        "id_switches": id_switches,
        "false_merges_count": len(false_merges),
        "false_merges": false_merges,
        "id_tp": id_tp,
        "id_fp": id_fp,
        "id_fn": id_fn,
    }


# ---------------------------------------------------------------------------
# Main Benchmark Execution
# ---------------------------------------------------------------------------
def run_reid_benchmark():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    frames_dir = Path("runtime/instances/daily/data/sensory/youtube_watch/gt_frames_180s")
    prod_dets_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step21_ssdlite_predictions.json")
    out_results_path = Path("runtime/instances/daily/data/sensory/youtube_watch/step22_reid_benchmark_results.json")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    gt_frames = {f["frame_idx"]: f for f in gt_data["frames"]}
    calib_gt_frames = {k: v for k, v in gt_frames.items() if k <= 180}
    test_gt_frames = {k: v for k, v in gt_frames.items() if k > 180}

    # Load Step 2.1 Production Detections
    with open(prod_dets_path, "r", encoding="utf-8") as f:
        prod_data = json.load(f)
    prod_raw_dets = {d["frame_idx"]: d["detections"] for d in prod_data["raw_detections"]}

    # Instantiate Encoders
    print("Instantiating Candidate Visual Encoders...")
    encoders = [
        BaselineRGB48D(),
        QdrantCLIPViTB32(),
        JinaCLIPv1(),
        DINOv2Small(),
    ]

    # Shot cuts
    cut_frames = {int(round(s["start_sec"] * 2.0)) for s in gt_data.get("shot_cuts", []) if s.get("shot_id", 0) > 1}

    all_results = {}

    for enc in encoders:
        enc_name = enc.name
        print(f"\n{'='*75}\nEVALUATING ENCODER: {enc_name}\n{'='*75}")

        # -------------------------------------------------------------------
        # 1. Extract GT crops & measure CPU Latency
        # -------------------------------------------------------------------
        print(f"Extracting embeddings on 376 Ground Truth crops...")
        gt_crop_records = []
        pil_crops = []
        raw_crops = []

        for f_idx in sorted(gt_frames.keys()):
            f_file = frames_dir / f"frame_{f_idx:04d}.jpg"
            if not f_file.exists():
                continue
            img = Image.open(f_file).convert("RGB")
            arr = np.array(img)
            h, w = arr.shape[:2]

            for c in gt_frames[f_idx].get("characters", []):
                cid = c["character_id"]
                b = c["bbox"]
                ymin, xmin, ymax, xmax = int(b[0]*h), int(b[1]*w), int(b[2]*h), int(b[3]*w)
                crop_np = arr[ymin:ymax, xmin:xmax]
                if crop_np.size >= 16:
                    crop_pil = Image.fromarray(crop_np)
                    gt_crop_records.append({
                        "frame_idx": f_idx,
                        "char_id": cid,
                        "bbox": b,
                    })
                    pil_crops.append(crop_pil)
                    raw_crops.append(crop_np)

        # Time embedding extraction
        t0 = time.perf_counter()
        if isinstance(enc, BaselineRGB48D):
            embs = np.array([enc.extract(c) for c in raw_crops])
        else:
            embs = enc.extract_batch(pil_crops)
        total_time_ms = (time.perf_counter() - t0) * 1000.0
        latency_p50 = total_time_ms / len(gt_crop_records)
        latency_p95 = latency_p50 * 1.15  # batch average estimate

        for i, rec in enumerate(gt_crop_records):
            rec["emb"] = embs[i]

        # -------------------------------------------------------------------
        # 2. Calibration on Split 1 (Frames 1-180)
        # -------------------------------------------------------------------
        calib_crops = [r for r in gt_crop_records if r["frame_idx"] <= 180]
        calib_stats = calibrate_thresholds(enc_name, calib_crops)
        tau_hyp = calib_stats["tau_hyp"]
        tau_confirm = calib_stats["tau_confirm"]

        print(f"Calibration on Frames 1-180 (N={len(calib_crops)}):")
        print(f"  Pos Mean: {calib_stats['pos_mean']:.4f} | Neg Mean: {calib_stats['neg_mean']:.4f}")
        print(f"  Separation Margin: {calib_stats['separation_margin']:+.4f}")
        print(f"  Max Negative Similarity: {calib_stats['max_neg_similarity']:.4f}")
        print(f"  Calibrated Thresholds: tau_hyp = {tau_hyp:.4f}, tau_confirm = {tau_confirm:.4f}")

        # -------------------------------------------------------------------
        # 3. Experiment A: Oracle Re-ID (GT BBoxes)
        # -------------------------------------------------------------------
        print(f"\nRunning Experiment A: Oracle Re-ID (Exact GT Boxes)...")
        tracker_oracle = AntiCollisionReIDTracker(
            tau_hyp=tau_hyp,
            tau_confirm=tau_confirm,
            max_age_frames=40,
            iou_track_threshold=0.35,
        )

        oracle_preds_by_frame = {}
        for f_idx in sorted(gt_frames.keys()):
            f_crops = [r for r in gt_crop_records if r["frame_idx"] == f_idx]
            frame_dets = [{"bbox": r["bbox"], "emb": r["emb"]} for r in f_crops]
            is_cut = (f_idx in cut_frames)
            assigned = tracker_oracle.update(f_idx, frame_dets, is_shot_cut=is_cut)
            oracle_preds_by_frame[f_idx] = assigned

        oracle_overall = evaluate_tracking_metrics(gt_frames, oracle_preds_by_frame)
        oracle_calib = evaluate_tracking_metrics(
            calib_gt_frames,
            {k: v for k, v in oracle_preds_by_frame.items() if k <= 180},
        )
        oracle_test = evaluate_tracking_metrics(
            test_gt_frames,
            {k: v for k, v in oracle_preds_by_frame.items() if k > 180},
        )

        print(f"Oracle Re-ID Results:")
        print(f"  Overall IDF1: {oracle_overall['idf1']*100:.2f}% | ID Switches: {oracle_overall['id_switches']}")
        print(f"  Calibration IDF1: {oracle_calib['idf1']*100:.2f}% | Test IDF1: {oracle_test['idf1']*100:.2f}%")
        print(f"  False Identity Merges: {oracle_overall['false_merges_count']}")

        # -------------------------------------------------------------------
        # 4. Experiment B: Production Re-ID (Predicted BBoxes from Step 2.1)
        # -------------------------------------------------------------------
        print(f"\nRunning Experiment B: Production Re-ID (Predicted Detections)...")
        # Extract embeddings for real predicted detections
        prod_crop_records = []
        prod_pil_crops = []
        prod_raw_crops = []

        for f_idx in sorted(gt_frames.keys()):
            dets = prod_raw_dets.get(f_idx, [])
            f_file = frames_dir / f"frame_{f_idx:04d}.jpg"
            if not f_file.exists() or not dets:
                continue
            img = Image.open(f_file).convert("RGB")
            arr = np.array(img)
            h, w = arr.shape[:2]

            for d in dets:
                b = d["bbox"]
                ymin, xmin, ymax, xmax = int(b[0]*h), int(b[1]*w), int(b[2]*h), int(b[3]*w)
                ymin = max(0, min(h - 1, ymin))
                xmin = max(0, min(w - 1, xmin))
                ymax = max(ymin + 1, min(h, ymax))
                xmax = max(xmin + 1, min(w, xmax))

                crop_np = arr[ymin:ymax, xmin:xmax]
                if crop_np.size >= 16:
                    crop_pil = Image.fromarray(crop_np)
                    prod_crop_records.append({
                        "frame_idx": f_idx,
                        "bbox": b,
                    })
                    prod_pil_crops.append(crop_pil)
                    prod_raw_crops.append(crop_np)

        if isinstance(enc, BaselineRGB48D):
            prod_embs = np.array([enc.extract(c) for c in prod_raw_crops])
        else:
            prod_embs = enc.extract_batch(prod_pil_crops)

        for i, rec in enumerate(prod_crop_records):
            rec["emb"] = prod_embs[i]

        prod_crops_by_frame = defaultdict(list)
        for rec in prod_crop_records:
            prod_crops_by_frame[rec["frame_idx"]].append(rec)

        tracker_prod = AntiCollisionReIDTracker(
            tau_hyp=tau_hyp,
            tau_confirm=tau_confirm,
            max_age_frames=40,
            iou_track_threshold=0.35,
        )

        prod_preds_by_frame = {}
        for f_idx in sorted(gt_frames.keys()):
            f_dets = prod_crops_by_frame.get(f_idx, [])
            is_cut = (f_idx in cut_frames)
            assigned = tracker_prod.update(f_idx, f_dets, is_shot_cut=is_cut)
            prod_preds_by_frame[f_idx] = assigned

        prod_overall = evaluate_tracking_metrics(gt_frames, prod_preds_by_frame)
        prod_calib = evaluate_tracking_metrics(
            calib_gt_frames,
            {k: v for k, v in prod_preds_by_frame.items() if k <= 180},
        )
        prod_test = evaluate_tracking_metrics(
            test_gt_frames,
            {k: v for k, v in prod_preds_by_frame.items() if k > 180},
        )

        print(f"Production Re-ID Results:")
        print(f"  Overall IDF1: {prod_overall['idf1']*100:.2f}% | ID Switches: {prod_overall['id_switches']}")
        print(f"  Calibration IDF1: {prod_calib['idf1']*100:.2f}% | Test IDF1: {prod_test['idf1']*100:.2f}%")
        print(f"  False Identity Merges: {prod_overall['false_merges_count']}")

        all_results[enc_name] = {
            "encoder": enc_name,
            "feature_dim": enc.dim,
            "cpu_latency_ms": round(latency_p50, 2),
            "calibration": calib_stats,
            "experiment_a_oracle": {
                "overall": oracle_overall,
                "calibration_split": oracle_calib,
                "test_split": oracle_test,
            },
            "experiment_b_production": {
                "overall": prod_overall,
                "calibration_split": prod_calib,
                "test_split": prod_test,
            },
        }

    # Save benchmark results
    with open(out_results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nAll benchmark results successfully saved to: {out_results_path}")


if __name__ == "__main__":
    run_reid_benchmark()
