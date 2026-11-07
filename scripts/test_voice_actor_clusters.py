"""Test multimodal speaker binding with voice actor clustering + scene character context."""

import json
from pathlib import Path
from collections import defaultdict
import numpy as np
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort

gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

with open(gt_path, "r", encoding="utf-8") as f:
    gt = json.load(f)

wav_np, sr = sf.read(wav_path)
waveform = torch.from_numpy(wav_np).float().unsqueeze(0)
sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

events = gt["speech_events"]
gt_frames = {f["frame_idx"]: f for f in gt["frames"]}
catalog = gt["character_catalog"]

# Step 1: Extract all embeddings
embs = []
for sp in events:
    s = int(sp["start_sec"] * sr)
    e = int(sp["end_sec"] * sr)
    sl = waveform[:, s:e]
    fbank = kaldi.fbank(sl, num_mel_bins=80)
    emb = sess.run(None, {"x": fbank.unsqueeze(0).numpy()})[0][0]
    emb /= (np.linalg.norm(emb) + 1e-8)
    embs.append(emb)

embs = np.array(embs)

# Let's inspect clustering: how many acoustic voice actors are detected?
# With 2 reference anchors or clustering threshold
# Let's see: Turn 1 is rival (female), Turn 2 is glasses (male)
# Turn 1 and Turn 2 have cos sim:
sim_1_2 = float(np.dot(embs[0], embs[1]))
print(f"Cosine sim between Turn 1 (female anchor) and Turn 2 (male anchor): {sim_1_2:.4f}")

# Acoustic gender assignment based on cosine to female anchor vs male anchor
# (Or online clustering)
# Let's test online clustering with 2 primary voice actor clusters:
clusters = []
for i, emb in enumerate(embs):
    if len(clusters) < 2:
        clusters.append({"id": f"voice_{i+1:02d}", "centroid": emb.copy(), "exemplars": [emb]})
    else:
        # compare to clusters
        sims = [float(np.dot(emb, c["centroid"])) for c in clusters]
        best_c = np.argmax(sims)
        clusters[best_c]["exemplars"].append(emb)
        clusters[best_c]["centroid"] = np.mean(clusters[best_c]["exemplars"], axis=0)
        clusters[best_c]["centroid"] /= np.linalg.norm(clusters[best_c]["centroid"])

print(f"Voice actor clusters formed: {len(clusters)}")
print(f"Cluster 1 size: {len(clusters[0]['exemplars'])}, Cluster 2 size: {len(clusters[1]['exemplars'])}")
