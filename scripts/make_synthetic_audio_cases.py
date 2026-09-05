"""Deterministic synthetic acoustic cases from one clean PCM16 WAV fixture.

Generates tempo-slow, paused, quiet, noisy, phrase-end and consecutive-phrase
variants of a source utterance using only the Python stdlib. The produced
cases.json manifest is consumed by run_asr_profile --expects so the synthetic
ASR profile can distinguish speech that must be transcribed from tolerated
no-speech inputs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_RATE = 8000
MAX_CASE_SECONDS = 60.0


def _read_mono_pcm16(path: Path) -> tuple[int, list[int]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        if channels not in {1, 2} or width != 2 or rate < MIN_RATE:
            raise ValueError("source WAV must be PCM16 mono or stereo")
        frames = wav.readframes(wav.getnframes())
    if channels == 1:
        return rate, [int.from_bytes(frames[i : i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
    mono: list[int] = []
    for i in range(0, len(frames), 4):
        left = int.from_bytes(frames[i : i + 2], "little", signed=True)
        right = int.from_bytes(frames[i + 2 : i + 4], "little", signed=True)
        mono.append((left + right) // 2)
    return rate, mono


def _write_mono_pcm16(path: Path, rate: int, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(int(frame).to_bytes(2, "little", signed=True) for frame in samples))


def _silence(rate: int, seconds: float) -> list[int]:
    return [0] * max(0, int(rate * seconds))


def _gain_db(samples: list[int], decibels: float) -> list[int]:
    factor = 10.0 ** (decibels / 20.0)
    return [int(round(frame * factor)) for frame in samples]


def _stretch(samples: list[int], factor: float) -> list[int]:
    if factor < 1.0:
        raise ValueError("stretch factor must be >= 1.0")
    width = max(1, int(round(factor)))
    stretched: list[int] = []
    for frame in samples:
        stretched.extend([frame] * width)
    return stretched


def _rms(samples: list[int]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(frame * frame for frame in samples) / len(samples))


def _add_white_noise(samples: list[int], snr_db: float, rng: random.Random) -> list[int]:
    speech_rms = _rms(samples) or 1.0
    noise_sigma = speech_rms / (10.0 ** (snr_db / 20.0))
    return [int(round(frame + rng.gauss(0.0, noise_sigma))) for frame in samples]


def _noise_like(samples: list[int], rng: random.Random) -> list[int]:
    target_rms = _rms(samples) or 1.0
    return [int(round(rng.gauss(0.0, target_rms))) for _ in samples]


def _seconds(samples: list[int], rate: int) -> float:
    return round(len(samples) / rate, 3)


def make_cases(source_path: Path, out_dir: Path, seed: int = 7) -> dict[str, Any]:
    source_path = Path(source_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rate, src = _read_mono_pcm16(source_path)
    src_rms = _rms(src)
    rng = random.Random(seed)
    speech_notes = {"must_transcribe": True, "min_chars": 1}
    two_phrase = {"must_transcribe": True, "min_chars": 2}
    tolerated = {"must_transcribe": False, "min_chars": 0}

    cases: list[dict[str, Any]] = []

    def add(name: str, case: str, samples: list[int], exp: dict[str, Any], note: str) -> None:
        _write_mono_pcm16(out_dir / name, rate, samples)
        cases.append({
            "file": name,
            "case": case,
            "must_transcribe": bool(exp["must_transcribe"]),
            "min_chars": int(exp["min_chars"]),
            "duration_seconds": _seconds(samples, rate),
            "note": note,
        })

    add("tempo_slow.wav", "tempo_slow", _stretch(src, 2.0), speech_notes,
        "speech stretched to roughly 2-3 words per second")
    add("pause_short.wav", "pause", src + _silence(rate, 0.5), speech_notes,
        "short trailing phrasing pause")
    add("pause_long.wav", "pause", src + _silence(rate, 2.0), speech_notes,
        "long trailing phrasing pause")
    add("quiet.wav", "quiet", _gain_db(src, -18.0), speech_notes,
        "quiet speech 18 dB below the fixture level")
    add("faint.wav", "quiet", _gain_db(src, -26.0), tolerated,
        "faint speech near the noise floor; empty transcript tolerated")
    add("noisy_snr10.wav", "noise", _add_white_noise(src, 10.0, rng), speech_notes,
        "white noise mixed at 10 dB SNR")
    add("noisy_snr0.wav", "noise", _add_white_noise(src, 0.0, rng), tolerated,
        "speech fully masked at 0 dB SNR; empty transcript tolerated")
    add("noise_only.wav", "noise", _noise_like(src, rng), tolerated,
        "noise floor only; empty transcript tolerated")
    add("phrase_end_0.wav", "phrase_end", src, speech_notes,
        "phrase ending without trailing silence")
    add("phrase_end_400.wav", "phrase_end", src + _silence(rate, 0.4), speech_notes,
        "phrase ending with 400 ms trail")
    add("phrase_end_800.wav", "phrase_end", src + _silence(rate, 0.8), speech_notes,
        "phrase ending with 800 ms trail")
    add("consecutive_two.wav", "consecutive", src + _silence(rate, 0.5) + src, two_phrase,
        "two phrases back to back",)

    for item in cases:
        if item["duration_seconds"] > MAX_CASE_SECONDS:
            raise ValueError(f"case {item['file']} exceeds the {MAX_CASE_SECONDS}s bound")

    manifest = {
        "schema_version": 1,
        "source": source_path.name,
        "source_rate": rate,
        "source_rms": round(src_rms, 3),
        "source_duration_seconds": round(len(src) / rate, 3),
        "seed": seed,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    (out_dir / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic acoustic cases")
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not Path(args.wav).is_file():
        raise SystemExit(f"source WAV is missing: {args.wav}")
    manifest = make_cases(args.wav, args.out, seed=args.seed)
    print(json.dumps({"status": "ok", "out": str(Path(args.out)), "cases": len(manifest["cases"])}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())