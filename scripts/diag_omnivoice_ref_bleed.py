"""Diagnose the OmniVoice reference-phrase bleed observed on generated fixtures.

Observed: GigaAM transcripts of generated WAVs began with the reference text
("Привет! Я твой голосовой компаньон...") before the requested sentence.
This probe isolates whether the bleed comes from the reference prompt reaching
the model, by comparing generation modes on one short, unambiguous sentence.
"""

from __future__ import annotations

import io
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime" / "omnivoice-venv" / "Lib" / "site-packages"))

import numpy as np  # noqa: E402

from omnivoice import OmniVoice  # noqa: E402

MODEL_DIR = ROOT / "runtime" / "models" / "tts" / "k2-fsa-OmniVoice"
REF_WAV = ROOT / "runtime" / "models" / "tts" / "refs" / "voice_ref_aleksandra.wav"
REF_TEXT = "Привет! Я твой голосовой компаньон, рад тебя слышать."
TEXT = "Какой сегодня статус моего проекта?"
OUT = ROOT / "runtime" / "omnivoice-diagnostic"


def to_wav(samples: np.ndarray) -> bytes:
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.abs(values).max()) if values.size else 0.0
    if peak > 0.9:
        values = values * (0.9 / peak)
    pcm = (values.clip(-1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading model (cpu)...", flush=True)
    began = time.perf_counter()
    model = OmniVoice.from_pretrained(str(MODEL_DIR), device_map="cpu", dtype="float32")
    print(f"loaded in {time.perf_counter() - began:.1f}s", flush=True)

    cases = {
        # Current server behaviour: ref audio + ref text every call.
        "a_ref_text": dict(ref_audio=str(REF_WAV), ref_text=REF_TEXT),
        # Reference audio only: no reference transcript to be spoken.
        "b_ref_audio_only": dict(ref_audio=str(REF_WAV)),
        # No reference at all: model picks its own voice.
        "c_no_ref": dict(),
    }

    for name, kwargs in cases.items():
        began = time.perf_counter()
        try:
            with __import__("torch").inference_mode():
                audio = model.generate(text=TEXT, **kwargs)
            wav = to_wav(audio[0])
            target = OUT / f"{name}.wav"
            target.write_bytes(wav)
            print(f"{name}: {len(wav)} B in {time.perf_counter() - began:.1f}s -> {target.name}", flush=True)
        except Exception as exc:  # noqa: BLE001 - diagnostic probe
            print(f"{name}: FAILED {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())