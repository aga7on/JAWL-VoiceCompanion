"""Inspect YAMNet's existing AudioSet genre classes on local audio controls.

This is a CPU-only, in-memory research probe. It stores class scores and
timings, never PCM or transcript text, and does not alter the daily profile.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
DEFAULT_OUTPUT = ROOT / "runtime/audio-path-replay/out/yamnet-music-style-probe-20261024.json"
FFMPEG = Path(r"C:\Users\ARTEM\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe")
CASES = {
    "bach_toccata": ROOT / "runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3",
    "saxophone_sample": ROOT / "runtime/vision-venv/Lib/site-packages/gradio/media_assets/audio/sax.wav",
    "music_fixture_unverified_style": ROOT / "runtime/gemma4-e4b-cpu/cases/music.wav",
    "russian_speech": ROOT / "runtime/gemma4-e4b-cpu/cases/ru_speech.wav",
    "speech_plus_music_fixture": ROOT / "runtime/gemma4-e4b-cpu/cases/speech_music.wav",
    "noise_control": ROOT / "runtime/gemma4-e4b-cpu/cases/noise.wav",
    "silence_control": ROOT / "runtime/gemma4-e4b-cpu/cases/silence.wav",
}
WINDOW_SAMPLES = 32_000
HOP_SAMPLES = 16_000
GENRE_LABELS = {
    "Pop music", "Hip hop music", "Rock music", "Rhythm and blues", "Jazz",
    "Classical music", "Electronic music", "Funk", "Soul music", "Reggae",
    "Country", "Blues", "Folk music", "Middle Eastern music", "Music of Africa",
    "Music of Asia", "Music of Latin America", "Ska", "New-age music", "Ambient music",
    "Disco", "Opera", "Heavy metal", "Punk rock", "Swing music", "Salsa music",
}


def _read_pcm(path: Path) -> np.ndarray:
    proc = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode or not proc.stdout:
        raise RuntimeError(f"audio decode failed ({proc.returncode})")
    return np.frombuffer(proc.stdout, dtype="<f4").copy()


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-seconds", type=float, default=30.0)
    args = parser.parse_args()

    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(MODEL_DIR / "yamnet.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("YAMNet did not load CPUExecutionProvider only")
    with (MODEL_DIR / "yamnet_class_map.csv").open(encoding="utf-8-sig", newline="") as handle:
        labels = [row["display_name"] for row in csv.DictReader(handle)]
    genre_indices = [index for index, label in enumerate(labels) if label in GENRE_LABELS]
    cases: dict[str, Any] = {}
    rss_after_load = _rss_bytes()

    for name, path in CASES.items():
        if not path.is_file():
            cases[name] = {"available": False}
            continue
        started = time.perf_counter()
        try:
            audio = _read_pcm(path)
            audio = audio[: int(args.max_seconds * 16_000)]
            starts = range(0, max(1, len(audio) - WINDOW_SAMPLES + HOP_SAMPLES), HOP_SAMPLES)
            rows: list[np.ndarray] = []
            for offset in starts:
                window = audio[offset : offset + WINDOW_SAMPLES]
                if len(window) < WINDOW_SAMPLES:
                    window = np.pad(window, (0, WINDOW_SAMPLES - len(window)))
                scores = np.asarray(session.run(None, {"waveform": window.astype(np.float32)})[0], dtype=np.float32).mean(axis=0).reshape(-1)
                rows.append(scores)
            matrix = np.stack(rows)
            mean_scores = matrix.mean(axis=0)
            music_index = labels.index("Music")
            music_scores = matrix[:, music_index]
            genre_order = sorted(genre_indices, key=lambda i: float(mean_scores[i]), reverse=True)[:6]
            event_order = np.argsort(mean_scores)[::-1][:8]
            cases[name] = {
                "available": True,
                "path": str(path.relative_to(ROOT)),
                "duration_seconds": round(len(audio) / 16_000, 2),
                "windows": len(rows),
                "music_score_median": round(float(np.median(music_scores)), 4),
                "music_windows_ge_0_30": int(np.count_nonzero(music_scores >= 0.30)),
                "genre_scores_mean": [{"label": labels[i], "score": round(float(mean_scores[i]), 4)} for i in genre_order],
                "top_event_scores_mean": [{"label": labels[int(i)], "score": round(float(mean_scores[i]), 4)} for i in event_order],
                "inference_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        except Exception as exc:
            cases[name] = {"available": True, "path": str(path.relative_to(ROOT)), "error": f"{type(exc).__name__}: {exc}"}

    result = {
        "schema_version": 1,
        "model": "YAMNet ONNX",
        "revision": MODEL_DIR.name,
        "providers": session.get_providers(),
        "threads": {"intra_op": options.intra_op_num_threads, "inter_op": options.inter_op_num_threads},
        "rss_after_load_bytes": rss_after_load,
        "cases": cases,
        "raw_audio_persisted": False,
        "transcript_persisted": False,
        "notes": [
            "Scores are raw AudioSet model scores, not calibrated genre probabilities.",
            "Genre rankings are exploratory; local controls are not source-disjoint validation.",
            "No production thresholds or profile changes are implied by this probe.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
