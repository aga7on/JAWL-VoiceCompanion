"""Decide the OmniVoice mode for the production TTS lane.

Context: with the default ``preprocess_prompt=True`` the model speaks the
reference sentence instead of the request. With it disabled the request text is
correct but the reference prefix still bleeds into the output. This probe
measures the remaining candidates on one short sentence and leaves the WAVs for
GigaAM to score.
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
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig  # noqa: E402

MODEL_DIR = ROOT / "runtime" / "models" / "tts" / "k2-fsa-OmniVoice"
REF_WAV = ROOT / "runtime" / "models" / "tts" / "refs" / "voice_ref_aleksandra.wav"
REF_TEXT = "Привет! Я твой голосовой компаньон, рад тебя слышать."
TEXT = "Проверка точности синтеза."
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

    # A short reference may carry less speakable content into the prompt.
    short_n = int(3.0 * rate)
    short_wave = waveform[:short_n]
    short_text = "Привет! Я твой голосовой компаньон."

    def tensor(w):
        return (torch.from_numpy(np.ascontiguousarray(w)), rate)

    off = OmniVoiceGenerationConfig(preprocess_prompt=False)

    cases = {
        # reference audio only, no transcript to speak
        "j_audio_only": dict(kwargs=dict(ref_audio=tensor(waveform)), config=off),
        # reference audio + transcript, but a 3 s clip and matching short text
        "k_short_ref": dict(
            kwargs=dict(ref_audio=tensor(short_wave), ref_text=short_text), config=off
        ),
        # language-guided auto voice (already known good)
        "l_auto_ru": dict(kwargs=dict(language="ru"), config=off),
    }

    for name, spec in cases.items():
        began = time.perf_counter()
        try:
            with torch.inference_mode():
                audio = model.generate(
                    text=TEXT, generation_config=spec["config"], **spec["kwargs"]
                )
            wav = to_wav(audio[0])
            (OUT / f"{name}.wav").write_bytes(wav)
            print(f"{name}: {len(wav)} B in {time.perf_counter() - began:.1f}s", flush=True)
        except Exception as exc:  # noqa: BLE001 - probe
            print(f"{name}: FAILED {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())