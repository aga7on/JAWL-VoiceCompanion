"""CPU-only, privacy-preserving live music probe for the selected WASAPI output.

PCM is held only in memory during capture/inference. The JSON artifact contains
YAMNet scores/tags, scalar signal levels, and ASR presence/length only; it never
contains raw audio or transcript text.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.system_audio import SystemAudioLoopback  # noqa: E402


def _overlap_helpers():
    spec = importlib.util.spec_from_file_location(
        "jawl_overlap_probe", ROOT / "scripts" / "probe_yamnet_gigaam_overlap.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load local ASR probe helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resample_pcm(raw: bytes, sample_rate: int, channels: int, target_rate: int) -> np.ndarray:
    command = [
        "ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(sample_rate),
        "-ac", str(channels), "-i", "pipe:0", "-ac", "1", "-ar", str(target_rate),
        "-f", "f32le", "pipe:1",
    ]
    completed = subprocess.run(command, input=raw, capture_output=True, check=True)
    return np.frombuffer(completed.stdout, dtype="<f4").copy()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=15.0, help="capture duration in seconds (4–60)")
    parser.add_argument("--device-name", default="DigitalOutput (NVIDIA High Definition Audio)")
    parser.add_argument("--out", default="runtime/audio-path-replay/out/live-music-loopback-probe.json")
    args = parser.parse_args()
    if not 4 <= args.duration <= 60:
        parser.error("--duration must be between 4 and 60 seconds")

    chunks: list[bytes] = []
    captured_bytes = 0
    device: dict = {}

    def consume(data: bytes, sample_rate: int, channels: int, session_id: str) -> None:
        nonlocal captured_bytes
        byte_cap = sample_rate * channels * 2 * 60
        if captured_bytes < byte_cap:
            value = bytes(data)
            chunks.append(value)
            captured_bytes += len(value)

    capture = SystemAudioLoopback(
        consume,
        session_id="live-music-probe",
        output_device_name=args.device_name,
        frames_per_buffer=1024,
        queue_size=64,
    )
    started = time.monotonic()
    try:
        device = capture.start()
        deadline = started + args.duration
        while time.monotonic() < deadline:
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    finally:
        stopped = capture.stop(timeout=4.0)

    rate = int(device.get("sample_rate") or 0)
    channels = int(device.get("channels") or 0)
    raw = b"".join(chunks)
    waveform = _resample_pcm(raw, rate, channels, 16000) if raw and rate and channels else np.zeros(0, dtype=np.float32)
    rms = float(np.sqrt(np.mean(waveform * waveform))) if waveform.size else 0.0
    rms_dbfs = 20.0 * np.log10(max(rms, 1e-8))
    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    has_analysis_window = waveform.size >= 2 * 16000
    audible_signal = bool(has_analysis_window and rms_dbfs >= -55.0)
    capture_status = "captured" if audible_signal else (
        "no_audio" if has_analysis_window else "insufficient_audio"
    )
    result: dict = {
        "schema_version": 1,
        "cpu_only": True,
        "status": capture_status,
        "capture_opened": bool(device),
        "audio_signal_detected": audible_signal,
        "device": device.get("device"),
        "device_index": device.get("device_index"),
        "sample_rate": rate,
        "channels": channels,
        "duration_s": round(waveform.size / 16000, 2),
        "chunks": stopped.get("chunks"),
        "consumer_chunks": stopped.get("consumer_chunks"),
        "dropped_chunks": stopped.get("dropped_chunks"),
        "last_error": stopped.get("last_error"),
        "pcm_rms": round(rms, 6),
        "pcm_rms_dbfs": round(float(rms_dbfs), 1),
        "pcm_peak": round(peak, 6),
        "raw_pcm_persisted": False,
        "transcript_text_persisted": False,
        "yamnet": None,
        "gigaam": None,
        "mert_affect": {"status": "skipped_music_not_established"},
    }
    if waveform.size >= 2 * 16000:
        helper = _overlap_helpers()
        yamnet_dir = helper.YAMNET_DIR
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        model = ort.InferenceSession(
            str(yamnet_dir / "yamnet.onnx"), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        labels = [
            row.split(",", 2)[2].strip().strip('"')
            for row in (yamnet_dir / "yamnet_class_map.csv").read_text(encoding="utf-8-sig").splitlines()[1:]
        ]
        music_ix, speech_ix = labels.index("Music"), labels.index("Speech")
        windows = []
        inference_ms = []
        for offset in range(0, waveform.size - 2 * 16000 + 1, 16000):
            clip = waveform[offset:offset + 2 * 16000].astype(np.float32)
            before = time.perf_counter()
            scores = model.run(None, {"waveform": clip})[0].mean(axis=0)
            inference_ms.append((time.perf_counter() - before) * 1000)
            windows.append({
                "start_s": round(offset / 16000, 1),
                "music_score": round(float(scores[music_ix]), 4),
                "speech_score": round(float(scores[speech_ix]), 4),
                "top_tags": helper.top_tags(scores, labels, 7),
            })
        persistent_music = sum(row["music_score"] >= 0.3 for row in windows) >= 2
        result["yamnet"] = {
            "providers": model.get_providers(),
            "intra_threads": 1,
            "inter_threads": 1,
            "windows": windows,
            "music_max": max((row["music_score"] for row in windows), default=0.0),
            "music_median": round(float(np.median([row["music_score"] for row in windows])), 4),
            "persistent_music_gate": persistent_music,
            "mean_window_ms": round(float(np.mean(inference_ms)), 2) if inference_ms else None,
        }
        asr = helper.transcribe(waveform, None)
        result["gigaam"] = {
            "nonempty": asr["nonempty"],
            "text_chars": asr["chars"],
            "latency_ms": asr["latency_ms"],
        }
        if persistent_music:
            mert_path = ROOT / "runtime/models/audio/mert-v1-95m-music-emotion-int8/mert_emotion_int8.onnx"
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            mert = ort.InferenceSession(str(mert_path), sess_options=options, providers=["CPUExecutionProvider"])
            audio24 = _resample_pcm(raw, rate, channels, 24000)
            frame = np.zeros(360000, dtype=np.float32)
            frame[:min(frame.size, audio24.size)] = audio24[:frame.size]
            before = time.perf_counter()
            values = mert.run(None, {mert.get_inputs()[0].name: frame[None, :]})
            result["mert_affect"] = {
                "status": "conditional_music_gate_passed",
                "provider": mert.get_providers()[0],
                "inference_ms": round((time.perf_counter() - before) * 1000, 1),
                "outputs": [np.asarray(value).reshape(-1).tolist() for value in values],
                "interpretation": "soundtrack features only; not listener emotion",
            }
    else:
        result["status"] = "insufficient_audio"

    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "device": result["device"], "duration_s": result["duration_s"],
        "capture_opened": result["capture_opened"], "audio_signal_detected": result["audio_signal_detected"],
        "chunks": result["chunks"], "dropped_chunks": result["dropped_chunks"],
        "yamnet": result["yamnet"], "gigaam": result["gigaam"], "mert_affect": result["mert_affect"],
        "raw_pcm_persisted": False, "transcript_text_persisted": False,
    }, ensure_ascii=False))
    return 0 if result["status"] == "captured" and result["last_error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
