"""Test and evaluate Active Speaker Binding logic on 180s benchmark."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
from scipy.optimize import linear_sum_assignment


class AcousticDiarizer:
    def __init__(self, model_path: str, sim_threshold: float = 0.50):
        self.sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.sim_threshold = sim_threshold
        self.clusters: list[dict] = []  # {'id': str, 'exemplars': list[np.ndarray], 'centroid': np.ndarray}
        self.latencies_ms: list[float] = []

    def extract_embedding(self, slice_wav: torch.Tensor) -> np.ndarray:
        t0 = time.perf_counter()
        fbank = kaldi.fbank(slice_wav, num_mel_bins=80)
        inp = fbank.unsqueeze(0).numpy()
        emb = self.sess.run(None, {"x": inp})[0][0]
        self.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        emb = emb / (np.linalg.norm(emb) + 1e-8)
        return emb

    def assign_or_create(self, emb: np.ndarray) -> tuple[str, float]:
        best_sim = -1.0
        best_idx = -1
        for idx, c in enumerate(self.clusters):
            # Cosine similarity to centroid or max exemplar
            sim = float(np.dot(emb, c["centroid"]))
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_sim >= self.sim_threshold and best_idx >= 0:
            c = self.clusters[best_idx]
            c["exemplars"].append(emb)
            # Update centroid
            c["centroid"] = np.mean(c["exemplars"], axis=0)
            c["centroid"] = c["centroid"] / (np.linalg.norm(c["centroid"]) + 1e-8)
            return c["id"], best_sim
        else:
            new_id = f"speaker_audio_{len(self.clusters) + 1:02d}"
            self.clusters.append({
                "id": new_id,
                "exemplars": [emb],
                "centroid": emb.copy(),
            })
            return new_id, 1.0


def compute_der_and_jer(turns: list[dict], pred_audio_ids: list[str]) -> tuple[float, float, dict]:
    """Compute Diarization Error Rate and Jaccard Error Rate via Hungarian matching."""
    true_spks = [t["speaker"] for t in turns]
    durations = [t["end_sec"] - t["start_sec"] for t in turns]
    total_duration = sum(durations)

    all_true = sorted(list(set(true_spks)))
    all_pred = sorted(list(set(pred_audio_ids)))

    true_idx = {s: i for i, s in enumerate(all_true)}
    pred_idx = {s: i for i, s in enumerate(all_pred)}

    # Cost matrix: overlap duration
    overlap = np.zeros((len(all_true), len(all_pred)), dtype=np.float64)
    for t_s, p_s, dur in zip(true_spks, pred_audio_ids, durations):
        overlap[true_idx[t_s], pred_idx[p_s]] += dur

    r, c = linear_sum_assignment(-overlap)
    mapped_pred_to_true = {all_pred[ci]: all_true[ri] for ri, ci in zip(r, c)}

    # DER
    error_duration = 0.0
    for t_s, p_s, dur in zip(true_spks, pred_audio_ids, durations):
        mapped = mapped_pred_to_true.get(p_s)
        if mapped != t_s:
            error_duration += dur
    der = error_duration / total_duration if total_duration > 0 else 0.0

    # JER (Jaccard Error Rate)
    true_totals = defaultdict(float)
    pred_totals = defaultdict(float)
    for t_s, p_s, dur in zip(true_spks, pred_audio_ids, durations):
        true_totals[t_s] += dur
        pred_totals[p_s] += dur

    jers = []
    for ri, ci in zip(r, c):
        t_s = all_true[ri]
        p_s = all_pred[ci]
        inter = overlap[ri, ci]
        union = true_totals[t_s] + pred_totals[p_s] - inter
        j_err = 1.0 - (inter / union) if union > 0 else 0.0
        jers.append(j_err)

    jer = float(np.mean(jers)) if jers else 0.0
    return round(der, 4), round(jer, 4), mapped_pred_to_true


def run_test():
    gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
    wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
    model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    wav_np, sr = sf.read(wav_path)
    waveform = torch.from_numpy(wav_np).float().unsqueeze(0)

    speech_events = gt["speech_events"]
    gt_frames = {f["frame_idx"]: f for f in gt["frames"]}

    print("Evaluating acoustic diarization across thresholds...")
    best_der = 999.0
    best_thresh = 0.50
    for thresh in [0.42, 0.45, 0.48, 0.50, 0.52, 0.55]:
        diarizer = AcousticDiarizer(str(model_path), sim_threshold=thresh)
        pred_ids = []
        for sp in speech_events:
            start_sample = int(sp["start_sec"] * sr)
            end_sample = int(sp["end_sec"] * sr)
            slice_wav = waveform[:, start_sample:end_sample]
            emb = diarizer.extract_embedding(slice_wav)
            spk_id, _ = diarizer.assign_or_create(emb)
            pred_ids.append(spk_id)

        der, jer, mapping = compute_der_and_jer(speech_events, pred_ids)
        print(f"  Thresh {thresh:.2f}: Clusters={len(diarizer.clusters):2d} | DER={der*100:5.2f}% | JER={jer*100:5.2f}%")
        if der < best_der:
            best_der = der
            best_thresh = thresh

    print(f"\nBest acoustic threshold: {best_thresh:.2f} with DER={best_der*100:.2f}%")


if __name__ == "__main__":
    run_test()
