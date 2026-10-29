"""Source-disjoint exploratory CLAP style probe on individually licensed FMA clips.

The report stores metadata, scalar similarities and resource measurements only.
It does not write decoded PCM or ASR transcripts and does not alter the daily
profile. FMA genre_top is treated as a weak catalog label, not human ground truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import onnxruntime as ort
import psutil
from tokenizers import Tokenizer
from transformers import ClapFeatureExtractor


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "runtime/models/audio/clap-htsat-onnx-f249703"
DEFAULT_MANIFEST = ROOT / "runtime/audio-path-replay/data/fma-medium-selected/manifest.json"
DEFAULT_OUT = ROOT / "runtime/audio-path-replay/out/fma-medium-clap-style-probe-20261024.json"
FFMPEG = Path(
    r"C:\Users\ARTEM\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
)

# Frozen once for this exploratory split. These are candidate descriptions,
# not calibrated probabilities or a claim that each FMA catalog label is right.
PROMPTS = {
    "Classical": "Classical music performed with acoustic instruments such as piano, strings, or orchestra.",
    "Electronic": "Electronic music made with synthesizers, electronic textures, and programmed beats.",
    "Folk": "Folk music with acoustic instruments and a traditional melodic style.",
    "Hip-Hop": "Hip-hop music with a rhythmic beat, bass, and rap vocals.",
    "Jazz": "Jazz music with improvisation, swing, and acoustic instruments.",
    "Rock": "Rock music with electric guitar, bass, and drum kit.",
    "other_music": "Music in a style other than classical, electronic, folk, hip-hop, jazz, or rock.",
    "speech_only": "A person speaking with no music in the background.",
    "speech_over_music": "A person speaking while background music continues.",
    "game_effects_no_music": "Video game sound effects without music or speech.",
    "noise_no_music": "Broadband noise without music or speech.",
    "digital_silence": "Digital silence with no audible sound.",
}
STYLE_LABELS = {"Classical", "Electronic", "Folk", "Hip-Hop", "Jazz", "Rock", "other_music"}
CONTROL_CASES = {
    "speech_only": ROOT / "runtime/gemma4-e4b-cpu/cases/ru_speech.wav",
    "speech_over_music": ROOT / "runtime/gemma4-e4b-cpu/cases/speech_music.wav",
    "noise_no_music": ROOT / "runtime/gemma4-e4b-cpu/cases/noise.wav",
    "digital_silence": ROOT / "runtime/gemma4-e4b-cpu/cases/silence.wav",
}
EXPECTED_HASHES = {
    "clap_audio.onnx": "3f42f71e555b62709910b6efa66fa5879f00d9571874b12b0fa674f82dbfe332",
    "clap_text.onnx": "c07b27204836877d5b615c103685b66ea8f21bc6b5b70a572be356125423a8bf",
    "tokenizer.json": "4fd1d86b4f5b53f40a609fcd11c1f34024b735f870a07439d70202b98493661a",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode(path: Path, seconds: float, start_seconds: float) -> np.ndarray:
    result = subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-ss", str(start_seconds), "-i", str(path),
            "-t", str(seconds), "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def text_inputs(tokenizer: Tokenizer, phrase: str, length: int = 77) -> dict[str, np.ndarray]:
    tokenizer.enable_truncation(max_length=length)
    encoded = tokenizer.encode(phrase)
    pad_id = tokenizer.token_to_id("<pad>")
    if pad_id is None:
        raise RuntimeError("CLAP tokenizer is missing <pad>")
    ids, mask = encoded.ids[:length], encoded.attention_mask[:length]
    pad = length - len(ids)
    return {
        "input_ids": np.asarray([ids + [pad_id] * pad], dtype=np.int64),
        "attention_mask": np.asarray([mask + [0] * pad], dtype=np.int64),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--clip-seconds", type=float, default=8.0)
    parser.add_argument("--start-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if not 1 <= args.clip_seconds <= 10 or args.start_seconds < 0:
        parser.error("clip duration must be 1..10s and start must be nonnegative")
    if not FFMPEG.is_file():
        raise FileNotFoundError("Pinned local FFmpeg executable was not found")
    audio_path, text_path, tokenizer_path = (
        MODEL_DIR / "clap_audio.onnx", MODEL_DIR / "clap_text.onnx", MODEL_DIR / "tokenizer.json"
    )
    actual_hashes = {p.name: sha256(p) for p in (audio_path, text_path, tokenizer_path)}
    if actual_hashes != EXPECTED_HASHES:
        raise RuntimeError(f"Pinned CLAP artifact SHA mismatch: {actual_hashes}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tracks = manifest.get("tracks") or []
    if not tracks:
        raise RuntimeError("No licensed tracks in manifest")
    for track in tracks:
        audio_file = (ROOT / track["local_file"]).resolve()
        if not audio_file.is_relative_to(ROOT.resolve()) or not audio_file.is_file():
            raise RuntimeError("Manifest audio path is missing or escapes repository runtime")
        track["_audio_path"] = audio_file

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    process = psutil.Process()
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    audio_session = ort.InferenceSession(str(audio_path), sess_options=options, providers=["CPUExecutionProvider"])
    text_session = ort.InferenceSession(str(text_path), sess_options=options, providers=["CPUExecutionProvider"])
    if audio_session.get_providers() != ["CPUExecutionProvider"] or text_session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("CLAP must remain CPUExecutionProvider-only")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    text_names = {item.name for item in text_session.get_inputs()}
    prototypes = {}
    for label, phrase in PROMPTS.items():
        prepared = text_inputs(tokenizer, phrase)
        feeds = {name: value for name, value in prepared.items() if name in text_names}
        vector = text_session.run(None, feeds)[0].astype(np.float32, copy=False).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm < 1e-8:
            raise RuntimeError(f"Invalid CLAP text vector for {label}")
        prototypes[label] = vector / norm
    matrix = np.stack(list(prototypes.values()))
    labels = list(prototypes)
    feature_extractor = ClapFeatureExtractor()
    input_name = audio_session.get_inputs()[0].name
    rows = []
    timings = []

    def infer(case_name: str, waveform: np.ndarray, metadata: dict, expected: str | None, case_type: str) -> None:
        minimum_samples = 48_000 if case_type == "control" else int(args.clip_seconds * 48_000 * 0.75)
        if waveform.size < minimum_samples:
            rows.append({"case": case_name, "case_type": case_type, "expected": expected, "status": "short_decode"})
            return
        features = feature_extractor(
            waveform, sampling_rate=48_000, truncation="rand_trunc", padding="pad", return_tensors="np"
        )["input_features"]
        if list(features.shape) != [1, 1, 1001, 64]:
            raise RuntimeError(f"Unexpected CLAP input shape {features.shape}")
        before = time.perf_counter()
        vector = audio_session.run(None, {input_name: features})[0].astype(np.float32, copy=False).reshape(-1)
        elapsed = time.perf_counter() - before
        timings.append(elapsed)
        norm = float(np.linalg.norm(vector))
        scores = matrix @ (vector / max(norm, 1e-8))
        order = np.argsort(scores)[::-1]
        ranked = [{"label": labels[i], "score": round(float(scores[i]), 6)} for i in order[:5]]
        row = {
            "case": case_name,
            "case_type": case_type,
            "expected_catalog_genre": expected,
            "top1": labels[int(order[0])],
            "top1_is_expected": bool(expected and labels[int(order[0])] == expected),
            "top1_top2_margin": round(float(scores[order[0]] - scores[order[1]]), 6),
            "top_candidates": ranked,
            "audio_rms": round(float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64)))), 6),
            "audio_encoder_ms": round(elapsed * 1000, 2),
        }
        if case_type == "fma_music":
            row.update({k: metadata[k] for k in ("track_id", "artist_id", "artist", "title", "genre", "license")})
        rows.append(row)

    for track in tracks:
        waveform = decode(track["_audio_path"], args.clip_seconds, args.start_seconds)
        infer(f"fma_{track['track_id']}", waveform, track, track["genre"], "fma_music")
    for name, path in CONTROL_CASES.items():
        if path.is_file():
            waveform = decode(path, args.clip_seconds, 0)
            expected = name if name in PROMPTS else None
            infer(name, waveform, {}, expected, "control")

    music_rows = [row for row in rows if row["case_type"] == "fma_music" and "top1" in row]
    per_genre = {}
    for genre in sorted({row["expected_catalog_genre"] for row in music_rows}):
        group = [row for row in music_rows if row["expected_catalog_genre"] == genre]
        per_genre[genre] = {
            "count": len(group),
            "top1_correct_vs_catalog_proxy": sum(row["top1_is_expected"] for row in group),
            "top1_accuracy_vs_catalog_proxy": round(sum(row["top1_is_expected"] for row in group) / max(1, len(group)), 4),
        }
    control_rows = [row for row in rows if row["case_type"] == "control" and "top1" in row]
    metrics = {
        "music_tracks": len(music_rows),
        "top1_correct_vs_catalog_proxy": sum(row["top1_is_expected"] for row in music_rows),
        "top1_accuracy_vs_catalog_proxy": round(sum(row["top1_is_expected"] for row in music_rows) / max(1, len(music_rows)), 4),
        "per_genre": per_genre,
        "control_count": len(control_rows),
        "style_false_positive_on_speech_noise_silence": sum(
            row["top1"] in STYLE_LABELS for row in control_rows if row["case"] in {"speech_only", "noise_no_music", "digital_silence"}
        ),
        "speech_music_control_top1": next((r["top1"] for r in control_rows if r["case"] == "speech_over_music"), None),
    }
    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "ConceptualMachines MAGDA CLAP HTSAT ONNX",
        "revision": "f24970352f239768aaad48cc8734fb298441a763",
        "execution_provider": audio_session.get_providers(),
        "threads": {"intra_op": options.intra_op_num_threads, "inter_op": options.inter_op_num_threads},
        "artifact_sha256": actual_hashes,
        "fma_manifest": str(args.manifest.relative_to(ROOT)) if args.manifest.is_relative_to(ROOT) else args.manifest.name,
        "split_unit": "18 distinct artist_id values across six catalog genres; artist-disjoint exploratory set",
        "prompt_bank": PROMPTS,
        "clip_seconds": args.clip_seconds,
        "clip_start_seconds": args.start_seconds,
        "metrics": metrics,
        "audio_encoder_ms_p50": round(float(np.percentile(timings, 50)) * 1000, 2) if timings else None,
        "audio_encoder_ms_p95": round(float(np.percentile(timings, 95)) * 1000, 2) if timings else None,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": process.memory_info().rss,
        "raw_pcm_written": False,
        "transcript_written": False,
        "limitations": [
            "FMA genre_top is a weak uploader/catalog proxy and was not independently human-labeled by listening.",
            "Three artists per style is exploratory, not a statistical acceptance set.",
            "Cosine similarity is not calibrated confidence; style outputs must remain research-only.",
            "The fixed crop and prompt bank were frozen before scoring this held-out artist subset.",
        ],
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": metrics, "audio_encoder_ms_p50": result["audio_encoder_ms_p50"], "audio_encoder_ms_p95": result["audio_encoder_ms_p95"], "rss_after_bytes": result["rss_after_bytes"], "output": str(args.output)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
