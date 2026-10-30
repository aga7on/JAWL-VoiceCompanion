"""Evaluate YAMNet event and broad-style tags on the licensed FMA probe set.

CPU-only, one-thread, bounded crop. The output contains track metadata and
scalar model scores only; decoded PCM and transcripts are never persisted.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "runtime/audio-path-replay/data/fma-medium-selected/manifest.json"
MODEL_DIR = ROOT / "runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
OUTPUT = ROOT / "runtime/audio-path-replay/out/yamnet-fma-style-probe-20261024.json"
FFMPEG = Path(r"C:\Users\ARTEM\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe")
STYLE_MAP = {
    "Classical": "Classical music", "Electronic": "Electronic music",
    "Folk": "Folk music", "Hip-Hop": "Hip hop music",
    "Jazz": "Jazz", "Rock": "Rock music",
}


def decode(path: Path, seconds: float, start: float) -> np.ndarray:
    proc = subprocess.run(
        [str(FFMPEG), "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(seconds),
         "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
        capture_output=True, timeout=60, check=False,
    )
    if proc.returncode or not proc.stdout:
        raise RuntimeError("audio decode failed")
    return np.frombuffer(proc.stdout, dtype="<f4").copy()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--clip-seconds", type=float, default=8.0)
    parser.add_argument("--start-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if not 2.0 <= args.clip_seconds <= 20.0 or args.start_seconds < 0:
        parser.error("clip must be 2..20s and start must be non-negative")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tracks = manifest["tracks"]
    artists = [str(track["artist_id"]) for track in tracks]
    if len(tracks) != 18 or len(set(artists)) != len(artists):
        raise RuntimeError("expected the 18-track artist-disjoint FMA probe manifest")

    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(MODEL_DIR / "yamnet.onnx"), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("YAMNet did not load CPUExecutionProvider only")
    with (MODEL_DIR / "yamnet_class_map.csv").open(encoding="utf-8-sig", newline="") as handle:
        labels = [row["display_name"] for row in csv.DictReader(handle)]
    if any(label not in labels for label in STYLE_MAP.values()):
        raise RuntimeError("YAMNet class map lacks a target genre class")
    genre_ids = {genre: labels.index(label) for genre, label in STYLE_MAP.items()}
    rows: list[dict[str, Any]] = []
    times: list[float] = []
    rss = None
    try:
        import psutil
        rss = int(psutil.Process().memory_info().rss)
    except Exception:
        pass

    for track in tracks:
        path = ROOT / track["local_file"]
        audio = decode(path, args.clip_seconds, args.start_seconds)
        if len(audio) < 32_000:
            raise RuntimeError(f"decoded crop too short for track {track['track_id']}")
        windows: list[np.ndarray] = []
        started = time.perf_counter()
        for offset in range(0, max(1, len(audio) - 32_000 + 16_000), 16_000):
            frame = audio[offset:offset + 32_000]
            if len(frame) < 32_000:
                frame = np.pad(frame, (0, 32_000 - len(frame)))
            windows.append(np.asarray(session.run(None, {"waveform": frame.astype(np.float32)})[0], dtype=np.float32).mean(axis=0).reshape(-1))
        elapsed_ms = (time.perf_counter() - started) * 1000
        times.append(elapsed_ms)
        scores = np.stack(windows).mean(axis=0)
        expected_id = genre_ids[track["genre"]]
        genre_scores = sorted(((genre, float(scores[index])) for genre, index in genre_ids.items()), key=lambda pair: pair[1], reverse=True)
        event_order = np.argsort(scores)[::-1]
        rows.append({
            **{key: track[key] for key in ("track_id", "artist_id", "artist", "title", "genre", "license")},
            "top_style": genre_scores[0][0],
            "expected_style": track["genre"],
            "top1_matches_catalog": genre_scores[0][0] == track["genre"],
            "expected_style_score": round(float(scores[expected_id]), 6),
            "top_style_margin": round(genre_scores[0][1] - genre_scores[1][1], 6),
            "style_scores": [{"label": genre, "score": round(score, 6)} for genre, score in genre_scores],
            "top_event_tags": [{"label": labels[int(i)], "score": round(float(scores[int(i)]), 6)} for i in event_order[:8]],
            "inference_ms": round(elapsed_ms, 2),
        })

    per_genre = {}
    for genre in STYLE_MAP:
        group = [row for row in rows if row["genre"] == genre]
        per_genre[genre] = {"count": len(group), "top1_matches": sum(row["top1_matches_catalog"] for row in group)}
    report = {
        "schema_version": 1, "model": "YAMNet ONNX", "providers": session.get_providers(),
        "threads": {"intra_op": options.intra_op_num_threads, "inter_op": options.inter_op_num_threads},
        "dataset": "FMA Medium selected individually licensed artist-disjoint probe",
        "tracks": len(rows), "unique_artists": len(set(artists)), "per_genre": per_genre,
        "top1_matches": sum(row["top1_matches_catalog"] for row in rows),
        "top1_accuracy": round(sum(row["top1_matches_catalog"] for row in rows) / len(rows), 4),
        "inference_ms_p50": round(float(np.median(times)), 2),
        "inference_ms_p95": round(float(np.percentile(times, 95)), 2),
        "rss_after_load_bytes": rss, "rows": rows,
        "raw_audio_persisted": False, "transcript_persisted": False,
        "notes": ["YAMNet AudioSet scores are not calibrated genre probabilities.",
                  "FMA catalog labels are weak proxy labels and were not independently confirmed by listening.",
                  "Small exploratory set; no production thresholds or profile changes are implied."],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("providers", "threads", "tracks", "unique_artists", "per_genre", "top1_matches", "top1_accuracy", "inference_ms_p50", "inference_ms_p95", "rss_after_load_bytes", "raw_audio_persisted", "transcript_persisted")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
