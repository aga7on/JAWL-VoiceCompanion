"""CPU-only preflight for the pinned MusicNN tagger on local audio controls.

Stores only model tags, timings, source paths, and process memory. It does not
write audio or transcripts. The checkpoint is research-only and is never
loaded by the daily profile.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "runtime/models/audio/musicnn-pytorch-394be17"
DEFAULT_OUTPUT = ROOT / "runtime/audio-path-replay/out/musicnn-candidate-probe-20261024.json"
DEFAULT_CASES = {
    "bach_toccata": ROOT / "runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3",
    "saxophone_sample": ROOT / "runtime/vision-venv/Lib/site-packages/gradio/media_assets/audio/sax.wav",
    "music_fixture": ROOT / "runtime/gemma4-e4b-cpu/cases/music.wav",
    "russian_speech": ROOT / "runtime/gemma4-e4b-cpu/cases/ru_speech.wav",
    "speech_plus_music_fixture": ROOT / "runtime/gemma4-e4b-cpu/cases/speech_music.wav",
    "noise_control": ROOT / "runtime/gemma4-e4b-cpu/cases/noise.wav",
    "silence_control": ROOT / "runtime/gemma4-e4b-cpu/cases/silence.wav",
}
MTT_LABELS = [
    "guitar", "classical", "slow", "techno", "strings", "drums", "electronic", "rock",
    "fast", "piano", "ambient", "beat", "violin", "vocal", "synth", "female", "indian",
    "opera", "male", "singing", "vocals", "no vocals", "harpsichord", "loud", "quiet",
    "flute", "woman", "male vocal", "no vocal", "pop", "soft", "sitar", "solo", "man",
    "classic", "choir", "voice", "new age", "dance", "male voice", "female vocal",
    "beats", "harp", "cello", "no voice", "weird", "country", "metal", "female voice",
    "choral",
]


def _tag_scores(model: Any, torch: Any, path: Path, top_k: int) -> list[dict[str, Any]]:
    """Mirror the pinned model's own 187-frame window aggregation, retaining scores."""
    features = model.preprocess_audio(str(path))
    frames_per_window = 187
    last_start = features.shape[0] - frames_per_window + 1
    if last_start <= 0:
        padded = np.zeros((frames_per_window, 96), dtype=np.float32)
        padded[: features.shape[0], :] = features
        windows = [padded]
    else:
        windows = [
            features[start : start + frames_per_window]
            for start in range(0, last_start, frames_per_window)
        ]
    scores: list[np.ndarray] = []
    with torch.inference_mode():
        for window in windows:
            logits, _, _ = model(torch.from_numpy(window[None, ...]))
            scores.append(torch.sigmoid(logits).squeeze(0).cpu().numpy())
    mean_scores = np.mean(scores, axis=0)
    order = np.argsort(mean_scores)[::-1][:top_k]
    return [
        {"tag": MTT_LABELS[int(index)], "score": round(float(mean_scores[index]), 4)}
        for index in order
    ]


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 20:
        parser.error("--repeats must be between 1 and 20")
    if args.top_k < 1 or args.top_k > 50:
        parser.error("--top-k must be between 1 and 50")

    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        import torch
        from transformers import AutoModel
    except Exception as exc:
        print(f"candidate dependencies unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    torch.set_num_threads(1)
    if not MODEL_DIR.is_dir():
        print(f"pinned MusicNN checkpoint not found: {MODEL_DIR}", file=sys.stderr)
        return 2

    rss_before = _rss_bytes()
    started = time.perf_counter()
    try:
        model = AutoModel.from_pretrained(
            str(MODEL_DIR), trust_remote_code=True, local_files_only=True
        ).to("cpu").eval()
    except Exception as exc:
        print(f"MusicNN load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    load_seconds = time.perf_counter() - started
    devices = sorted({str(parameter.device) for parameter in model.parameters()})
    if devices != ["cpu"]:
        print(f"unexpected inference device(s): {devices}", file=sys.stderr)
        return 2

    cases: dict[str, Any] = {}
    for name, path in DEFAULT_CASES.items():
        if not path.is_file():
            cases[name] = {"available": False}
            continue
        timings: list[float] = []
        tags: list[dict[str, Any]] = []
        try:
            for _ in range(args.repeats):
                before = time.perf_counter()
                tags = _tag_scores(model, torch, path, args.top_k)
                timings.append(time.perf_counter() - before)
            cases[name] = {
                "available": True,
                "path": str(path.relative_to(ROOT)),
                "top_tags": tags,
                "repeat_count": len(timings),
                "latency_p50_ms": round(statistics.median(timings) * 1000, 1),
                "latency_max_ms": round(max(timings) * 1000, 1),
            }
        except Exception as exc:
            cases[name] = {
                "available": True,
                "path": str(path.relative_to(ROOT)),
                "error": f"{type(exc).__name__}: {exc}",
            }

    result = {
        "schema_version": 1,
        "model": "oriyonay/musicnn-pytorch",
        "revision": "394be17",
        "weights_bytes": (MODEL_DIR / "model.safetensors").stat().st_size,
        "torch_version": torch.__version__,
        "device": "cpu",
        "torch_threads": torch.get_num_threads(),
        "load_ms": round(load_seconds * 1000, 1),
        "rss_before_bytes": rss_before,
        "rss_after_load_bytes": _rss_bytes(),
        "top_k": args.top_k,
        "cases": cases,
        "raw_audio_persisted": False,
        "transcript_persisted": False,
        "notes": [
            "Tagger scores are not calibrated probabilities.",
            "Several fixtures are controls, not a source-disjoint style benchmark.",
            "This probe does not activate or modify the daily profile.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
