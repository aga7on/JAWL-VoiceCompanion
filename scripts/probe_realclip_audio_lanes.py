"""Run local GigaAM ASR and CPU YAMNet over the five real QA clip audio lanes.

Only scalar class scores, timing, and transcript-presence metadata are written.
Decoded PCM and transcript text remain in memory or short-lived temporary files;
no capture devices or daily-profile services are started.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort


ROOT = Path(__file__).resolve().parents[1]
CLIP_DIR = ROOT / "runtime/multimodal-realclips-20261024/probes/lowrate"
MODEL_DIR = ROOT / "runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
ASR_EXE = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
ASR_MODEL = ROOT / "runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf"
CASES = {
    "01_ru_trailer": "Russian live-action trailer",
    "02_anime": "Russian anime trailer",
    "03_gameplay": "RTS gameplay",
    "04_coding_ui": "coding UI video",
    "05_aqua_song": "Aqua music video",
}
RATE = 16_000
WINDOW = 2 * RATE
HOP = RATE


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getframerate() != RATE or source.getsampwidth() != 2:
            raise ValueError(f"expected mono 16 kHz PCM16 WAV: {path.name}")
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def asr_metadata(audio: np.ndarray) -> dict:
    pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype("<i2")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="jawl-realclip-asr-") as tmp:
        tmp_path = Path(tmp)
        wav_path = tmp_path / "audio.wav"
        output_prefix = tmp_path / "asr"
        with wave.open(str(wav_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(RATE)
            output.writeframes(pcm16.tobytes())
        proc = subprocess.run(
            [str(ASR_EXE), "-m", str(ASR_MODEL), "-oj", "-of", str(output_prefix), str(wav_path)],
            cwd=tmp_path,
            capture_output=True,
            timeout=90,
            check=False,
        )
        if proc.returncode:
            raise RuntimeError(f"GigaAM exited {proc.returncode}")
        result_path = next((p for p in (tmp_path / "asr.json", tmp_path / "asr.wav.json") if p.is_file()), None)
        if result_path is None:
            raise RuntimeError("GigaAM produced no JSON")
        data = json.loads(result_path.read_text(encoding="utf-8"))
        result = data.get("transcription") or data.get("result") or data
        if isinstance(result, list):
            transcript = " ".join(str(item.get("text", "") if isinstance(item, dict) else item) for item in result)
        elif isinstance(result, dict):
            transcript = str(result.get("text") or result.get("transcription") or "")
        else:
            transcript = str(result)
        normalized = "".join(char.casefold() for char in transcript if char.isalnum())
        return {
            "nonempty": bool(normalized),
            "normalized_char_count": len(normalized),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/audio-path-replay/out/realclip-audio-lanes-20261024.json")
    args = parser.parse_args()
    missing = [str(path) for path in (ASR_EXE, ASR_MODEL, MODEL_DIR / "yamnet.onnx", MODEL_DIR / "yamnet_class_map.csv") if not path.is_file()]
    missing.extend(str(CLIP_DIR / f"{name}.wav") for name in CASES if not (CLIP_DIR / f"{name}.wav").is_file())
    if missing:
        raise FileNotFoundError("missing local probe dependencies: " + ", ".join(missing))

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    model = ort.InferenceSession(str(MODEL_DIR / "yamnet.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    if model.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("YAMNet did not load CPUExecutionProvider only")
    with (MODEL_DIR / "yamnet_class_map.csv").open(encoding="utf-8-sig", newline="") as source:
        labels = [row["display_name"] for row in csv.DictReader(source)]
    music_index = labels.index("Music")
    speech_index = labels.index("Speech")
    output = {
        "schema_version": 1,
        "model": "YAMNet ONNX + GigaAM v3 e2e RNNT q8_0",
        "cpu_only": True,
        "onnx_providers": model.get_providers(),
        "yamnet_threads": {"intra": options.intra_op_num_threads, "inter": options.inter_op_num_threads},
        "clip_set": str(CLIP_DIR.relative_to(ROOT)),
        "raw_audio_persisted": False,
        "transcript_text_persisted": False,
        "cases": [],
    }
    for case_id, description in CASES.items():
        audio = read_wav(CLIP_DIR / f"{case_id}.wav")
        windows = []
        started = time.perf_counter()
        for offset in range(0, max(1, len(audio) - WINDOW + 1), HOP):
            window = audio[offset : offset + WINDOW]
            if len(window) < WINDOW:
                window = np.pad(window, (0, WINDOW - len(window)))
            scores = model.run(None, {"waveform": window.astype(np.float32)})[0].mean(axis=0)
            top = np.argsort(scores)[::-1][:5]
            windows.append({
                "start_s": round(offset / RATE, 1),
                "music_score": round(float(scores[music_index]), 4),
                "speech_score": round(float(scores[speech_index]), 4),
                "top_tags": [{"label": labels[int(i)], "score": round(float(scores[i]), 4)} for i in top],
            })
        yamnet_latency_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            asr = asr_metadata(audio)
            asr_error = None
        except Exception as exc:
            asr = None
            asr_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        row = {
            "id": case_id,
            "description": description,
            "duration_seconds": round(len(audio) / RATE, 2),
            "yamnet_windows": windows,
            "yamnet_latency_ms": yamnet_latency_ms,
            "music_windows_ge_0_30": sum(item["music_score"] >= 0.30 for item in windows),
            "asr": asr,
            "asr_error": asr_error,
        }
        output["cases"].append(row)
        print(f"{case_id}: music windows >=0.30={row['music_windows_ge_0_30']}/{len(windows)}, ASR nonempty={asr and asr['nonempty']}, latency={asr and asr['latency_ms']} ms")

    target = args.output if args.output.is_absolute() else ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0 if all(item["asr_error"] is None for item in output["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
