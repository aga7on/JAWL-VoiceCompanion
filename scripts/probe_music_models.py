"""Offline CPU probe for experimental music classifiers and affect estimators."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import psutil

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "runtime" / "models" / "audio"
CASES = {
    "bach_toccata_music": ROOT / "runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3",
    "sax_instrument_music": ROOT / "runtime/vision-venv/Lib/site-packages/gradio/media_assets/audio/sax.wav",
    "russian_speech_01": ROOT / "runtime/synthetic-questions/question-01.wav",
    "russian_speech_02": ROOT / "runtime/synthetic-questions/question-02.wav",
    "russian_speech_03": ROOT / "runtime/synthetic-questions/question-03.wav",
    "english_speech": ROOT / "runtime/gemma4-e4b-cpu/cases/en_speech.wav",
    "synthetic_harmonic_chord": ROOT / "runtime/gemma4-e4b-cpu/cases/music.wav",
    "russian_speech_over_chord": ROOT / "runtime/gemma4-e4b-cpu/cases/speech_music.wav",
    "synthetic_noise": ROOT / "runtime/gemma4-e4b-cpu/cases/noise.wav",
    "synthetic_silence": ROOT / "runtime/gemma4-e4b-cpu/cases/silence.wav",
}


def decode(path: Path, rate: int, seconds: float) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-t", str(seconds), "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").copy()


def session(path: Path) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


def top(scores: np.ndarray, labels: list[str], n: int = 5) -> list[dict]:
    scores = np.asarray(scores).reshape(-1)
    indices = np.argsort(scores)[::-1][:n]
    return [{"label": labels[int(i)], "score": float(scores[i])} for i in indices]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runtime/audio-path-replay/out/music-model-candidate-probe-20261024.json")
    args = ap.parse_args()
    process = psutil.Process()
    rss_mib = lambda: round(process.memory_info().rss / 1048576, 1)
    result: dict = {"providers": ["CPUExecutionProvider"], "thread_count": 1, "rss_mib_before_sessions": rss_mib(), "cases": {}, "models": {}}
    hubert_path = AUDIO / "music-genre-hubert-v1-onnx/onnx/model_int8.onnx"
    yamnet_dir = AUDIO / "yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
    hubert_labels = ["blues", "classical", "country", "disco", "hiphop", "jazz", "metal", "pop", "reggae", "rock"]
    class_map = (yamnet_dir / "yamnet_class_map.csv").read_text(encoding="utf-8-sig").splitlines()
    yamnet_labels = [line.split(",", 2)[2].strip().strip('"') for line in class_map[1:]]
    hubert = session(hubert_path)
    result["models"]["hubert_genre_int8"] = {"rss_mib_after_session_load": rss_mib()}
    yamnet = session(yamnet_dir / "yamnet.onnx")
    result["models"]["yamnet"] = {"rss_mib_after_session_load": rss_mib()}
    for name, path in CASES.items():
        decoded: dict[int, np.ndarray] = {}
        case: dict = {"path": str(path.relative_to(ROOT)), "models": {}}
        for rate in (16000,):
            decoded[rate] = decode(path, rate, 16.0)
        signal = decoded[16000]
        rms = float(np.sqrt(np.mean(signal * signal))) if len(signal) else 0.0
        case["decoded"] = {"sample_rate_hz": 16000, "samples": len(signal), "duration_s": len(signal) / 16000, "rms": rms}
        # Hubert takes a 16 kHz normalized waveform; average independent 5 s crops.
        n = 5 * 16000
        crops = [signal[i:i+n] for i in range(0, max(1, len(signal)-n+1), n)]
        if len(signal) >= n and len(signal) % n >= 16000:
            crops.append(signal[-n:])
        if not crops and len(signal):
            crops = [signal]
        scores_by_crop, times, cpu_times = [], [], []
        for crop in crops:
            crop = crop.astype(np.float32)
            crop = (crop - crop.mean()) / max(float(crop.std()), 1e-7)
            t0 = time.perf_counter()
            c0 = process.cpu_times()
            logits = hubert.run(None, {"input_values": crop[None, :]})[0][0]
            times.append((time.perf_counter() - t0) * 1000)
            c1 = process.cpu_times()
            cpu_times.append(c1.user + c1.system - c0.user - c0.system)
            logits = logits - logits.max()
            probs = np.exp(logits) / np.exp(logits).sum()
            scores_by_crop.append(probs)
        mean_probs = np.mean(scores_by_crop, axis=0)
        case["models"]["hubert_genre_int8"] = {"top5_mean_crop_probabilities": top(mean_probs, hubert_labels), "crop_count": len(crops), "crop_inference_ms": times, "process_cpu_s_per_crop": cpu_times, "p50_ms": float(np.median(times)) if times else None, "p95_ms": float(np.percentile(times, 95)) if times else None, "rss_mib_after_inference": rss_mib()}
        # YAMNet scores represent ~0.96 s patches; preserve mean top tags and span.
        t0 = time.perf_counter()
        c0 = process.cpu_times()
        ys = yamnet.run(None, {"waveform": signal.astype(np.float32)})[0]
        elapsed = (time.perf_counter() - t0) * 1000
        c1 = process.cpu_times()
        mean_y = np.mean(ys, axis=0)
        window_rows = []
        window_samples, hop_samples = 2 * 16000, 1 * 16000
        for start in range(0, max(1, len(signal) - window_samples + 1), hop_samples):
            window = signal[start:start + window_samples]
            if len(window) < window_samples:
                window = np.pad(window, (0, window_samples - len(window)))
            win_scores = yamnet.run(None, {"waveform": window.astype(np.float32)})[0].mean(axis=0)
            window_rows.append({
                "start_s": round(start / 16000, 2),
                "music_score": float(win_scores[yamnet_labels.index("Music")]),
                "speech_score": float(win_scores[yamnet_labels.index("Speech")]),
                "top3": top(win_scores, yamnet_labels, 3),
            })
        case["models"]["yamnet"] = {"top5_mean_patch_scores": top(mean_y, yamnet_labels), "music_mean_patch_score": float(mean_y[yamnet_labels.index("Music")]), "patch_count": int(ys.shape[0]), "inference_ms": elapsed, "process_cpu_s": c1.user + c1.system - c0.user - c0.system, "rss_mib_after_inference": rss_mib(), "windows_2s_hop_1s": window_rows}
        result["cases"][name] = case
    for name, signal in (("digital_silence_control", np.zeros(5 * 16000, dtype=np.float32)), ("white_noise_control", np.random.default_rng(20261024).normal(0, 0.08, 5 * 16000).astype(np.float32))):
        case = {"path": "synthetic control; generated in memory", "decoded": {"sample_rate_hz": 16000, "samples": len(signal), "duration_s": 5.0, "rms": float(np.sqrt(np.mean(signal * signal)))}, "models": {}}
        crop = signal.copy()
        crop = (crop - crop.mean()) / max(float(crop.std()), 1e-7)
        t0 = time.perf_counter()
        logits = hubert.run(None, {"input_values": crop[None, :]})[0][0]
        elapsed = (time.perf_counter() - t0) * 1000
        logits -= logits.max()
        probs = np.exp(logits) / np.exp(logits).sum()
        case["models"]["hubert_genre_int8"] = {"top5_mean_crop_probabilities": top(probs, hubert_labels), "crop_count": 1, "crop_inference_ms": [elapsed], "p50_ms": elapsed, "p95_ms": elapsed}
        t0 = time.perf_counter()
        ys = yamnet.run(None, {"waveform": signal})[0]
        win_scores = ys.mean(axis=0)
        case["models"]["yamnet"] = {"top5_mean_patch_scores": top(np.mean(ys, axis=0), yamnet_labels), "music_mean_patch_score": float(np.mean(ys, axis=0)[yamnet_labels.index("Music")]), "patch_count": int(ys.shape[0]), "inference_ms": (time.perf_counter()-t0)*1000, "windows_2s_hop_1s": [{"start_s": 0.0, "music_score": float(win_scores[yamnet_labels.index("Music")]), "speech_score": float(win_scores[yamnet_labels.index("Speech")]), "top3": top(win_scores, yamnet_labels, 3)}]}
        result["cases"][name] = case
    mert_path = AUDIO / "mert-v1-95m-music-emotion-int8/mert_emotion_int8.onnx"
    if mert_path.exists() and mert_path.stat().st_size > 80_000_000:
        mert = session(mert_path)
        result["models"]["mert"] = {"inputs": [(x.name, x.shape, x.type) for x in mert.get_inputs()], "outputs": [(x.name, x.shape, x.type) for x in mert.get_outputs()], "rss_mib_after_session_load": rss_mib()}
        mert_cases = {name: path for name, path in CASES.items()}
        for name, path in mert_cases.items():
            x = decode(path, 24000, 15.0)
            if len(x) < 360000:
                x = np.pad(x, (0, 360000-len(x)))
            else:
                x = x[:360000]
            t0 = time.perf_counter()
            y = mert.run(None, {mert.get_inputs()[0].name: x.astype(np.float32)[None, :]})
            elapsed = (time.perf_counter() - t0) * 1000
            result["cases"][name]["models"]["mert_emotion"] = {"output_shapes": [list(a.shape) for a in y], "outputs": [np.asarray(a).reshape(-1).tolist() for a in y], "inference_ms": elapsed}
        for name in ("digital_silence_control", "white_noise_control"):
            x = result["cases"][name]
            signal = np.zeros(360000, dtype=np.float32) if name == "digital_silence_control" else np.random.default_rng(20261024).normal(0, 0.08, 360000).astype(np.float32)
            t0 = time.perf_counter()
            y = mert.run(None, {mert.get_inputs()[0].name: signal[None, :]})
            x["models"]["mert_emotion"] = {"output_shapes": [list(a.shape) for a in y], "outputs": [np.asarray(a).reshape(-1).tolist() for a in y], "inference_ms": (time.perf_counter()-t0)*1000}
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
