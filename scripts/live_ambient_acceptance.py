"""Bounded live check for the ambient system-audio path (D4-01/D4-03)."""
from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:2367"
OUT = Path(__file__).resolve().parents[1] / "runtime" / "live-ambient-acceptance-20261020.json"


def session():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(urllib.request.Request(BASE + "/api/session"), timeout=5) as r:
        csrf = json.loads(r.read())["csrf_token"]
    token = [c.value for c in jar if c.name == "companion_session"][0]
    return opener, {
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": token,
        "Origin": BASE,
    }


def get(opener, headers, path):
    with opener.open(urllib.request.Request(BASE + path, headers=dict(headers)), timeout=10) as r:
        return json.loads(r.read())


def post(opener, headers, path, payload=None):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, headers=dict(headers))
    with opener.open(req, timeout=20) as r:
        return json.loads(r.read())


def main() -> int:
    opener, headers = session()
    steps = []
    steps.append({"step": "ambient-audio-initial", "result": get(opener, headers, "/api/ambient-audio")})
    steps.append({"step": "memory-initial", "result": get(opener, headers, "/api/ambient-memory")})
    steps.append({"step": "start", "result": post(opener, headers, "/api/ambient-audio/start")})
    time.sleep(3)
    steps.append({"step": "running", "result": get(opener, headers, "/api/ambient-audio")})
    steps.append({"step": "pause", "result": post(opener, headers, "/api/ambient-audio/pause")})
    steps.append({"step": "paused-state", "result": get(opener, headers, "/api/ambient-audio")})
    steps.append({"step": "resume", "result": post(opener, headers, "/api/ambient-audio/resume")})
    time.sleep(2)
    steps.append({"step": "resumed-state", "result": get(opener, headers, "/api/ambient-audio")})
    steps.append({"step": "stop", "result": post(opener, headers, "/api/ambient-audio/stop")})
    steps.append({"step": "stopped-state", "result": get(opener, headers, "/api/ambient-audio")})
    report = {"schema_version": 1, "steps": steps}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in steps:
        result = item["result"]
        state = result.get("state", result) if isinstance(result, dict) else result
        summary = {}
        if isinstance(state, dict):
            for key in ("backend", "device", "sample_rate", "channels", "running", "paused", "dropped_chunks", "accepted_chunks", "chunks", "enabled"):
                if key in state:
                    summary[key] = state[key]
        print(item["step"], json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
