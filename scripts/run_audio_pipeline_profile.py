"""Guarded live smoke for Companion audio input, ASR, VoiceMem and TTS."""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import wave
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _loopback_url(value: str) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("audio profile accepts a loopback HTTP URL only")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not accepted in the Companion URL")
    return str(value).rstrip("/")


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _json_request(opener: Any, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read(256 * 1024).decode("utf-8"))


def _audio_info(data: bytes) -> dict[str, Any]:
    if not data.startswith(b"RIFF") or len(data) > 8 * 1024 * 1024:
        raise ValueError("TTS response is not a bounded WAV")
    with wave.open(io.BytesIO(data), "rb") as wav:
        rate = wav.getframerate()
        frames = wav.getnframes()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or rate <= 0 or frames <= 0:
            raise ValueError("TTS response is not mono PCM16 with positive duration")
    return {"bytes": len(data), "sample_rate": rate, "duration_seconds": round(frames / rate, 3)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded live Companion audio pipeline profile")
    # Audio endpoints belong to the Companion control plane, not JAWL's
    # separate native web console. The Companion default is 2367 in the
    # current profile; callers may override this for an alternate deployment.
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--session", default="audio-pipeline-profile")
    parser.add_argument("--chunk-frames", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-end-seconds", type=float, default=8.0)
    parser.add_argument("--tts-voice", default="ru_f1")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


def run(args: argparse.Namespace) -> int:
    base = _loopback_url(args.url)
    if not 128 <= args.chunk_frames <= 8192:
        raise ValueError("chunk-frames must be between 128 and 8192")
    if not 0.1 <= args.max_end_seconds <= 180.0:
        raise ValueError("max-end-seconds must be between 0.1 and 180")
    if args.dry_run:
        print(json.dumps({"profile": "audio_pipeline", "url": base, "wav": str(args.wav)}, ensure_ascii=True))
        return 0
    if not args.live:
        report = {"profile": "audio_pipeline", "status": "refused", "reason": "live_acknowledgement_required"}
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=True))
        return 2

    opener = build_opener()
    started = time.perf_counter()
    correlation_id = f"audio-profile-{uuid4().hex}"
    stage_times: dict[str, float] = {}
    failure = None
    chunks = 0
    pcm_bytes = 0
    result: dict[str, Any] = {}
    tts_info = None
    try:
        stage_started = time.perf_counter()
        with opener.open(Request(base + "/api/session", method="GET"), timeout=args.timeout) as response:
            session_body = json.loads(response.read(64 * 1024).decode("utf-8"))
            cookies = SimpleCookie(response.headers.get("Set-Cookie", ""))
        stage_times["session_bootstrap_seconds"] = round(time.perf_counter() - stage_started, 3)
        session_cookie = cookies.get("companion_session")
        csrf = session_body.get("csrf_token") if isinstance(session_body, dict) else None
        if session_cookie is None or not isinstance(csrf, str) or not csrf:
            raise ValueError("Companion session bootstrap was incomplete")
        headers = {
            "Cookie": f"companion_session={session_cookie.value}",
            "X-Companion-Session": session_cookie.value,
            "X-Companion-CSRF": csrf,
        }
        stage_started = time.perf_counter()
        with wave.open(str(args.wav), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("input WAV must be mono PCM16")
            sample_rate = wav.getframerate()
            while True:
                pcm = wav.readframes(args.chunk_frames)
                if not pcm:
                    break
                payload = _json_request(opener, base + "/api/voice/audio", headers, {
                    "session_id": args.session,
                    "sample_rate": sample_rate,
                    "channels": 1,
                    "pcm16_base64": base64.b64encode(pcm).decode("ascii"),
                }, args.timeout)
                if payload.get("ok") is not True or payload.get("mode") != "external_final_utterance":
                    raise ValueError("audio chunk was not accepted by external ASR mode")
                chunks += 1
                pcm_bytes += len(pcm)
        stage_times["asr_upload_seconds"] = round(time.perf_counter() - stage_started, 3)
        end_started = time.perf_counter()
        end = _json_request(opener, base + "/api/voice/end", headers, {"session_id": args.session, "correlation_id": correlation_id}, args.timeout)
        result = {
            "ok": end.get("ok"),
            "mode": end.get("mode"),
            "event_types": [item.get("type") for item in end.get("events", []) if isinstance(item, dict)],
            "response_count": len(end.get("responses", [])) if isinstance(end.get("responses"), list) else 0,
            "response_text_chars": len(str((end.get("responses") or [{}])[0].get("text", ""))) if isinstance(end.get("responses"), list) and end.get("responses") else 0,
            "end_seconds": round(time.perf_counter() - end_started, 3),
            "memory_sync": end.get("memory_sync"),
        }
        stage_times["final_response_seconds"] = result["end_seconds"]
        if result["ok"] is not True or result["mode"] != "external_final_utterance" or "VOICE_TURN" not in result["event_types"] or result["response_count"] != 1 or result["end_seconds"] > args.max_end_seconds:
            raise ValueError("audio pipeline did not produce one final voice response")
        if not args.skip_tts:
            response_text = end["responses"][0].get("text", "")
            request = Request(
                base + "/api/tts/synthesize",
                data=json.dumps({"text": response_text, "voice": args.tts_voice, "speed": 1.0}, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", **headers},
                method="POST",
            )
            tts_started = time.perf_counter()
            with opener.open(request, timeout=args.timeout) as response:
                tts_info = _audio_info(response.read(8 * 1024 * 1024))
            stage_times["tts_complete_seconds"] = round(time.perf_counter() - tts_started, 3)
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        failure = type(exc).__name__

    report = {
        "schema_version": 1,
        "profile": "audio_pipeline",
        "status": "passed" if failure is None else "failed",
        "url": base,
        "correlation_id": correlation_id,
        "wav": args.wav.name,
        "chunks": chunks,
        "pcm_bytes": pcm_bytes,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "stage_times": stage_times,
        "result": result,
        "tts": tts_info,
        "failure": failure,
        "raw_audio_persisted": False,
        "max_end_seconds": args.max_end_seconds,
        "limitation": "The profile validates bounded final-utterance ASR, non-blocking VoiceMem memory enqueue and optional TTS plumbing; it does not prove microphone acoustics, streaming partial ASR, provider-native LLM behavior, echo cancellation or barge-in.",
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
