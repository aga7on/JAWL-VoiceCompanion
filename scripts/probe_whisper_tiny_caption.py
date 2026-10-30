"""CPU-only preflight for an experimental Whisper audio-caption model."""
from __future__ import annotations

import hashlib
import copy
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import psutil
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "runtime/models/audio/whisper-tiny-audio-captioning-v2.0"
WEIGHTS = MODEL / "model.safetensors"
OUT = ROOT / "runtime/audio-path-replay/out/whisper-tiny-caption-probe-20261024.json"
CASES = {
    "bach_toccata_music": ROOT / "runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3",
    "sax_instrument_music": ROOT / "runtime/vision-venv/Lib/site-packages/gradio/media_assets/audio/sax.wav",
    "synthetic_music": ROOT / "runtime/gemma4-e4b-cpu/cases/music.wav",
    "speech_over_music": ROOT / "runtime/gemma4-e4b-cpu/cases/speech_music.wav",
    "russian_speech": ROOT / "runtime/synthetic-questions/question-01.wav",
    "noise": ROOT / "runtime/gemma4-e4b-cpu/cases/noise.wav",
    "silence": ROOT / "runtime/gemma4-e4b-cpu/cases/silence.wav",
}


def decode(path: Path, seconds: int = 12) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-t", str(seconds),
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(proc.stdout, dtype="<f4").copy()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    process = psutil.Process()
    started = time.perf_counter()
    result: dict = {
        "model": "cahya/whisper-tiny-audio-captioning-v2.0",
        "revision": "a8219d270ff91d8a671c7ff1e760ca6175ffd311",
        "provider": "PyTorch CPU",
        "threads": 1,
        "weight_bytes": WEIGHTS.stat().st_size,
        "weight_sha256": sha256(WEIGHTS),
        "rss_mib_before_load": round(process.memory_info().rss / 1048576, 1),
        "cases": {},
    }
    processor = WhisperProcessor.from_pretrained(MODEL, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(
        MODEL, local_files_only=True, use_safetensors=True
    ).to("cpu").eval()
    prefix = processor.tokenizer(
        "", text_target="clotho > caption: ", return_tensors="pt", add_special_tokens=False
    ).labels
    tokenizer = processor.tokenizer
    decoder_prefix = torch.tensor([[
        model.config.decoder_start_token_id,
        tokenizer.convert_tokens_to_ids("<|en|>"),
        tokenizer.convert_tokens_to_ids("<|transcribe|>"),
        tokenizer.convert_tokens_to_ids("<|notimestamps|>"),
        *prefix[0].tolist(),
    ]], dtype=torch.long)
    result["caption_prefix"] = "clotho > caption: "
    result["load_seconds"] = round(time.perf_counter() - started, 3)
    result["rss_mib_after_load"] = round(process.memory_info().rss / 1048576, 1)

    for name, path in CASES.items():
        if not path.is_file():
            result["cases"][name] = {"available": False, "path": str(path)}
            continue
        audio = decode(path)
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt")
        t0 = time.perf_counter()
        cpu0 = process.cpu_times()
        with torch.inference_mode():
            generation_config = copy.deepcopy(model.generation_config)
            generation_config.forced_decoder_ids = None
            generation_config.language = None
            generation_config.task = None
            generation_config.return_timestamps = False
            ids = model.generate(
                inputs.input_features,
                decoder_input_ids=decoder_prefix,
                generation_config=generation_config,
                max_new_tokens=40,
                num_beams=1,
                do_sample=False,
            )
        cpu1 = process.cpu_times()
        text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        text = text.removeprefix("clotho > caption:").strip()
        result["cases"][name] = {
            "available": True,
            "duration_s": round(len(audio) / 16000, 3),
            "rms": round(float(np.sqrt(np.mean(audio * audio))), 6),
            "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
            "cpu_ms": round((cpu1.user + cpu1.system - cpu0.user - cpu0.system) * 1000, 1),
            "caption": text,
        }
    result["rss_mib_after_inference"] = round(process.memory_info().rss / 1048576, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "model": result["model"],
        "revision": result["revision"],
        "load_seconds": result["load_seconds"],
        "rss_mib": result["rss_mib_after_inference"],
        "cases": {key: {"wall_ms": value.get("wall_ms"), "caption": value.get("caption")}
                  for key, value in result["cases"].items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
