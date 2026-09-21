"""GigaAM (canonical ASR) baseline on the same RU fixtures as the R2T2 smoke.

Runs the project's own CrispASRFileTranscriber so the comparison uses the
canonical code path, not a reimplementation.

Usage: python -X utf8 scripts/gigaam_baseline_fixtures.py [wav ...]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(r"G:\AI\JAWL-VoiceCompanion")
sys.path.insert(0, str(REPO / "src"))

from jawl_voicecompanion.giga_final import CrispASRFileTranscriber  # noqa: E402

CRISPASR = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
MODEL = Path(r"G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf")

DEFAULT_WAVS = [
    REPO / "runtime" / "voice-native-ru-clean-20260906.wav",
    REPO / "runtime" / "voice-native-command-20260906.wav",
    REPO / "runtime" / "bench" / "rumbench_ru" / "ref_ru.wav",
]


def main() -> int:
    wavs = [Path(p) for p in sys.argv[1:]] or DEFAULT_WAVS
    for path, label in ((CRISPASR, "crispasr"), (MODEL, "gigaam model")):
        if not path.exists():
            print(f"{label} not found: {path}", file=sys.stderr)
            return 2
    transcriber = CrispASRFileTranscriber(str(CRISPASR), str(MODEL))
    print(f"gigaam={MODEL.name}")
    for wav in wavs:
        if not wav.exists():
            print(f"{wav.name}: MISSING")
            continue
        payload = wav.read_bytes()
        t0 = time.perf_counter()
        try:
            text = transcriber.transcribe(payload)
            dt = time.perf_counter() - t0
            print(f"== {wav.name} ({dt:.1f}s)")
            print(f"   {text}")
        except Exception as exc:  # noqa: BLE001
            print(f"== {wav.name} ERROR: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
