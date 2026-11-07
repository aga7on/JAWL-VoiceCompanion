import json
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort
import numpy as np

gt_path = 'runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json'
wav_path = 'runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav'
model_path = 'runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx'

gt_data = json.load(open(gt_path, encoding='utf-8'))
speech_events = gt_data['speech_events']
wav_np, sr = sf.read(wav_path)
waveform = torch.from_numpy(wav_np).float().unsqueeze(0)
sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])

embs = []
spks = []
for sp in speech_events:
    start_sample = int(sp['start_sec'] * sr)
    end_sample = int(sp['end_sec'] * sr)
    slice_wav = waveform[:, start_sample:end_sample]
    fbank = kaldi.fbank(slice_wav, num_mel_bins=80)
    emb = sess.run(None, {'x': fbank.unsqueeze(0).numpy()})[0][0]
    emb = emb / (np.linalg.norm(emb) + 1e-8)
    embs.append(emb)
    spks.append(sp['speaker'])

embs = np.array(embs)
sim_mat = np.dot(embs, embs.T)

c_idx = [i for i, s in enumerate(spks) if s == 'p_curly']
print("=== p_curly Turns Similarity Breakdown ===")
for i in c_idx:
    sims = [sim_mat[i, j] for j in c_idx if i != j]
    sp = speech_events[i]
    dur = sp['end_sec'] - sp['start_sec']
    txt = sp['text'][:25]
    print(f"Turn {sp['turn_id']:2d} ({dur:4.1f}s, '{txt}'): mean={np.mean(sims):.3f}, min={np.min(sims):.3f}, max={np.max(sims):.3f}")
