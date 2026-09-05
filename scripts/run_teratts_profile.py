"""Guarded live profile for the local TeraTTSv2 REST worker."""

from __future__ import annotations

import argparse
import io
import json
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.tts import TeraTTSHttpClient  # noqa: E402


DEFAULT_TEXTS = (
    "Привет, это проверка TeraTTSv2.",
    "Система продолжает тестирование голосового контура.",
    "Сегодня проверяем русский синтез речи на локальном процессоре.",
    "Эта фраза проверяет стабильность выдачи WAV.",
    "Тест завершён.",
)


def _loopback_url(value: str) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("TeraTTS profile accepts a loopback HTTP URL only")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not accepted in the TeraTTS URL")
    return str(value).rstrip("/")


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _wav_info(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data or len(data) > 8 * 1024 * 1024:
        raise ValueError("provider returned empty or oversized audio")
    with wave.open(io.BytesIO(data), "rb") as wav:
        sample_rate = wav.getframerate()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or sample_rate <= 0:
            raise ValueError("provider returned a non-mono PCM16 WAV")
        duration = wav.getnframes() / sample_rate
    if duration <= 0:
        raise ValueError("provider returned zero-duration audio")
    return {
        "bytes": len(data),
        "sample_rate": sample_rate,
        "duration_seconds": round(duration, 3),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded live TeraTTSv2 worker profile")
    parser.add_argument("--url", default="http://127.0.0.1:9889")
    parser.add_argument("--voice", default="ru_f1")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--requests", type=int, default=5)
    parser.add_argument("--text", action="append", dest="texts", default=[])
    parser.add_argument("--allow-live-model", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    url = _loopback_url(args.url)
    texts = tuple(args.texts) if args.texts else DEFAULT_TEXTS
    if not 1 <= args.requests <= 20:
        raise ValueError("requests must be between 1 and 20")
    if not 0.5 <= float(args.speed) <= 2.0:
        raise ValueError("speed must be between 0.5 and 2.0")
    if args.dry_run:
        print(json.dumps({"profile": "teratts", "url": url, "requests": args.requests}, ensure_ascii=True))
        return 0
    if not args.allow_live_model:
        report = {"profile": "teratts", "status": "refused", "reason": "allow_live_model_required"}
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=True))
        return 2

    client = TeraTTSHttpClient(url, timeout_seconds=args.timeout)
    health = client.health()
    samples: list[dict[str, Any]] = []
    failure = None
    try:
        for index in range(args.requests):
            started = time.perf_counter()
            data = client.synthesize(texts[index % len(texts)], voice=args.voice, speed=args.speed)
            elapsed = time.perf_counter() - started
            sample = _wav_info(data)
            sample.update({
                "request": index + 1,
                "elapsed_seconds": round(elapsed, 3),
                "rtf": round(elapsed / sample["duration_seconds"], 3),
            })
            samples.append(sample)
    except Exception as exc:
        failure = type(exc).__name__

    elapsed_values = [item["elapsed_seconds"] for item in samples]
    rtf_values = [item["rtf"] for item in samples]
    sorted_elapsed = sorted(elapsed_values)
    report = {
        "schema_version": 1,
        "profile": "teratts",
        "status": "passed" if failure is None and len(samples) == args.requests and health.get("status") == "ok" else "failed",
        "url": url,
        "voice": args.voice,
        "requests": args.requests,
        "health": {"status": health.get("status"), "model": health.get("model"), "sample_rate": health.get("sample_rate")},
        "samples": samples,
        "complete_response_seconds": {
            "p50": round(statistics.median(elapsed_values), 3) if elapsed_values else None,
            "p95": round(sorted_elapsed[min(len(sorted_elapsed) - 1, int(len(sorted_elapsed) * 0.95))], 3) if elapsed_values else None,
        },
        "median_rtf": round(statistics.median(rtf_values), 3) if rtf_values else None,
        "failure": failure,
        "limitation": "Measures complete WAV response, not provider-native streaming first audio or acoustic microphone latency.",
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
