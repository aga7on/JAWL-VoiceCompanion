"""Guarded live profile for an OpenAI-compatible final-utterance ASR worker."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.asr import ASRNoSpeech, OpenAICompatibleASRClient  # noqa: E402


def _loopback_url(value: str) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ASR profile accepts a loopback HTTP URL only")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not accepted in the ASR URL")
    return str(value).rstrip("/")


def _load_expectations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    expectations: dict[str, dict[str, Any]] = {}
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        for item in payload["cases"]:
            if isinstance(item, dict) and item.get("file"):
                expectations[str(item["file"])] = {
                    "must_transcribe": bool(item.get("must_transcribe", True)),
                    "min_chars": int(item.get("min_chars", 1)),
                }
        return expectations
    if isinstance(payload, dict):
        for name, spec in payload.items():
            if isinstance(name, str) and isinstance(spec, dict) and "must_transcribe" in spec:
                expectations[name] = {
                    "must_transcribe": bool(spec.get("must_transcribe", True)),
                    "min_chars": int(spec.get("min_chars", 1)),
                }
    return expectations


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() not in {1, 2} or wav.getsampwidth() != 2 or wav.getframerate() <= 0:
            raise ValueError("WAV must be PCM16 with one or two channels")
        duration = wav.getnframes() / wav.getframerate()
    if duration <= 0:
        raise ValueError("WAV must have a positive duration")
    return duration


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded live final-utterance ASR profile")
    parser.add_argument("--url", default="http://127.0.0.1:8984/v1")
    parser.add_argument("--model", default="Qwen3-ASR-0.6B")
    parser.add_argument("--wav", type=Path, action="append", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--allow-live-model", action="store_true")
    parser.add_argument("--expects", type=Path, default=None,
                        help="cases.json manifest (or file->spec mapping) with per-file must_transcribe/min_chars")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    url = _loopback_url(args.url)
    paths = tuple(Path(item) for item in args.wav)
    if not 1 <= len(paths) <= 20:
        raise ValueError("wav count must be between 1 and 20")
    expectations = _load_expectations(getattr(args, "expects", None))
    if args.dry_run:
        print(json.dumps({"profile": "asr", "url": url, "wav_count": len(paths), "expected_files": len(expectations)}, ensure_ascii=True))
        return 0
    if not args.allow_live_model:
        report = {"profile": "asr", "status": "refused", "reason": "allow_live_model_required"}
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=True))
        return 2

    client = OpenAICompatibleASRClient(url, args.model, timeout_seconds=args.timeout)
    health = client.health()
    samples: list[dict[str, Any]] = []
    failure = None
    try:
        for index, path in enumerate(paths, start=1):
            if not path.is_file():
                raise FileNotFoundError(path)
            expectation = expectations.get(path.name, {"must_transcribe": True, "min_chars": 1})
            audio = path.read_bytes()
            duration = _wav_duration(path)
            started = time.perf_counter()
            transcript = ""
            error = None
            try:
                transcript = client.transcribe(audio, filename=path.name)
            except ASRNoSpeech:
                transcript = ""
            except Exception as exc:
                error = type(exc).__name__
            elapsed = time.perf_counter() - started
            transcribed = bool(transcript.strip()) and len(transcript.strip()) >= int(expectation["min_chars"])
            accepted = False if error is not None else (transcribed or not expectation["must_transcribe"])
            samples.append({
                "request": index,
                "file": path.name,
                "duration_seconds": round(duration, 3),
                "elapsed_seconds": round(elapsed, 3),
                "rtf": round(elapsed / duration, 3) if duration else None,
                "transcript_chars": len(transcript),
                "non_empty": bool(transcript.strip()),
                "must_transcribe": bool(expectation["must_transcribe"]),
                "min_chars": int(expectation["min_chars"]),
                "accepted": bool(accepted),
                "accepted_empty": error is None and not transcript.strip() and not expectation["must_transcribe"],
                "error": error,
            })
    except Exception as exc:
        failure = type(exc).__name__

    rtf_values = [item["rtf"] for item in samples if item["rtf"] is not None]
    report = {
        "schema_version": 2,
        "profile": "asr",
        "status": "passed" if failure is None and len(samples) == len(paths) and health.get("status") == "online" and all(item["accepted"] for item in samples) else "failed",
        "url": url,
        "model": args.model,
        "health": {"status": health.get("status"), "mode": health.get("mode"), "model": health.get("model")},
        "samples": samples,
        "median_rtf": round(statistics.median(rtf_values), 3) if rtf_values else None,
        "failure": failure,
        "raw_audio_persisted": False,
        "limitation": "Final-utterance multipart evidence only; it does not prove streaming partial ASR, microphone capture, echo cancellation or barge-in.",
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
