"""Run a bounded live integration profile against the VoxCPM2 worker."""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.tts import TTSService, VoxCPMHttpClient  # noqa: E402


DEFAULT_TEXT = "Привет. Это проверка потоковой русской речи VoxCPM2."
LONG_TEXT = "Это длинный текст для проверки отмены при перебивании пользователя. " * 3


def _loopback_url(value: str) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("VoxCPM profile accepts a loopback HTTP URL only")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not accepted in the VoxCPM URL")
    return str(value).rstrip("/")


def _wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() <= 0:
            raise ValueError("provider returned a non-mono PCM16 WAV")
        duration = wav.getnframes() / wav.getframerate()
    if duration <= 0:
        raise ValueError("provider returned zero-duration audio")
    return duration


def _write_report(path: Path | None, report: dict[str, object]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9891")
    parser.add_argument("--voice", default="voxcpm-zero-shot")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--allow-live-model", action="store_true")
    parser.add_argument("--cancel-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    url = _loopback_url(args.url)
    if not 0.5 <= float(args.speed) <= 2.0:
        raise ValueError("speed must be between 0.5 and 2.0")
    if args.dry_run:
        print(json.dumps({"profile": "voxcpm", "url": url, "cancel_test": bool(args.cancel_test)}))
        return 0
    if not args.allow_live_model:
        report = {"profile": "voxcpm", "status": "refused", "reason": "allow_live_model_required"}
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 2

    client = VoxCPMHttpClient(url, timeout_seconds=args.timeout)
    service = TTSService(client)
    health = client.health()
    started = time.perf_counter()
    chunks: list[bytes] = []
    first_chunk = None
    stream_error = None
    stream = service.stream(args.text, voice=args.voice, speed=args.speed)
    try:
        for chunk in stream:
            if first_chunk is None:
                first_chunk = time.perf_counter() - started
            chunks.append(chunk)
    except Exception as exc:  # noqa: BLE001 - report the live provider failure
        stream_error = type(exc).__name__
    finally:
        stream.close()
    elapsed = time.perf_counter() - started
    audio_seconds = sum(_wav_seconds(chunk) for chunk in chunks)
    report: dict[str, object] = {
        "schema_version": 1,
        "profile": "voxcpm",
        "url": url,
        "voice": args.voice,
        "health": health,
        "status": "passed" if stream_error is None and chunks and health.get("status") == "ok" else "failed",
        "stream": {
            "chunks": len(chunks),
            "first_chunk_seconds": round(first_chunk, 3) if first_chunk is not None else None,
            "elapsed_seconds": round(elapsed, 3),
            "audio_seconds": round(audio_seconds, 3),
            "rtf": round(elapsed / audio_seconds, 3) if audio_seconds else None,
        },
        "stream_error": stream_error,
        "cancel": None,
        "limitation": "Measures worker native streaming and transport cancellation; subjective voice quality is not scored.",
    }

    if args.cancel_test and report["status"] == "passed":
        cancel_stream = service.stream(LONG_TEXT, voice=args.voice, speed=args.speed)
        cancel_error = None
        cancel_started = time.perf_counter()
        try:
            next(cancel_stream)
        except Exception as exc:  # noqa: BLE001 - cancellation profile evidence
            cancel_error = type(exc).__name__
        finally:
            cancel_stream.close()
        recovery_started = time.perf_counter()
        recovery = list(service.stream("После отмены контур продолжает работу.", voice=args.voice, speed=args.speed))
        report["cancel"] = {
            "first_chunk_or_error_seconds": round(time.perf_counter() - cancel_started, 3),
            "close_error": cancel_error,
            "recovery_chunks": len(recovery),
            "recovery_seconds": round(time.perf_counter() - recovery_started, 3),
            "passed": bool(recovery),
        }
        if not recovery:
            report["status"] = "failed"

    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
