"""Probe latency and output presence for short ASR windows on the five local QA clips.

This is an offline model-level experiment, not a live capture or end-to-end
freshness acceptance. It stores only timing and transcript-length metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CLIP_DIR = ROOT / "runtime/multimodal-realclips-20261024/probes/lowrate"
ASR_EXE = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
ASR_MODEL = ROOT / "runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf"
RATE = 16_000
CLIPS = ("01_ru_trailer", "02_anime", "03_gameplay", "04_coding_ui", "05_aqua_song")


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, RATE, 2):
            raise ValueError(f"expected mono 16kHz PCM16 WAV: {path}")
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").copy()


def transcribe(pcm: np.ndarray) -> dict:
    pcm = np.asarray(pcm, dtype="<i2")
    with tempfile.TemporaryDirectory(prefix="jawl-freshness-") as temp:
        base = Path(temp)
        audio_path = base / "window.wav"
        output_prefix = base / "asr"
        with wave.open(str(audio_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(RATE)
            output.writeframes(pcm.tobytes())
        started = time.perf_counter()
        proc = subprocess.run(
            [str(ASR_EXE), "-m", str(ASR_MODEL), "-oj", "-of", str(output_prefix), str(audio_path)],
            cwd=base, capture_output=True, timeout=90, check=False,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if proc.returncode:
            raise RuntimeError(f"GigaAM exited {proc.returncode}: {proc.stderr[-300:].decode(errors='replace')}")
        result_path = next((p for p in (base / "asr.json", base / "asr.wav.json") if p.is_file()), None)
        if result_path is None:
            raise RuntimeError("GigaAM produced no JSON")
        data = json.loads(result_path.read_text(encoding="utf-8"))
        result = data.get("transcription") or data.get("result") or data
        if isinstance(result, list):
            text = " ".join(str(item.get("text", "") if isinstance(item, dict) else item) for item in result)
        elif isinstance(result, dict):
            text = str(result.get("text") or result.get("transcription") or "")
        else:
            text = str(result)
        normalized = "".join(c.casefold() for c in text if c.isalnum())
        return {
            "nonempty": bool(normalized),
            "normalized_char_count": len(normalized),
            "normalized_text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "inference_latency_ms": round(latency_ms, 1),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=float, default=5.0)
    parser.add_argument("--hop", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/audio-path-replay/out/short-window-gigaam-20261024.json")
    args = parser.parse_args()
    if not (1.0 <= args.window <= 15.0 and 0.25 <= args.hop <= args.window):
        parser.error("require 1 <= window <= 15 seconds and 0.25 <= hop <= window")
    for path in (ASR_EXE, ASR_MODEL, *(CLIP_DIR / f"{name}.wav" for name in CLIPS)):
        if not path.is_file():
            raise FileNotFoundError(path)

    rows = []
    for clip_id in CLIPS:
        pcm = load_wav(CLIP_DIR / f"{clip_id}.wav")
        duration = len(pcm) / RATE
        windows = []
        start = 0.0
        while start < duration:
            start_sample = round(start * RATE)
            end_sample = min(len(pcm), start_sample + round(args.window * RATE))
            window_pcm = pcm[start_sample:end_sample]
            if len(window_pcm) < RATE:
                break
            result = transcribe(window_pcm)
            window_end = end_sample / RATE
            windows.append({
                "start_s": round(start, 3),
                "end_s": round(window_end, 3),
                "input_seconds": round(len(window_pcm) / RATE, 3),
                **result,
                # Under continuous playback, result becomes available this long
                # after its window's first sample (capture cadence excluded).
                "window_age_at_result_ms": round((window_end - start) * 1000 + result["inference_latency_ms"], 1),
            })
            if end_sample == len(pcm):
                break
            start += args.hop
        rows.append({
            "clip_id": clip_id,
            "duration_seconds": round(duration, 3),
            "wav_sha256": hashlib.sha256((CLIP_DIR / f"{clip_id}.wav").read_bytes()).hexdigest(),
            "windows": windows,
        })
        print(f"{clip_id}: {sum(w['nonempty'] for w in windows)}/{len(windows)} nonempty; max age={max(w['window_age_at_result_ms'] for w in windows):.0f}ms")

    latencies = [w["inference_latency_ms"] for row in rows for w in row["windows"]]
    ages = [w["window_age_at_result_ms"] for row in rows for w in row["windows"]]
    summary = {
        "schema_version": 1,
        "status": "completed",
        "model": "GigaAM v3 e2e RNNT q8_0 via CrispASR CPU CLI",
        "cpu_only": True,
        "scope": "offline ASR windows over five existing 10-second real QA audio lanes; not live capture or transcript accuracy acceptance",
        "window_seconds": args.window,
        "hop_seconds": args.hop,
        "raw_audio_persisted": False,
        "transcript_text_persisted": False,
        "window_count": len(latencies),
        "nonempty_windows": sum(w["nonempty"] for row in rows for w in row["windows"]),
        "latency_ms": {
            "p50": round(float(np.quantile(latencies, .5)), 1),
            "p95": round(float(np.quantile(latencies, .95)), 1),
            "max": round(max(latencies), 1),
        },
        "window_age_ms": {
            "p50": round(float(np.quantile(ages, .5)), 1),
            "p95": round(float(np.quantile(ages, .95)), 1),
            "max": round(max(ages), 1),
        },
        "clips": rows,
        "limitations": [
            "Hashes and character counts do not measure word error rate or semantic correctness.",
            "Window outputs overlap and may repeat or truncate words; no deduplication is applied.",
            "This measures model window latency only; queueing, capture cadence, fusion, and user-turn delivery are excluded.",
            "Five clips are a small fixed QA set and are not independent source-disjoint accuracy evidence.",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "windows": len(latencies), "latency_ms": summary["latency_ms"], "window_age_ms": summary["window_age_ms"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
