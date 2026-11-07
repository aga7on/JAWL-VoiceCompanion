import json
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
import torchaudio.compliance.kaldi as kaldi
import onnxruntime as ort

from test_speaker_graph import AudioVisualSpeakerGraph

gt_path = Path("runtime/instances/daily/data/sensory/youtube_watch/ground_truth_180s.json")
wav_path = Path("runtime/instances/daily/data/sensory/youtube_watch/episode1_180s_16k.wav")
model_path = Path("runtime/models/speaker/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")

with open(gt_path, "r", encoding="utf-8") as f:
    gt = json.load(f)

wav_np, sr = sf.read(wav_path)
waveform = torch.from_numpy(wav_np).float().unsqueeze(0)

events = gt["speech_events"]
gt_frames = {f["frame_idx"]: f for f in gt["frames"]}

graph = AudioVisualSpeakerGraph(str(model_path), audio_sim_threshold=0.55)

print(f"{'Turn':4s} | {'True Spk':12s} | {'Pred Spk':14s} | {'Status':20s} | {'Audio ID':15s} | Match?")
print("-" * 75)
for e in events:
    s_samp = int(e["start_sec"] * sr)
    e_samp = int(e["end_sec"] * sr)
    sl = waveform[:, s_samp:e_samp]
    res = graph.process_turn_oracle(
        turn_id=e["turn_id"],
        start_sec=e["start_sec"],
        end_sec=e["end_sec"],
        slice_wav=sl,
        gt_frames=gt_frames,
    )
    ok = "OK" if res["character_id"] == e["speaker"] else "FAIL"
    print(f"{e['turn_id']:4d} | {e['speaker']:12s} | {res['character_id']:14s} | {res['binding_status']:20s} | {res['speaker_audio_id']:15s} | {ok}")
