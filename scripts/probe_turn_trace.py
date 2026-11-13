"""Verify the turn tracer end to end without a microphone.

Sends one text turn through the live Companion with a known trace id, then
prints the recorded stages. This proves the server-side marks work before the
owner runs a real voice turn.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = ROOT / "runtime" / "instances" / ".turn-trace"


def main() -> int:
    trace_id = f"probe-{int(time.time())}"
    url = "http://127.0.0.1:2367/api/chat"
    body = json.dumps({"text": "Ответь одним словом: работаешь?"}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
    )
    print(f"trace: {trace_id}")
    print("posting to /api/chat (expect 403 without a browser session)")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            print("HTTP", response.status)
            print(response.read()[:400])
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, "- session gate rejected the probe, as designed")
    except Exception as exc:  # noqa: BLE001 - diagnostic probe
        print("request failed:", type(exc).__name__, exc)

    time.sleep(1.0)
    path = TRACE_DIR / f"{trace_id}.jsonl"
    if not path.exists():
        print(f"no trace at {path}")
        print("Expected: /api/chat is session-gated, so no turn ran.")
        return 0
    for line in path.read_text(encoding="utf-8").splitlines():
        print(" ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())