"""Paired CPU-only YAMNet/GigaAM probe for speech over external music.

All waveforms are generated or loaded locally and kept in memory or short-lived
temporary directories. The report stores scores and ASR quality metrics only;
it never stores decoded transcript text or raw PCM.
"""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
RATE = 16_000
ASR_EXE = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
ASR_MODEL = ROOT / "runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf"
YAMNET_DIR = ROOT / "runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
SPEECH = {
    "ru_01": (ROOT / "runtime/synthetic-questions/question-01.wav", "статус"),
    "ru_02": (ROOT / "runtime/synthetic-questions/question-02.wav", "короткие"),
    "ru_03": (ROOT / "runtime/synthetic-questions/question-03.wav", "тестовый"),
}
MUSIC = {
    "bach_toccata": (ROOT / "runtime/crane-repo/data/audio/toccata-amp-fugue-js-bach.mp3", 10.0),
    "saxophone": (ROOT / "runtime/vision-venv/Lib/site-packages/gradio/media_assets/audio/sax.wav", 5.0),
}


def decode(path: Path, seconds: float = 5.0, start: float = 0.0) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(seconds), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").copy()


def encode_wav(samples: np.ndarray) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    import io
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
        wav.writeframes(pcm16.tobytes())
    return out.getvalue()


def normalize_rms(x: np.ndarray, target: float = 0.10) -> np.ndarray:
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    return x.astype(np.float32) * (target / max(rms, 1e-8))


def mix_snr(speech: np.ndarray, music: np.ndarray, speech_over_music_db: float) -> np.ndarray:
    n = max(len(speech), len(music))
    s = np.pad(normalize_rms(speech), (0, max(0, n - len(speech))))[:n]
    m = np.pad(normalize_rms(music), (0, max(0, n - len(music))))[:n]
    # Positive speech-over-music SNR means music is quieter than speech.
    m *= 10.0 ** (-speech_over_music_db / 20.0)
    mixed = s + m
    peak = float(np.max(np.abs(mixed))) if len(mixed) else 0.0
    if peak > 0.95:
        mixed *= 0.95 / peak
    return mixed.astype(np.float32)


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalize_text(text: str) -> str:
    return "".join(ch.casefold() for ch in text if ch.isalnum())


def top_tags(scores: np.ndarray, labels: list[str], count: int = 5) -> list[dict]:
    indices = np.argsort(scores)[::-1][:count]
    return [{"label": labels[int(i)], "score": round(float(scores[i]), 4)} for i in indices]


def transcribe(samples: np.ndarray, expected_hint: str | None) -> dict:
    wav_bytes = encode_wav(samples)
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="jawl-yamnet-gigaam-") as tmp:
        root = Path(tmp)
        wav_path, prefix = root / "input.wav", root / "asr"
        wav_path.write_bytes(wav_bytes)
        proc = subprocess.run([str(ASR_EXE), "-m", str(ASR_MODEL), "-oj", "-of", str(prefix), str(wav_path)], cwd=tmp, capture_output=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"GigaAM exited with code {proc.returncode}")
        candidates = (root / "asr.json", root / "asr.wav.json")
        data = next((json.loads(p.read_text(encoding="utf-8")) for p in candidates if p.is_file()), None)
        if data is None:
            raise RuntimeError("GigaAM returned no JSON output")
        raw = data.get("transcription") or data.get("result") or data
        if isinstance(raw, list):
            text = " ".join(str(v.get("text", "") if isinstance(v, dict) else v) for v in raw)
        elif isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("transcription") or "")
        else:
            text = str(raw)
        clean = normalize_text(text)
        result = {"nonempty": bool(clean), "chars": len(clean), "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if expected_hint:
            hint = normalize_text(expected_hint)
            result["expected_hint_found"] = hint in clean
            result["hint_edit_distance"] = edit_distance(hint, clean)
            result["hint_length"] = len(hint)
        return result


def build_cases() -> list[dict]:
    speech = {key: (decode(path, seconds=8.0), hint) for key, (path, hint) in SPEECH.items()}
    music = {key: decode(path, seconds=5.0, start=offset) for key, (path, offset) in MUSIC.items()}
    cases = []
    for key, (samples, hint) in speech.items():
        cases.append({"id": f"speech_only_{key}", "kind": "speech_only", "audio": samples, "hint": hint})
    for key, samples in music.items():
        cases.append({"id": f"music_only_{key}", "kind": "music_only", "audio": samples, "hint": None})
    for speech_key, (spoken, hint) in speech.items():
        for music_key, track in music.items():
            for snr_db in (10, 0, -10):
                cases.append({"id": f"mix_{speech_key}_{music_key}_speech_snr_{snr_db}db", "kind": "speech_plus_music", "audio": mix_snr(spoken, track, snr_db), "hint": hint, "speech_over_music_db": snr_db, "speech_id": speech_key, "music_id": music_key})
    cases.append({"id": "noise_only", "kind": "noise_only", "audio": np.random.default_rng(20261024).normal(0, 0.045, 5 * RATE).astype(np.float32), "hint": None})
    cases.append({"id": "silence_only", "kind": "silence_only", "audio": np.zeros(5 * RATE, dtype=np.float32), "hint": None})
    return cases


def main() -> int:
    required = [ASR_EXE, ASR_MODEL, YAMNET_DIR / "yamnet.onnx", YAMNET_DIR / "yamnet_class_map.csv"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise FileNotFoundError("missing local probe dependencies: " + ", ".join(missing))
    opts = ort.SessionOptions(); opts.intra_op_num_threads = 1; opts.inter_op_num_threads = 1; opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    model = ort.InferenceSession(str(YAMNET_DIR / "yamnet.onnx"), sess_options=opts, providers=["CPUExecutionProvider"])
    labels = [line.split(",", 2)[2].strip().strip('"') for line in (YAMNET_DIR / "yamnet_class_map.csv").read_text(encoding="utf-8-sig").splitlines()[1:]]
    ix_music, ix_speech = labels.index("Music"), labels.index("Speech")
    output = {"schema_version": 1, "cpu_only": True, "onnx_providers": model.get_providers(), "yamnet_threads": {"intra": 1, "inter": 1}, "gigaam_model": ASR_MODEL.name, "raw_pcm_persisted": False, "transcript_text_persisted": False, "cases": []}
    for case in build_cases():
        x = case.pop("audio")
        windows = []
        t0 = time.perf_counter()
        for start in range(0, max(1, len(x) - 2 * RATE + 1), RATE):
            win = x[start:start + 2 * RATE]
            if len(win) < 2 * RATE:
                win = np.pad(win, (0, 2 * RATE - len(win)))
            scores = model.run(None, {"waveform": win.astype(np.float32)})[0].mean(axis=0)
            windows.append({"start_s": round(start / RATE, 1), "music_score": round(float(scores[ix_music]), 4), "speech_score": round(float(scores[ix_speech]), 4), "top_tags": top_tags(scores, labels)})
        case["yamnet_windows"] = windows
        case["yamnet_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        case["music_score_max"] = max((w["music_score"] for w in windows), default=0.0)
        case["music_score_median"] = round(float(np.median([w["music_score"] for w in windows])), 4) if windows else 0.0
        case["speech_score_max"] = max((w["speech_score"] for w in windows), default=0.0)
        try:
            case["gigaam"] = transcribe(x, case.get("hint"))
            case["asr_error"] = None
        except Exception as exc:
            case["gigaam"] = None
            case["asr_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        output["cases"].append(case)
        print(f"{case['id']}: YAMNet Music max={case['music_score_max']:.3f}, Speech max={case['speech_score_max']:.3f}; ASR={case['gigaam'] and case['gigaam'].get('nonempty')}; hint={case['gigaam'] and case['gigaam'].get('expected_hint_found')}")
    path = ROOT / "runtime/audio-path-replay/out/yamnet-gigaam-overlap-20261024.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    return 0 if all(c["asr_error"] is None for c in output["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
