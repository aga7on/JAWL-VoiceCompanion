"""Collect bounded live visual and system-audio sensor evidence from a running companion.

The monitor never records screen pixels or raw audio. It samples the companion's
status endpoints and stores captions, transcript/description observations, and
bounded counters in an operator-selected JSON report.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _request(opener: Any, url: str, *, headers: dict[str, str] | None = None,
             payload: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers or {})
    with opener.open(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} returned a non-object JSON response")
    return value


def _atomic_write(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _observation_key(event: dict[str, Any]) -> str:
    return str(event.get("event_id") or event.get("id") or json.dumps(event, sort_keys=True, ensure_ascii=False))


def _redact_content(value: Any, key: str = "") -> Any:
    """Keep sensor telemetry and categorical tags, never persist recognized prose."""
    normalized = key.casefold()
    if any(token in normalized for token in ("text", "transcript", "caption", "description", "prompt", "utterance", "content")):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(child_key): _redact_content(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_redact_content(child, key) for child in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:2367")
    parser.add_argument("--duration-seconds", type=float, default=300.0)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--start-audio", action="store_true",
                        help="start loopback capture for this run and stop it on exit")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.interval_seconds <= 0 or args.timeout <= 0:
        parser.error("duration, interval, and timeout must be positive")
    if args.report.exists():
        parser.error(f"report already exists: {args.report}")
    args.report.parent.mkdir(parents=True, exist_ok=True)

    base = args.base_url.rstrip("/")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    session = _request(opener, base + "/api/session", timeout=args.timeout)
    csrf = session.get("csrf_token")
    cookie = next((item.value for item in jar if item.name == "companion_session"), None)
    if not isinstance(csrf, str) or not csrf or not cookie:
        raise RuntimeError("companion session bootstrap failed")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": base,
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": cookie,
    }

    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "duration_requested_seconds": args.duration_seconds,
        "interval_seconds": args.interval_seconds,
        "raw_audio_persisted": False,
        "screen_pixels_persisted": False,
        "audio_started_by_monitor": False,
        "samples": [],
        "errors": [],
    }
    start_monotonic = time.monotonic()
    initial_observation_keys: set[str] = set()
    try:
        ambient = _request(opener, base + "/api/ambient-audio", headers=headers, timeout=args.timeout)
        memory = _request(opener, base + "/api/ambient-memory", headers=headers, timeout=args.timeout)
        initial_observation_keys = {
            _observation_key(item) for item in memory.get("observations", []) if isinstance(item, dict)
        }
        if args.start_audio:
            if ambient.get("configured") is not True or ambient.get("enabled") is not True:
                raise RuntimeError("ambient audio is not configured and enabled; refusing to start capture")
            if (ambient.get("capture") or {}).get("running") is True:
                raise RuntimeError("ambient capture is already running; refusing to claim ownership")
            result = _request(opener, base + "/api/ambient-audio/start", headers=headers,
                              payload={}, timeout=args.timeout)
            report["audio_started_by_monitor"] = bool(result.get("ok"))

        while True:
            now = time.monotonic()
            elapsed = now - start_monotonic
            if elapsed >= args.duration_seconds:
                break
            sample: dict[str, Any] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(elapsed, 3),
            }
            try:
                vision = _request(opener, base + "/api/vision/status", timeout=args.timeout)
                sensor = vision.get("visual_sensor") if isinstance(vision.get("visual_sensor"), dict) else {}
                audio = _request(opener, base + "/api/ambient-audio", headers=headers, timeout=args.timeout)
                bridge = audio.get("bridge") if isinstance(audio.get("bridge"), dict) else {}
                capture = audio.get("capture") if isinstance(audio.get("capture"), dict) else {}
                memory = _request(opener, base + "/api/ambient-memory", headers=headers, timeout=args.timeout)
                new_observations = [
                    item for item in memory.get("observations", [])
                    if isinstance(item, dict) and _observation_key(item) not in initial_observation_keys
                ]
                sample.update({
                    "visual_sensor": _redact_content(sensor),
                    "ambient_audio": {
                        "configured": audio.get("configured"),
                        "enabled": audio.get("enabled"),
                        "paused": audio.get("paused"),
                        "capture": capture,
                        "bridge": bridge,
                    },
                    "new_ambient_observations": _redact_content(new_observations[-20:]),
                })
                initial_observation_keys.update(_observation_key(item) for item in new_observations)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
                report["errors"].append({"at": sample["at"], "elapsed_seconds": sample["elapsed_seconds"],
                                         "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            report["samples"].append(sample)
            _atomic_write(args.report, report)
            sampled_at = time.monotonic()
            delay = args.interval_seconds - (sampled_at - now)
            if delay > 0:
                time.sleep(min(delay, max(0.0, args.duration_seconds - (sampled_at - start_monotonic))))
    finally:
        if report["audio_started_by_monitor"]:
            try:
                report["audio_stop"] = _request(opener, base + "/api/ambient-audio/stop", headers=headers,
                                                 payload={}, timeout=args.timeout)
            except Exception as exc:  # report cleanup failure without hiding original failure
                report["errors"].append({"at": datetime.now(timezone.utc).isoformat(),
                                         "error": f"audio-stop {type(exc).__name__}: {str(exc)[:300]}"})
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["elapsed_seconds"] = round(time.monotonic() - start_monotonic, 3)
        report["sample_count"] = len(report["samples"])
        report["error_count"] = len(report["errors"])
        _atomic_write(args.report, report)

    descriptions = [
        sample.get("ambient_audio", {}).get("bridge", {}).get("audio_description_count", 0)
        for sample in report["samples"]
    ]
    print(json.dumps({
        "report": str(args.report),
        "elapsed_seconds": report["elapsed_seconds"],
        "samples": report["sample_count"],
        "errors": report["error_count"],
        "audio_started_by_monitor": report["audio_started_by_monitor"],
        "audio_description_count_first_last": [descriptions[0], descriptions[-1]] if descriptions else [],
    }, ensure_ascii=False))
    return 0 if report["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
