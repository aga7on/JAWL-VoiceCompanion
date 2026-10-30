"""Run a short real-display Qwen + Windows OCR + VA packet smoke.

The script requires an explicit --live acknowledgement. It captures one
selected display in memory, sends only its redacted image to a loopback Qwen
endpoint, and prints a bounded result. Frames and OCR text are never written.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.perception_packet import make_packet, render_packet  # noqa: E402
from jawl_voicecompanion.qwen_event_describer import QwenEventDescriber  # noqa: E402
from jawl_voicecompanion.qwen_visual_sensor import QwenVisualSensor  # noqa: E402
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402
from jawl_voicecompanion.windows_ocr import WindowsOcr  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="acknowledge a transient capture of the selected display")
    parser.add_argument("--url", default="http://127.0.0.1:8994/v1")
    parser.add_argument("--model", default="qwen3.5-0.8b")
    parser.add_argument("--display-index", type=int, default=0)
    parser.add_argument("--wait-seconds", type=float, default=35.0)
    parser.add_argument("--show-caption", action="store_true", help="print the model's one-sentence visual caption")
    args = parser.parse_args()
    if not args.live:
        parser.error("real-display capture requires --live")
    if args.display_index not in range(4):
        parser.error("--display-index must be 0..3")
    if not 5.0 <= args.wait_seconds <= 90.0:
        parser.error("--wait-seconds must be 5..90")
    parsed_url = urlsplit(args.url)
    try:
        valid_port = parsed_url.port is not None and 1 <= parsed_url.port <= 65535
    except ValueError:
        valid_port = False
    if (
        parsed_url.scheme != "http"
        or parsed_url.hostname != "127.0.0.1"
        or not valid_port
        or parsed_url.path != "/v1"
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.username
        or parsed_url.password
    ):
        parser.error("--url must be a loopback HTTP /v1 endpoint")

    fusion = PerceptionFusion()
    capture = ScreenCaptureAdapter(
        enabled=True,
        ocr_enabled=True,
        ocr_provider=WindowsOcr(timeout_s=20.0),
    )
    describer = QwenEventDescriber(
        args.url,
        model=args.model,
        max_age_s=8.0,
        timeout=min(60.0, args.wait_seconds + 10.0),
    )
    sensor = QwenVisualSensor(
        screen_capture=capture,
        describer=describer,
        fusion=fusion,
        display_index=args.display_index,
        active_interval_s=1.0,
        static_interval_s=5.0,
        periodic_s=1.0,
        poll_interval_s=0.2,
    )

    deadline = time.monotonic() + args.wait_seconds
    try:
        sensor.start()
        while time.monotonic() < deadline:
            state = sensor.state()
            if state["delivered"] > 0 or state["capture_errors"] > 0:
                break
            time.sleep(0.2)
        state = sensor.state()
        snapshot = fusion.compose_snapshot()
        packet = make_packet(snapshot)
        screen = snapshot["channels"].get("screen", {})
        ocr = snapshot["channels"].get("ocr", {})
        caption = str((state.get("last_observation") or {}).get("caption") or "")
        result = {
            "status": "passed" if state["delivered"] > 0 and "screen" in packet["channels"] else "failed",
            "display_index": args.display_index,
            "captures": state["captures"],
            "submits": state["submits"],
            "delivered": state["delivered"],
            "capture_errors": state["capture_errors"],
            "screen_confirmation_age_ms": screen.get("age_ms"),
            "caption_age_ms": screen.get("caption_age_ms"),
            "ocr_present": bool(ocr.get("text")),
            "packet_channels": sorted(packet["channels"]),
            "screen_is_hypothesis": packet.get("channels", {}).get("screen", {}).get("hypothesis"),
            "packet_rendered_chars": len(render_packet(packet)),
            "raw_frames_persisted": False,
            "ocr_text_persisted": False,
        }
        if args.show_caption:
            result["caption"] = caption[:500]
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "passed" else 1
    finally:
        sensor.stop(timeout=5.0)


if __name__ == "__main__":
    raise SystemExit(main())
