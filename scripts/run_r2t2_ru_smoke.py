"""R2T2 RU smoke: transcribe a Russian WAV, one-shot (offline) via transformers backend.

Usage: python -X utf8 scripts/run_r2t2_ru_smoke.py <r2t2_model_dir> <ru_wav> [language=Russian]
Prints the transcript; exit 0 on success.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("R2T2_REPO", r"G:\AI\_tmp\companion-repos\r2t2"))


def main() -> int:
    model_dir = Path(sys.argv[1] if len(sys.argv) > 1 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\r2t2")
    wav = Path(sys.argv[2] if len(sys.argv) > 2 else r"G:\AI\JAWL-VoiceCompanion\runtime\voice-native-ru-clean-20260906.wav")
    language = sys.argv[3] if len(sys.argv) > 3 else "Russian"
    if not wav.exists():
        print(f"RU-файл не найден: {wav}", file=sys.stderr)
        return 2
    if not (model_dir / "model.safetensors").exists():
        print(f"Веса R2T2 ещё не скачаны: {model_dir}", file=sys.stderr)
        return 3

    sys.path.insert(0, str(REPO))
    import librosa
    import numpy as np
    from r2t2 import R2T2ASRModel

    print(f"Загрузка R2T2 из {model_dir} ...")
    model = R2T2ASRModel.from_pretrained(str(model_dir))
    model.model.eval()

    audio, sr = librosa.load(str(wav), sr=None, mono=True)
    if sr != 16000:
        dur = audio.shape[0] / sr
        n = int(round(dur * 16000))
        x = np.linspace(0.0, dur, num=audio.shape[0], endpoint=False)
        xn = np.linspace(0.0, dur, num=n, endpoint=False)
        audio = np.interp(xn, x, audio).astype(np.float32)
    else:
        audio = audio.astype(np.float32)

    print(f"Аудио: {audio.shape[0] / 16000:.2f}s · язык={language}")
    results = model.transcribe(audio, language=language, context="")
    result = results[0]
    text = result.text if hasattr(result, "text") else str(result)
    detected = getattr(result, "language", "") or ""
    print(f"R2T2 transcript ({detected}): {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())