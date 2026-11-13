"""Find a working OmniVoice generation mode that speaks the requested text.

Confirmed defect: with ``ref_audio`` + ``ref_text`` the model emits the
reference sentence instead of (or before) the target sentence. That makes the
production TTS lane unusable for real answers. This probe compares the
remaining candidate modes on one unambiguous sentence.
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
import soundfile as sf  # noqa: E402
import torch  # noqa: E402

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
    model = OmniVoice.from_pretrained(str(MODEL_DIR), device_map="cpu", dtype="float32")
    print("model loaded", flush=True)

    waveform, rate = sf.read(str(REF_WAV), dtype="float32")
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    print(f"ref audio: {waveform.shape[0]} samples @ {rate} Hz", flush=True)

    prompt = None
    try:
        prompt = model.create_voice_clone_prompt(
            ref_audio=(torch.from_numpy(waveform), rate), ref_text=REF_TEXT
        )
        print("voice_clone_prompt created", flush=True)
    except Exception as exc:  # noqa: BLE001 - probe
        print(f"create_voice_clone_prompt FAILED: {type(exc).__name__}: {exc}", flush=True)

    cases = {
        "d_ref_tuple": dict(ref_audio=(torch.from_numpy(waveform), rate), ref_text=REF_TEXT),
        "e_prompt": dict(voice_clone_prompt=prompt) if prompt is not None else None,
        "f_noref_lang": dict(language="ru"),
        "g_instruct": dict(instruct="Спокойный женский голос, чистая русская речь."),
    }

    for name, kwargs in cases.items():
        if kwargs is None:
            print(f"{name}: SKIPPED (prompt unavailable)", flush=True)
            continue
        began = time.perf_counter()
        try:
            with torch.inference_mode():
                audio = model.generate(text=TEXT, **kwargs)
            wav = to_wav(audio[0])
            (OUT / f"{name}.wav").write_bytes(wav)
            print(f"{name}: {len(wav)} B in {time.perf_counter() - began:.1f}s", flush=True)
        except Exception as exc:  # noqa: BLE001 - probe
            print(f"{name}: FAILED {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())