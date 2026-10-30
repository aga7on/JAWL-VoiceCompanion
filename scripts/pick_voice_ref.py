"""Pick a clean single-speaker reference segment for OmniVoice cloning.

Scans candidate windows of the 5-minute source, transcribes each with
GigaAM (crispasr), and keeps the first segment that:
  - has no dialogue markers ("—") or second-person switches,
  - is 6-10 s long,
  - transcribes confidently (non-empty).

Writes runtime/models/asr/voice_ref_aleksandra.wav + prints its transcript
for the wrapper default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
SOURCE = Path(r"G:\AI\kyutai-ru\voice\RU_Famale_ALEKSANDRA_KOSTINSKAYa.mp3")
OUT = ROOT / "runtime" / "models" / "asr" / "voice_ref_aleksandra.wav"
CRISP = r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe"
MODEL = r"G:\AI\JAWL-VoiceCompanion\runtime\models\asr\gigaam-v3-e2e-rnnt-q8_0.gguf"


def transcribe(wav: Path) -> str:
    result = subprocess.run(
        [CRISP, "--model", MODEL, "--file", str(wav)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line and not line.startswith("gigaam") and not line.startswith("=="):
            return line
    return ""


def main() -> int:
    data, sr = sf.read(SOURCE, dtype="float32", always_2d=True)
    mono = data.T.mean(axis=0)
    print(f"source: {len(mono)/sr:.1f} s @ {sr} Hz")

    # Candidate windows: every 20 s, 8 s long, skipping the first 15 s
    # (already known to be a two-voice dialogue).
    for start in range(15, int(len(mono)/sr) - 10, 20):
        seg = mono[int(start*sr):int((start+8)*sr)]
        temp = ROOT / "runtime" / "models" / "asr" / "_ref_candidate.wav"
        sf.write(temp, seg, sr)
        text = transcribe(temp).strip()
        if not text or len(text) < 30:
            continue
        if "—" in text or " - " in text:
            print(f"[{start:3d}s] dialogue, skip: {text[:60]}")
            continue
        print(f"[{start:3d}s] clean: {text}")
        sf.write(OUT, seg, sr)
        temp.unlink(missing_ok=True)
        print(f"\nREF WRITTEN: {OUT} ({len(seg)/sr:.1f} s)")
        print(f"REF TEXT: {text}")
        return 0
    temp = ROOT / "runtime" / "models" / "asr" / "_ref_candidate.wav"
    temp.unlink(missing_ok=True)
    print("no clean segment found")
    return 1


if __name__ == "__main__":
    sys.exit(main())