"""R2T2 RU smoke: transcribe multiple Russian WAVs in one run.

Usage: python -X utf8 scripts/run_r2t2_ru_smoke.py [r2t2_model_dir] [language=Russian] [wav1 wav2 ...]
Prints transcript per WAV with durations; exit 0 on success.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("R2T2_REPO", r"G:\AI\_tmp\companion-repos\r2t2"))
DEFAULT_WAVS = [
    r"G:\AI\JAWL-VoiceCompanion\runtime\voice-native-ru-clean-20260906.wav",
    r"G:\AI\JAWL-VoiceCompanion\runtime\voice-native-command-20260906.wav",
    r"G:\AI\JAWL-VoiceCompanion\runtime\bench\rumbench_ru\ref_ru.wav",
]


def main() -> int:
    args = sys.argv[1:]
    model_dir = Path(args[0]) if args else Path(r"G:\AI\JAWL-VoiceCompanion\runtime\models\r2t2")
    # After model_dir, optional language; first non-flag positional afterwards is a WAV.
    language = "Russian"
    wavs: list[str] = []
    for tok in args[1:]:
        if tok.lower().startswith(("russian", "english", "chinese", "auto")):
            language = tok
        elif tok != "auto":
            wavs.append(tok)
    if not wavs:
        wavs = DEFAULT_WAVS

    missing = [w for w in wavs if not Path(w).exists()]
    if missing:
        print(f"WAV не найден: {missing}", file=sys.stderr)
        return 2
    if not (model_dir / "model.safetensors").exists():
        print(f"Веса R2T2 ещё не скачаны: {model_dir}", file=sys.stderr)
        return 3

    sys.path.insert(0, str(REPO))
    from r2t2 import R2T2ASRModel

    print(f"Загрузка R2T2 из {model_dir} ...", flush=True)
    t0 = time.perf_counter()
    model = R2T2ASRModel.from_pretrained(str(model_dir))
    model.model.eval()
    print(f"Загрузка модели: {time.perf_counter() - t0:.1f}s", flush=True)

    for wav in wavs:
        name = Path(wav).name
        t1 = time.perf_counter()
        try:
            results = model.transcribe(wav, language=language, context="")
            dt = time.perf_counter() - t1
            result = results[0]
            text = result.text if hasattr(result, "text") else str(result)
            detected = getattr(result, "language", "") or ""
            print(f"== {name} ({dt:.1f}s, {detected})")
            print(f"   {text}")
        except Exception as exc:  # noqa: BLE001
            print(f"== {name} ERROR: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())