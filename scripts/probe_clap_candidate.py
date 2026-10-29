"""CPU-only CLAP text-audio retrieval preflight on labeled controls.

This is a bounded research probe, not a production music classifier. It ranks
fixed candidate descriptions and stores scalar cosine scores only; no PCM or
transcript is written to the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
import onnxruntime as ort
import psutil
from tokenizers import Tokenizer
from transformers import ClapFeatureExtractor

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "runtime/models/audio/clap-htsat-onnx-f249703"
DEFAULT_OUT = ROOT / "runtime/audio-path-replay/out/clap-candidate-probe-20261024.json"
FFMPEG = Path(
    r"C:\Users\ARTEM\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
)

# Existing clips are controls, not a broad source-disjoint validation set.
CASES = {
    "bach_toccata": (ROOT / "runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3", "classical_organ"),
    "saxophone_sample": (ROOT / "runtime/vision-venv/Lib/site-packages/gradio/media_assets/audio/sax.wav", "saxophone_timbre"),
    "music_fixture_unknown_style": (ROOT / "runtime/gemma4-e4b-cpu/cases/music.wav", None),
    "speech_plus_music": (ROOT / "runtime/gemma4-e4b-cpu/cases/speech_music.wav", "speech_music_overlap"),
    "russian_speech": (ROOT / "runtime/gemma4-e4b-cpu/cases/ru_speech.wav", "speech_only"),
    "noise": (ROOT / "runtime/gemma4-e4b-cpu/cases/noise.wav", "noise"),
    "silence": (ROOT / "runtime/gemma4-e4b-cpu/cases/silence.wav", "silence"),
}

PROMPTS = {
    "classical_organ": "Baroque classical instrumental music played on a pipe organ.",
    "saxophone_timbre": "A solo saxophone playing a melodic instrumental passage.",
    "jazz_saxophone": "Jazz music featuring a prominent saxophone solo.",
    "orchestral_cinematic": "A cinematic orchestral soundtrack with strings and brass.",
    "ambient_electronic": "Ambient electronic instrumental music with synthesizers.",
    "rock_guitar": "Rock music with electric guitar, bass, and drums.",
    "pop_vocals": "A pop song with a singer and rhythmic accompaniment.",
    "speech_only": "A person speaking in a conversational voice.",
    "speech_music_overlap": "A person speaking while background music continues.",
    "game_sound_effects": "Sound effects from a video game, without music.",
    "noise": "Broadband static noise, without speech or music.",
    "silence": "Digital silence with no audible sound.",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rss_bytes() -> int:
    return int(psutil.Process().memory_info().rss)


def decode(path: Path, seconds: float) -> np.ndarray:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-t", str(seconds), "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def make_text_inputs(tokenizer: Tokenizer, text: str, length: int = 77) -> dict[str, np.ndarray]:
    tokenizer.enable_truncation(max_length=length)
    encoded = tokenizer.encode(text)
    pad_id = tokenizer.token_to_id("<pad>")
    if pad_id is None:
        raise RuntimeError("CLAP tokenizer has no <pad> token")
    ids = encoded.ids[:length]
    mask = encoded.attention_mask[:length]
    pad = length - len(ids)
    ids += [pad_id] * pad
    mask += [0] * pad
    return {"input_ids": np.asarray([ids], dtype=np.int64), "attention_mask": np.asarray([mask], dtype=np.int64)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--clip-seconds", type=float, default=8.0)
    args = parser.parse_args()
    if not 1 <= args.clip_seconds <= 10:
        raise ValueError("clip-seconds must be between 1 and 10 to keep one deterministic CLAP crop")
    audio_path = MODEL_DIR / "clap_audio.onnx"
    text_path = MODEL_DIR / "clap_text.onnx"
    tokenizer_path = MODEL_DIR / "tokenizer.json"
    if not all(path.is_file() for path in (audio_path, text_path, tokenizer_path)):
        raise FileNotFoundError("Pinned CLAP audio/text ONNX and tokenizer files are required")
    expected_hashes = {
        "clap_audio.onnx": "3f42f71e555b62709910b6efa66fa5879f00d9571874b12b0fa674f82dbfe332",
        "clap_text.onnx": "c07b27204836877d5b615c103685b66ea8f21bc6b5b70a572be356125423a8bf",
        "tokenizer.json": "4fd1d86b4f5b53f40a609fcd11c1f34024b735f870a07439d70202b98493661a",
    }
    hashes = {path.name: sha256(path) for path in (audio_path, text_path, tokenizer_path)}
    if hashes != expected_hashes:
        raise RuntimeError(f"Pinned artifact SHA mismatch: {hashes}")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    process = psutil.Process()
    rss_before = rss_bytes()
    cpu_before = process.cpu_times()
    started = time.perf_counter()
    audio_session = ort.InferenceSession(str(audio_path), sess_options=options, providers=["CPUExecutionProvider"])
    text_session = ort.InferenceSession(str(text_path), sess_options=options, providers=["CPUExecutionProvider"])
    if audio_session.get_providers() != ["CPUExecutionProvider"] or text_session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("CLAP sessions must use CPUExecutionProvider only")
    loaded_seconds = time.perf_counter() - started
    rss_loaded = rss_bytes()

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    text_embeddings: dict[str, np.ndarray] = {}
    text_timings: dict[str, float] = {}
    text_input_names = {item.name for item in text_session.get_inputs()}
    for label, phrase in PROMPTS.items():
        inputs = make_text_inputs(tokenizer, phrase)
        feeds = {name: value for name, value in inputs.items() if name in text_input_names}
        if set(feeds) != text_input_names:
            raise RuntimeError(f"Unsupported text model inputs: {sorted(text_input_names)}")
        before = time.perf_counter()
        embedding = text_session.run(None, feeds)[0].astype(np.float32, copy=False).reshape(-1)
        text_timings[label] = time.perf_counter() - before
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(norm) or norm < 1e-8:
            raise RuntimeError(f"Invalid text embedding for {label}")
        text_embeddings[label] = embedding / norm
    rss_after_text = rss_bytes()

    feature_extractor = ClapFeatureExtractor()
    class_labels = list(PROMPTS)
    class_matrix = np.stack([text_embeddings[label] for label in class_labels])
    audio_input_name = audio_session.get_inputs()[0].name
    rows = []
    inference_times = []
    for case, (path, expected) in CASES.items():
        if not path.is_file():
            rows.append({"case": case, "expected_probe": expected, "available": False})
            continue
        waveform = decode(path, args.clip_seconds)
        if waveform.size < 48_000:
            rows.append({"case": case, "expected_probe": expected, "available": False, "reason": "clip shorter than one second"})
            continue
        features = feature_extractor(
            waveform,
            sampling_rate=48_000,
            truncation="rand_trunc",
            padding="pad",
            return_tensors="np",
        )["input_features"]
        if list(features.shape) != [1, 1, 1001, 64]:
            raise RuntimeError(f"Unexpected CLAP feature shape {features.shape}; expected one deterministic crop")
        before = time.perf_counter()
        audio_embedding = audio_session.run(None, {audio_input_name: features})[0].astype(np.float32, copy=False).reshape(-1)
        elapsed = time.perf_counter() - before
        inference_times.append(elapsed)
        norm = float(np.linalg.norm(audio_embedding))
        if not np.isfinite(norm) or norm < 1e-8:
            raise RuntimeError(f"Invalid audio embedding for {case}")
        scores = (class_matrix @ (audio_embedding / norm)).tolist()
        ranking = sorted(zip(class_labels, scores), key=lambda item: item[1], reverse=True)
        rows.append({
            "case": case,
            "expected_probe": expected,
            "available": True,
            "clip_seconds_requested": args.clip_seconds,
            "rms": float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64)))),
            "top_candidates": [{"label": label, "cosine_similarity": float(score), "phrase": PROMPTS[label]} for label, score in ranking[:5]],
            "all_cosine_similarities": {label: float(score) for label, score in zip(class_labels, scores)},
            "audio_encoder_seconds": elapsed,
        })

    finished = time.perf_counter()
    cpu_after = process.cpu_times()
    wall_elapsed = finished - started
    cpu_elapsed = (cpu_after.user + cpu_after.system) - (cpu_before.user + cpu_before.system)
    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "ConceptualMachines/magda-sample-tagger CLAP HTSAT ONNX",
        "revision": "f24970352f239768aaad48cc8734fb298441a763",
        "execution_provider": "CPUExecutionProvider",
        "threads": 1,
        "prompts": PROMPTS,
        "artifact_sha256": hashes,
        "load_seconds": loaded_seconds,
        "rss_bytes_before_load": rss_before,
        "rss_bytes_after_load": rss_loaded,
        "rss_bytes_after_text_embeddings": rss_after_text,
        "text_encoder_seconds_by_prompt": text_timings,
        "audio_encoder_seconds_p50": float(np.median(inference_times)) if inference_times else None,
        "audio_encoder_seconds_p95": float(np.percentile(inference_times, 95)) if inference_times else None,
        "probe_wall_seconds": wall_elapsed,
        "probe_process_cpu_percent": round(100.0 * cpu_elapsed / wall_elapsed, 2) if wall_elapsed > 0 else None,
        "limitations": [
            "small exploratory fixtures; not parent-recording-disjoint or style-balanced",
            "cosine similarity is not calibrated probability or confidence",
            "candidate phrases can bias retrieval; no genre label should be published from this probe alone",
            "CLAP retrieves similarities and does not generate a grounded natural-language caption",
            "isolated process RSS includes Python, ONNX Runtime, tokenizer and feature extractor",
        ],
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "load_seconds": loaded_seconds,
        "rss_mib_after_text": round(rss_after_text / 1024**2, 1),
        "audio_encoder_seconds_p50": result["audio_encoder_seconds_p50"],
        "audio_encoder_seconds_p95": result["audio_encoder_seconds_p95"],
        "probe_process_cpu_percent": result["probe_process_cpu_percent"],
        "cases": [{"case": row["case"], "top": row.get("top_candidates", [])[:2]} for row in rows if row.get("available")],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
