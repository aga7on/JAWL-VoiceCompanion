"""Generates authentic Russian WAV fixtures for Step 2.7 acceptance testing via OmniVoice on GPU 1."""

import io
import sys
import time
import wave
from pathlib import Path
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
for candidate in (
    ROOT / "runtime" / "OmniVoice",
    Path(r"G:\AI\OmniVoice"),
    Path(r"G:\AI\OmniVoice\omnivoice"),
):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from omnivoice import OmniVoice

MODEL_DIR = ROOT / "runtime" / "models" / "tts" / "k2-fsa-OmniVoice"
REF_WAV = ROOT / "runtime" / "models" / "tts" / "refs" / "ru_ref.wav"
REF_TEXT = "Привет! Я твой голосовой компаньон, рад тебя слышать."
OUT_DIR = ROOT / "runtime" / "instances" / "test_step27_e2e" / "queries"
OUT_DIR.mkdir(parents=True, exist_ok=True)

QUERIES = {
    "query1_screen.wav": "Что сейчас видно на экране?",
    "query2_recall.wav": "Что мы только что видели на экране?",
    "query3_cancel.wav": "Расскажи подробно и длинно о том, что происходит вокруг.",
}

print(f"Loading OmniVoice model on cuda:1...")
t0 = time.perf_counter()
model = OmniVoice.from_pretrained(str(MODEL_DIR), device_map="cuda:1", dtype=torch.float16)
print(f"Loaded OmniVoice in {time.perf_counter() - t0:.2f}s")

for filename, text in QUERIES.items():
    out_path = OUT_DIR / filename
    print(f"Generating '{text}' -> {out_path.name}...")
    t_gen = time.perf_counter()
    audio = model.generate(text=text, ref_audio=str(REF_WAV), ref_text=REF_TEXT)
    samples = audio[0]
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.abs(values).max()) if values.size else 0.0
    if peak > 0.9:
        values = values * (0.9 / peak)
    pcm = (values.clip(-1.0, 1.0) * 32767.0).astype("<i2")

    with wave.open(str(out_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(pcm.tobytes())
    print(f"  -> Wrote {out_path.stat().st_size} bytes in {time.perf_counter() - t_gen:.2f}s")

del model
torch.cuda.empty_cache()
print("All query fixtures successfully generated.")
