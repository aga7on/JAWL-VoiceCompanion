"""Replay the five local QA audio clips through YAMNet's unverified SFX lane.

Only model class names, raw scores, and window counts are persisted. PCM is
decoded in memory and is never copied into the output artifact.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.yamnet_soundscape import EVENT_THRESHOLD, YamnetSoundscapeDetector


ROOT = Path(__file__).resolve().parents[1]
CLIP_DIR = ROOT / "runtime/multimodal-realclips-20261024/probes/lowrate"
CLIPS = (
    "01_ru_trailer",
    "02_anime",
    "03_gameplay",
    "04_coding_ui",
    "05_aqua_song",
)


def read_pcm(path: Path) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"expected PCM16 WAV: {path.name}")
        return source.readframes(source.getnframes()), source.getframerate(), source.getnchannels()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "runtime/audio-path-replay/out/yamnet-events-realclips-20261029.json",
    )
    args = parser.parse_args()
    missing = [str(CLIP_DIR / f"{clip}.wav") for clip in CLIPS if not (CLIP_DIR / f"{clip}.wav").is_file()]
    if missing:
        raise FileNotFoundError("missing local probe clips: " + ", ".join(missing))

    detector = YamnetSoundscapeDetector()
    cases = []
    for clip in CLIPS:
        pcm, rate, channels = read_pcm(CLIP_DIR / f"{clip}.wav")
        result = detector.describe(pcm, sample_rate=rate, channels=channels, clip_id=clip)
        cases.append({
            "id": clip,
            "kind": result["kind"],
            "windows": result["windows"],
            "music_windows": result["music_windows"],
            "event_candidates": result["event_candidates"],
        })

    output = {
        "schema_version": 1,
        "model": detector.name,
        "cpu_only": True,
        "raw_audio_persisted": False,
        "event_candidates_are_verified_facts": False,
        "event_score_threshold": EVENT_THRESHOLD,
        "required_window_hits": "max(2, ceil(window_count * 0.25))",
        "clips": cases,
    }
    target = args.output if args.output.is_absolute() else ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case in cases:
        print(f"{case['id']}: music={case['kind']}, event_candidates={case['event_candidates']}")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
