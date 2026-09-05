"""Bounded live VoiceMem profile runner for an explicit local model smoke."""

from __future__ import annotations

import argparse
import json
import time
import wave
from collections import Counter
from pathlib import Path
from typing import Any

from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded real VoiceMem WAV profile")
    parser.add_argument("--python", dest="python_executable", required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--session", default="voicemem-profile")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-frames", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--warmup", choices=("none", "text", "audio"), default="none")
    parser.add_argument("--local-memory", action="store_true")
    parser.add_argument("--allow-live-model", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(json.dumps({
            "profile": "voicemem",
            "wav": str(args.wav),
            "warmup": args.warmup,
            "local_memory": bool(args.local_memory),
            "allow_live_model": bool(args.allow_live_model),
        }, ensure_ascii=False))
        return 0
    if not args.allow_live_model:
        report = {"profile": "voicemem", "status": "refused", "reason": "allow_live_model_required"}
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 2
    if not args.wav.is_file():
        report = {"profile": "voicemem", "status": "failed", "reason": "wav_not_found"}
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 1
    if args.chunk_frames < 32 or args.chunk_frames > 8192:
        raise ValueError("chunk-frames must be between 32 and 8192")

    sidecar_args = []
    if args.local_memory:
        sidecar_args.append("--local-memory")
    client = VoiceMemProcessClient(
        args.python_executable,
        args=tuple(sidecar_args),
        timeout_seconds=args.timeout,
    )
    started = time.perf_counter()
    warmup_seconds = None
    events: list[dict[str, Any]] = []
    chunks = 0
    first_partial_ms = None
    first_turn_ms = None
    failure = None
    try:
        if args.warmup != "none":
            warmup_started = time.perf_counter()
            events.extend(client.warmup(kind=args.warmup))
            warmup_seconds = time.perf_counter() - warmup_started
        with wave.open(str(args.wav), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("WAV must be mono PCM16")
            if wav.getframerate() != args.sample_rate:
                raise ValueError("WAV sample rate does not match --sample-rate")
            while True:
                chunk = wav.readframes(args.chunk_frames)
                if not chunk:
                    break
                chunks += 1
                result = client.feed_audio(
                    chunk,
                    sample_rate=args.sample_rate,
                    session_id=args.session,
                )
                events.extend(result)
                elapsed_ms = (time.perf_counter() - started) * 1000
                if first_partial_ms is None and any(item.get("type") == "USER_PARTIAL" for item in result):
                    first_partial_ms = round(elapsed_ms, 1)
                if first_turn_ms is None and any(item.get("type") == "VOICE_TURN" for item in result):
                    first_turn_ms = round(elapsed_ms, 1)
            result = client.end_audio(session_id=args.session)
            events.extend(result)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if first_turn_ms is None and any(item.get("type") == "VOICE_TURN" for item in result):
                first_turn_ms = round(elapsed_ms, 1)
    except Exception as exc:
        failure = type(exc).__name__
    finally:
        health = None
        try:
            health = client.health()
        except Exception:
            health = {"status": "unavailable"}
        client.close()

    counts = Counter(str(item.get("type")) for item in events if isinstance(item, dict))
    report = {
        "schema_version": 1,
        "profile": "voicemem",
        "status": "passed" if failure is None and counts["VOICE_TURN"] > 0 else "failed",
        "warmup": args.warmup,
        "warmup_seconds": round(warmup_seconds, 3) if warmup_seconds is not None else None,
        "chunks": chunks,
        "event_counts": dict(counts),
        "first_partial_ms": first_partial_ms,
        "first_turn_ms": first_turn_ms,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "health": {
            "status": health.get("status") if isinstance(health, dict) else "unavailable",
            "process_status": (health.get("process") or {}).get("status") if isinstance(health, dict) else None,
            "audio_models_loaded": health.get("audio_models_loaded") if isinstance(health, dict) else None,
        },
        "failure": failure,
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    return run(_build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
