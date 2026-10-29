"""Capability and latency probe for the experimental Gemma 4 E4B CPU describer."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.gemma_sensory import (  # noqa: E402
    GemmaSensoryClient,
    GemmaSensoryStream,
    normalize_observation,
)
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402
from jawl_voicecompanion.system_audio import SystemAudioLoopback  # noqa: E402


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"expected PCM16: {path}")
    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return data, rate


def _write_wav(path: Path, data: np.ndarray, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(np.asarray(data, dtype=np.int16).tobytes())


def _fit(data: np.ndarray, seconds: float = 4.0, rate: int = 16000) -> np.ndarray:
    length = int(seconds * rate)
    if len(data) < length:
        return np.pad(data, (0, length - len(data)))
    return data[:length]


def _sapi(path: Path, voice: str, text: str) -> bool:
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('{voice}'); "
        f"$s.SetOutputToWaveFile('{path}'); "
        f"$s.Speak('{text}'); "
        "$s.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            check=True,
            timeout=30,
            capture_output=True,
        )
        return path.is_file()
    except Exception:
        return False


def prepare_cases(cases: Path) -> dict[str, Path]:
    cases.mkdir(parents=True, exist_ok=True)
    produced: dict[str, Path] = {}
    ru_source = ROOT / "runtime/synthetic-questions/question-01.wav"
    if ru_source.is_file():
        data, rate = _read_wav(ru_source)
        if rate != 16000:
            indices = (np.arange(int(len(data) * 16000 / rate)) * rate / 16000).astype(int)
            data = data[indices]
        ru = _fit(data.astype(np.int16))
        path = cases / "ru_speech.wav"
        _write_wav(path, ru)
        produced["ru_speech"] = path
    else:
        ru = None

    en_path = cases / "en_speech.wav"
    if not en_path.is_file():
        _sapi(en_path, "Microsoft Zira Desktop", "This is a short English speech sample for the sensory experiment.")
    if en_path.is_file():
        produced["en_speech"] = en_path

    t = np.arange(16000 * 4, dtype=np.float32) / 16000.0
    chord = (
        0.20 * np.sin(2 * math.pi * 220 * t)
        + 0.14 * np.sin(2 * math.pi * 277 * t)
        + 0.10 * np.sin(2 * math.pi * 330 * t)
        + 0.05 * np.sin(2 * math.pi * 440 * t)
    )
    music = np.clip(chord * 32767, -32768, 32767).astype(np.int16)
    music_path = cases / "music.wav"
    _write_wav(music_path, music)
    produced["music"] = music_path

    rng = np.random.default_rng(17)
    noise = np.clip(rng.normal(0, 2200, 16000 * 4), -32768, 32767).astype(np.int16)
    noise_path = cases / "noise.wav"
    _write_wav(noise_path, noise)
    produced["noise"] = noise_path

    silence_path = cases / "silence.wav"
    _write_wav(silence_path, np.zeros(16000 * 4, dtype=np.int16))
    produced["silence"] = silence_path

    if ru is not None:
        mixed = np.clip(ru.astype(np.float32) * 0.72 + music.astype(np.float32) * 0.45, -32768, 32767)
        mixed_path = cases / "speech_music.wav"
        _write_wav(mixed_path, mixed.astype(np.int16))
        produced["speech_music"] = mixed_path
    return produced


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 1)


def summarize(results: list[dict], *, quant: str) -> dict:
    ok = [item for item in results if item.get("status") == "ok"]
    ttfts = [float(item["ttft_ms"]) for item in ok if isinstance(item.get("ttft_ms"), (int, float))]
    totals = [float(item["total_ms"]) for item in ok if isinstance(item.get("total_ms"), (int, float))]
    return {
        "quant": quant,
        "runs": len(results),
        "ok": len(ok),
        "format_errors": sum(1 for item in results if item.get("status") == "invalid_json"),
        "schema_invalid": sum(1 for item in ok if not item.get("schema_valid")),
        "http_errors": sum(1 for item in results if item.get("status") == "http_error"),
        "request_errors": sum(1 for item in results if item.get("status") == "request_error"),
        "ttft_ms": {
            "p50": statistics.median(ttfts) if ttfts else None,
            "p95": _percentile(ttfts, 0.95),
            "min": min(ttfts) if ttfts else None,
            "max": max(ttfts) if ttfts else None,
        },
        "total_ms": {
            "p50": statistics.median(totals) if totals else None,
            "p95": _percentile(totals, 0.95),
            "min": min(totals) if totals else None,
            "max": max(totals) if totals else None,
        },
        "results": results,
    }


def run_cases(args: argparse.Namespace) -> dict:
    client = GemmaSensoryClient(args.server_url, model=args.model, timeout=args.timeout)
    try:
        health = client.health()
    except Exception as exc:  # noqa: BLE001
        return {"status": "server_unavailable", "error": f"{type(exc).__name__}: {exc}"}
    images = [p for p in (ROOT / "runtime/live-sensory-run/display1.jpg", ROOT / "runtime/live-sensory-run/display2.jpg") if p.is_file()]
    audio_cases = prepare_cases(ROOT / "runtime/gemma4-e4b-cpu/cases")
    cases: list[tuple[str, bytes | None, bytes | None]] = []
    if args.case in {"all", "image"}:
        for index, image in enumerate(images):
            cases.append((f"image_{index + 1}", image.read_bytes(), None))
    if args.case in {"all", "audio"}:
        for name, path in audio_cases.items():
            cases.append((name, None, path.read_bytes()))
    if args.case in {"all", "combined"} and images:
        image = images[0].read_bytes()
        for name in ("ru_speech", "music", "speech_music", "noise", "silence"):
            path = audio_cases.get(name)
            if path:
                cases.append((f"combined_{name}", image, path.read_bytes()))
    results: list[dict] = []
    for name, image, audio in cases:
        for run in range(max(1, int(args.runs))):
            started = time.perf_counter()
            result = client.describe(image_bytes=image, audio_wav_bytes=audio, max_tokens=args.max_tokens)
            result["case"] = name
            result["run"] = run
            result["wall_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            result["source"] = "combined" if image and audio else "screen" if image else "audio"
            if result.get("status") == "ok":
                now = time.time()
                frame = normalize_observation(
                    result.get("payload"),
                    source=result["source"],
                    observed_interval=[now, now],
                    observed_at=now,
                    processed_at=time.time(),
                    model=args.model,
                    quant=args.quant,
                )
                result["schema_valid"] = frame["schema_valid"]
            else:
                result["schema_valid"] = False
            results.append(result)
    summary = {
        "status": "ok",
        "profile": "gemma4-e4b-cpu",
        "model": args.model,
        "server_url": args.server_url,
        "health": health,
        "images": [str(path) for path in images],
        "audio_cases": {name: str(path) for name, path in audio_cases.items()},
        "summary": summarize(results, quant=args.quant),
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_live(args: argparse.Namespace) -> dict:
    client = GemmaSensoryClient(args.server_url, model=args.model, timeout=args.timeout)
    capture = ScreenCaptureAdapter(enabled=True, max_width=960, max_height=720)
    loopback = SystemAudioLoopback(lambda *_: None, session_id="gemma4-e4b-probe")
    output = Path(args.out or (ROOT / f"runtime/gemma4-e4b-cpu/out/live-{args.quant}.jsonl"))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    stream = GemmaSensoryStream(
        client=client,
        screen_capture=capture,
        audio_loopback=loopback,
        target_title=args.target_title,
        output_path=str(output),
        quant=args.quant,
        frame_interval_s=args.frame_interval,
        audio_window_s=args.audio_window,
        audio_step_s=args.audio_step,
    )
    stream.start()
    started = time.time()
    samples = []
    try:
        while time.time() - started < max(5, int(args.duration)):
            time.sleep(5)
            samples.append({"at_s": round(time.time() - started, 1), **stream.state()})
    finally:
        stream.stop()
    summary = {
        "status": "ok",
        "profile": "gemma4-e4b-cpu",
        "quant": args.quant,
        "duration_s": round(time.time() - started, 1),
        "output": str(output),
        "final": stream.state(),
        "samples": samples,
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", default="http://127.0.0.1:8997")
    parser.add_argument("--model", default="gemma4-e4b")
    parser.add_argument("--quant", choices=["q2", "q4"], default="q2")
    parser.add_argument("--case", choices=["all", "image", "audio", "combined"], default="all")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--out", default="")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument("--target-title", default="YouTube")
    parser.add_argument("--frame-interval", type=float, default=1.0)
    parser.add_argument("--audio-window", type=float, default=4.0)
    parser.add_argument("--audio-step", type=float, default=2.0)
    args = parser.parse_args()
    result = run_live(args) if args.live else run_cases(args)
    print(json.dumps({key: value for key, value in result.items() if key not in {"results", "samples"}}, ensure_ascii=False, indent=2))
    if "summary" in result:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
