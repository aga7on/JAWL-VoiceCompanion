"""Exemplar-based clustering without centroid drift."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort
from scipy.optimize import linear_sum_assignment

gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

with open(gt_path, "r", encoding="utf-8") as f:
    gt = json.load(f)

wav_np, sr = sf.read(wav_path)
waveform = torch.from_numpy(wav_np).float().unsqueeze(0)
sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

speech_events = gt["speech_events"]
embs = []
for sp in speech_events:
    s = int(sp["start_sec"] * sr)
    e = int(sp["end_sec"] * sr)
    sl = waveform[:, s:e]
    emb = sess.run(None, {"x": kaldi.fbank(sl, num_mel_bins=80).unsqueeze(0).numpy()})[0][0]
    embs.append(emb / (np.linalg.norm(emb) + 1e-8))

embs = np.array(embs)

# Let's test clustering with:
# A) Max exemplar similarity (complete/single linkage)
# B) Seed exemplar only (no drift)
# C) Average exemplar similarity
for method in ["seed_only", "average_exemplar", "max_exemplar"]:
    for th in [0.45, 0.50, 0.55, 0.60, 0.65]:
        clusters = []  # list of list of embs
        pred_ids = []
        for emb in embs:
            best_score = -1.0
            best_c = -1
            for ci, c in enumerate(clusters):
                if method == "seed_only":
                    score = float(np.dot(emb, c[0]))
                elif method == "average_exemplar":
                    score = float(np.mean([np.dot(emb, ex) for ex in c]))
                elif method == "max_exemplar":
                    score = float(np.max([np.dot(emb, ex) for ex in c]))
                if score > best_score:
                    best_score = score
                    best_c = ci
            if best_score >= th and best_c >= 0:
                clusters[best_c].append(emb)
                pred_ids.append(f"spk_{best_c:02d}")
            else:
                new_c = [emb]
                clusters.append(new_c)
                pred_ids.append(f"spk_{len(clusters)-1:02d}")

        # Compute DER
        true_spks = [sp["speaker"] for sp in speech_events]
        durations = [sp["end_sec"] - sp["start_sec"] for sp in speech_events]
        all_true = sorted(list(set(true_spks)))
        all_pred = sorted(list(set(pred_ids)))
        cost = np.zeros((len(all_true), len(all_pred)))
        for ts, ps, d in zip(true_spks, pred_ids, durations):
            cost[all_true.index(ts), all_pred.index(ps)] += d
        r, c = linear_sum_assignment(-cost)
        mapped = {all_pred[ci]: all_true[ri] for ri, ci in zip(r, c)}
        err_d = sum(d for ts, ps, d in zip(true_spks, pred_ids, durations) if mapped.get(ps) != ts)
        der = err_d / sum(durations)
        print(f"Method: {method:16s} | Thresh: {th:.2f} | Clusters: {len(clusters):2d} | DER: {der*100:5.2f}%")
