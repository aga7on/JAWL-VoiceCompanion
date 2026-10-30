"""Ten-minute live sensory/history acceptance against a running companion.

Stores text observations and counters only; screen pixels and PCM are never
requested or persisted. The existing companion must already be running.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def request(opener: Any, base: str, path: str, headers: dict[str, str] | None = None,
            payload: dict[str, Any] | None = None, timeout: float = 120) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, headers=headers or {})
    with opener.open(req, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8", errors="replace"))
    return result if isinstance(result, dict) else {}


def write_report(path: Path, report: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:2367")
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--interval", type=float, default=3)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.duration < 300 or args.interval < 1 or args.report.exists():
        parser.error("duration must be >=300s, interval >=1s, and report path must be new")

    base = args.base_url.rstrip("/")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    session = request(opener, base, "/api/session")
    cookie = next((c.value for c in jar if c.name == "companion_session"), "")
    csrf = session.get("csrf_token", "")
    if not cookie or not csrf:
        raise RuntimeError("companion session bootstrap failed")
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "Origin": base, "X-Companion-CSRF": csrf, "X-Companion-Session": cookie}

    report: dict[str, Any] = {
        "schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_requested_seconds": args.duration, "interval_seconds": args.interval,
        "raw_audio_persisted": False, "raw_video_persisted": False,
        "history_queries_use_automatic_enrichment": True,
        "capture_source": "existing companion status APIs", "samples": [], "events": [],
        "model_checks": [], "errors": [],
    }
    start = time.monotonic()
    wall_start = datetime.now(timezone.utc)
    report["started_at"] = wall_start.isoformat()
    seen: set[str] = set()
    queried: set[str] = set()
    last_progress = -1

    def ask(label: str, question: str) -> None:
        mark = {"label": label, "at": datetime.now(timezone.utc).isoformat()}
        try:
            t0 = time.monotonic()
            result = request(opener, base, "/api/chat", headers,
                             {"text": question, "session_id": "sensory-history-acceptance"})
            mark.update({"response_id": result.get("response_id"), "text": result.get("text", ""),
                         "elapsed_seconds": round(time.monotonic() - t0, 2), "error": result.get("error"),
                         "history_events_supplied": 0,
                         "history_enrichment_requested": any(word in question.lower() for word in ("\u0438\u0441\u0442\u043e\u0440", "\u043c\u0438\u043d\u0443\u0442", "\u0440\u0430\u043d\u044c\u0448\u0435", "\u0432\u0441\u0451 \u0432\u0440\u0435\u043c\u044f"))})
        except Exception as exc:  # noqa: BLE001
            mark["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        report["model_checks"].append(mark)
        write_report(args.report, report)

    ask("current_at_start", "\u041e\u043f\u0438\u0448\u0438 \u043a\u043e\u0440\u043e\u0442\u043a\u043e \u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u044d\u043a\u0440\u0430\u043d \u0438 \u0441\u0438\u0441\u0442\u0435\u043c\u043d\u044b\u0439 \u0437\u0432\u0443\u043a. \u0420\u0430\u0437\u0434\u0435\u043b\u0438 \u043d\u0430\u0431\u043b\u044e\u0434\u0430\u0435\u043c\u043e\u0435 \u0438 \u043f\u0440\u0435\u0434\u043f\u043e\u043b\u043e\u0436\u0435\u043d\u0438\u0435; \u043f\u0440\u0438 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0438\u0438 \u0434\u0430\u043d\u043d\u044b\u0445 \u0441\u043a\u0430\u0436\u0438 \u043f\u0440\u044f\u043c\u043e.")
    while time.monotonic() - start < args.duration:
        elapsed = time.monotonic() - start
        sample: dict[str, Any] = {"at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(elapsed, 1)}
        try:
            vision = request(opener, base, "/api/vision/status")
            sensor = vision.get("visual_sensor") if isinstance(vision.get("visual_sensor"), dict) else {}
            obs = sensor.get("last_observation") if isinstance(sensor.get("last_observation"), dict) else {}
            sample["visual"] = {k: sensor.get(k) for k in ("running", "captures", "submits", "delivered", "caption_age_ms", "scene_id", "source", "capture_errors")}
            if obs:
                event = {"at": obs.get("observed_at"), "elapsed_seconds": round(elapsed, 1), "modality": "visual", "text": obs.get("caption", ""),
                         "source": obs.get("source", ""), "scene_id": obs.get("scene_id"),
                         "age_ms": obs.get("age_ms"), "verified": False}
                key = json.dumps(event, sort_keys=True, ensure_ascii=False)
                if event["text"] and key not in seen:
                    seen.add(key); report["events"].append(event)
            audio = request(opener, base, "/api/ambient-audio", headers)
            bridge = audio.get("bridge") if isinstance(audio.get("bridge"), dict) else {}
            capture = audio.get("capture") if isinstance(audio.get("capture"), dict) else {}
            sample["audio"] = {"enabled": audio.get("enabled"), "running": capture.get("running"),
                               "device": capture.get("device"), "rms": capture.get("last_chunk_rms"),
                               "chunks": bridge.get("chunks"), "transcripts": bridge.get("transcripts"),
                               "soundscape_count": bridge.get("soundscape_count"),
                               "soundscape_kind": bridge.get("soundscape_last_kind"),
                               "soundscape_tags": bridge.get("soundscape_last_tags"),
                               "audio_description_count": bridge.get("audio_description_count"),
                               "last_error": bridge.get("last_error")}
            memory = request(opener, base, "/api/ambient-memory", headers)
            history_state = request(opener, base, "/api/sensory-history", headers)
            sample["sensory_history"] = history_state.get("state", history_state)
            for item in memory.get("observations", []):
                if not isinstance(item, dict):
                    continue
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                text = str(payload.get("text") or "").strip()
                stamp = str(payload.get("observed_at") or item.get("created_at") or "")
                try:
                    event_time = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    event_elapsed = (event_time - wall_start).total_seconds()
                except ValueError:
                    event_elapsed = -1
                if event_elapsed < 0 or event_elapsed > elapsed + 5:
                    continue
                ident = str(item.get("event_id") or item.get("session_id") or "") + stamp + text
                if text and ident not in seen:
                    seen.add(ident)
                    report["events"].append({"at": stamp, "elapsed_seconds": round(event_elapsed, 1), "modality": payload.get("audio_kind") or payload.get("stream") or "audio",
                                             "text": text[:500], "source": item.get("source", "ambient_memory"),
                                             "confidence": payload.get("confidence"), "verified": False,
                                             "tags": payload.get("tags", [])})
            report["samples"].append(sample)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"at": sample["at"], "elapsed_seconds": round(elapsed, 1),
                                     "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        if 115 <= elapsed < 125 and "two_minutes" not in queried:
            queried.add("two_minutes")
            ask("two_minutes_since_start", "\u0427\u0442\u043e \u043d\u0430\u0431\u043b\u044e\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u0438\u043c\u0435\u0440\u043d\u043e \u0434\u0432\u0435 \u043c\u0438\u043d\u0443\u0442\u044b \u043d\u0430\u0437\u0430\u0434? \u0412\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u0438 \u043f\u043e \u0432\u0441\u0442\u0440\u043e\u0435\u043d\u043d\u043e\u0439 \u0438\u0441\u0442\u043e\u0440\u0438\u0438 \u0441\u0435\u043d\u0441\u043e\u0440\u043d\u044b\u0445 \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0439 \u044d\u0442\u043e\u0439 \u0441\u0435\u0441\u0441\u0438\u0438, \u043e\u0442\u0434\u0435\u043b\u044f\u0439 \u043f\u043e\u0434\u043f\u0438\u0441\u0438 \u043c\u043e\u0434\u0435\u043b\u0438 \u043e\u0442 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u044b\u0445 \u0444\u0430\u043a\u0442\u043e\u0432 \u0438 \u043d\u0435 \u0443\u0433\u0430\u0434\u044b\u0432\u0430\u0439 \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0438.")
        if 475 <= elapsed < 485 and "two_minutes_before_end" not in queried:
            queried.add("two_minutes_before_end")
            ask("two_minutes_before_end", "\u0427\u0442\u043e \u043f\u0440\u043e\u0438\u0441\u0445\u043e\u0434\u0438\u043b\u043e \u043f\u0440\u0438\u043c\u0435\u0440\u043d\u043e \u0434\u0432\u0435 \u043c\u0438\u043d\u0443\u0442\u044b \u043d\u0430\u0437\u0430\u0434? \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 \u0432\u0441\u0442\u0440\u043e\u0435\u043d\u043d\u0443\u044e \u0438\u0441\u0442\u043e\u0440\u0438\u044e \u0441\u0435\u043d\u0441\u043e\u0440\u043d\u044b\u0445 \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0439, \u0443\u043a\u0430\u0436\u0438 \u0432\u0440\u0435\u043c\u044f \u0437\u0430\u043f\u0438\u0441\u0438 \u0438 \u043e\u0442\u0434\u0435\u043b\u0438 \u043c\u043e\u0434\u0435\u043b\u044c\u043d\u044b\u0435 \u0433\u0438\u043f\u043e\u0442\u0435\u0437\u044b \u043e\u0442 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u044b\u0445 \u0444\u0430\u043a\u0442\u043e\u0432.")
        now_elapsed = int(elapsed // 60)
        if now_elapsed != last_progress:
            last_progress = now_elapsed
            print(f"progress {now_elapsed}m; samples={len(report['samples'])}; events={len(report['events'])}; errors={len(report['errors'])}", flush=True)
        write_report(args.report, report)
        delay = args.interval - (time.monotonic() - start - elapsed)
        if delay > 0:
            time.sleep(min(delay, max(0.0, args.duration - (time.monotonic() - start))))

    compact: list[dict[str, Any]] = []
    last_sig = None
    for event in sorted(report["events"], key=lambda e: e.get("elapsed_seconds", 0)):
        sig = (event.get("modality"), event.get("text", ""))
        if sig == last_sig:
            continue
        compact.append(event)
        last_sig = sig
    if len(compact) > 48:
        stride = max(1, len(compact) // 48)
        compact = compact[::stride][:48]
    ask("all_session", "\u0420\u0430\u0441\u0441\u043a\u0430\u0436\u0438, \u0447\u0442\u043e \u043d\u0430\u0431\u043b\u044e\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430 \u0432\u0441\u0451 \u0432\u0440\u0435\u043c\u044f \u044d\u0442\u043e\u0439 \u0434\u0435\u0441\u044f\u0442\u0438\u043c\u0438\u043d\u0443\u0442\u043d\u043e\u0439 \u0441\u0435\u0441\u0441\u0438\u0438. \u0412\u044b\u0434\u0435\u043b\u0438 \u043f\u043e\u0441\u043b\u0435\u0434\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u043e\u0441\u043d\u043e\u0432\u043d\u044b\u0445 \u0432\u0438\u0437\u0443\u0430\u043b\u044c\u043d\u044b\u0445 \u0441\u0446\u0435\u043d \u0438 \u0437\u0432\u0443\u043a\u043e\u0432\u044b\u0435 \u0441\u043e\u0431\u044b\u0442\u0438\u044f, \u043e\u0442\u0434\u0435\u043b\u0438 \u043c\u043e\u0434\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u0434\u043f\u0438\u0441\u0438 \u043e\u0442 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u044b\u0445 \u0444\u0430\u043a\u0442\u043e\u0432 \u0438 \u0443\u043a\u0430\u0436\u0438 \u043d\u0435\u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0451\u043d\u043d\u043e\u0441\u0442\u044c.")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["elapsed_seconds"] = round(time.monotonic() - start, 1)
    report["sample_count"] = len(report["samples"])
    report["event_count"] = len(report["events"])
    report["error_count"] = len(report["errors"])
    write_report(args.report, report)
    print(json.dumps({k: report[k] for k in ("elapsed_seconds", "sample_count", "event_count", "error_count", "finished_at")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
