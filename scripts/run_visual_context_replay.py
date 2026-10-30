"""Capture exact fused visual context and brain-bound text for a QA replay.

The script talks only to a local companion API and records captions/prompts
from a supplied QA stimulus. It never captures pixels, microphone input, or
PCM. Use only with a disposable profile and non-private test content.
"""

from __future__ import annotations

import argparse
import json
import time
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:2369")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target-title", default="QA-Video")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    cookies = CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))
    csrf = ""

    def request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal csrf
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Origin": base, "Accept": "application/json"}
        if csrf:
            headers["X-Companion-CSRF"] = csrf
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(base + path, data=body, headers=headers)
        with client.open(req, timeout=150) as response:
            result = json.loads(response.read().decode("utf-8"))
        if path == "/api/session":
            csrf = str(result.get("csrf_token") or "")
        return result

    try:
        request("/api/session")
        turns = [
            {
                "wait_for": "yellow jacket",
                "session_id": "visual-context-retained",
                "question": "Describe the current gameplay scene. Mention visible characters and setting; use only the current image.",
            },
            {
                "wait_for": "Earth",
                "session_id": "visual-context-retained",
                "question": "Describe the current gameplay scene. Mention visible characters and setting; use only the current image, and say if it does not show gameplay.",
            },
            {
                "wait_for": "Earth",
                "session_id": "visual-context-second-id-only",
                "question": "Describe the current gameplay scene. Mention visible characters and setting; use only the current image, and say if it does not show gameplay.",
            },
        ]
        result: dict[str, Any] = {
            "schema_version": 1,
            "base_url": base,
            "started_at": time.time(),
            "stimulus": "local QA-Video target window; no pixels/PCM persisted by this script",
            "brain_context_isolation": (
                "not performed: the outer Companion session_id is not forwarded as a "
                "JAWL conversation reset; native turns carry correlation turn_id only, "
                "and one JAWL instance shares its HostTerminal history/context"
            ),
            "turns": [],
            "errors": [],
        }

        def save() -> None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.output.with_suffix(args.output.suffix + ".tmp")
            tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(args.output)

        previous_frame = ""
        for spec in turns:
            deadline = time.monotonic() + max(1.0, args.timeout)
            captured = None
            while time.monotonic() < deadline:
                status = request("/api/vision/status")
                visual = status.get("visual_sensor") or {}
                observation = visual.get("last_observation") or {}
                source = str(observation.get("source") or "")
                frame_id = str(observation.get("frame_id") or "")
                caption = str(observation.get("caption") or "")
                if (
                    visual.get("running")
                    and visual.get("target_title") == args.target_title
                    and source.startswith("screen:target_visible_region")
                    and visual.get("caption_fresh")
                    and frame_id
                    and frame_id != previous_frame
                    and str(spec["wait_for"]).casefold() in caption.casefold()
                ):
                    captured = {"visual": visual, "observation": observation}
                    break
                time.sleep(max(0.1, args.poll_interval))

            if captured is None:
                item = {"question": spec["question"], "status": "stimulus_timeout", "wait_for": spec["wait_for"]}
                result["turns"].append(item)
                result["errors"].append(f"timed out waiting for fresh target caption containing {spec['wait_for']!r}")
                save()
                continue

            draft = request("/api/perception/now").get("draft", "")
            before = captured["observation"]
            reply_started = time.monotonic()
            reply = request(
                "/api/chat",
                {"text": spec["question"], "session_id": spec["session_id"]},
            )
            reply_seconds = round(time.monotonic() - reply_started, 3)
            history = request("/api/history").get("turns", [])
            brain_turn = next(
                (
                    turn
                    for turn in reversed(history)
                    if turn.get("session_id") == spec["session_id"]
                    and turn.get("user", "").startswith(spec["question"])
                ),
                None,
            )
            item = {
                "status": "captured" if brain_turn else "history_record_missing",
                "session_id": spec["session_id"],
                "question": spec["question"],
                "pre_turn": {
                    "scene_id": before.get("scene_id"),
                    "frame_id": before.get("frame_id"),
                    "source": before.get("source"),
                    "age_ms": before.get("age_ms"),
                    "caption": before.get("caption"),
                },
                "fused_context_before_turn": draft,
                "brain_bound_text": brain_turn.get("user") if brain_turn else None,
                "brain_reply": (
                    (brain_turn.get("response") or {}).get("text") if brain_turn else None
                ) or reply.get("text"),
                "reply_seconds": reply_seconds,
                "correlation_id": brain_turn.get("correlation_id") if brain_turn else None,
            }
            result["turns"].append(item)
            previous_frame = str(before.get("frame_id") or "")
            save()

        result["ended_at"] = time.time()
        save()
        print(json.dumps({"output": str(args.output), "turns": result["turns"], "errors": result["errors"]}, ensure_ascii=False))
        return 0 if not result["errors"] and all(t["status"] == "captured" for t in result["turns"]) else 2
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        print(f"visual context replay failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
