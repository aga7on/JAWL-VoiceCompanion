"""15-minute screen-only live stability probe for a CPU VLM."""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.gemma_sensory import GemmaSensoryStream, OBSERVATION_SCHEMA  # noqa: E402
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402

SYSTEM = (
    "You are a concise vision describer for a desktop companion. Describe only "
    "visible evidence. Return only valid JSON matching the schema. Do not describe "
    "audio; set audio fields to empty strings, empty lists, or 'unknown'."
)
USER = (
    "Describe the visible scene specifically: content type, main objects, and any "
    "readable text. Do not guess unseen details. Return JSON only."
)


class Client:
    def __init__(self, url: str, model: str, max_tokens: int = 160) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens

    def describe(self, *, image_bytes=None, audio_wav_bytes=None, **_: object) -> dict:
        started = time.perf_counter()
        if not image_bytes:
            return {
                "status": "request_error",
                "error": "no image",
                "ttft_ms": None,
                "total_ms": 0.0,
            }
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                    ],
                },
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            "top_p": 0.9,
            "stream": True,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "jawl_sensory_observation", "schema": OBSERVATION_SCHEMA},
            },
        }
        text = ""
        ttft = None
        try:
            response = requests.post(
                self.url + "/chat/completions",
                json=payload,
                stream=True,
                timeout=120,
            )
            if response.status_code >= 400:
                return {
                    "status": "http_error",
                    "error": response.text[:400],
                    "ttft_ms": None,
                    "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
                }
            for raw in response.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (event.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = round((time.perf_counter() - started) * 1000.0, 1)
                    text += piece
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "request_error",
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "ttft_ms": None,
                "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
        total = round((time.perf_counter() - started) * 1000.0, 1)
        try:
            import re

            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
            start, end = clean.find("{"), clean.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("no JSON object")
            return {
                "status": "ok",
                "payload": json.loads(clean[start : end + 1]),
                "text": text[:2000],
                "ttft_ms": ttft,
                "total_ms": total,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "invalid_json",
                "error": f"{type(exc).__name__}: {exc}",
                "text": text[:2000],
                "ttft_ms": ttft,
                "total_ms": total,
            }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8993")
    parser.add_argument("--model", default="lfm2.5-vl-450m")
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--target-title", default="")
    parser.add_argument("--out", default=str(ROOT / "runtime/vlm-cpu-bench/live/lfm450-live.jsonl"))
    args = parser.parse_args()
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    capture = ScreenCaptureAdapter(enabled=True, max_width=960, max_height=720)
    stream = GemmaSensoryStream(
        client=Client(args.url, args.model, args.max_tokens),
        screen_capture=capture,
        audio_loopback=None,
        target_title=args.target_title,
        frame_interval_s=1.0,
        max_age_s=8.0,
        change_threshold=0.0,
        output_path=str(output),
        quant="q4",
    )
    stream.start()
    started = time.time()
    samples = []
    try:
        while time.time() - started < max(5, args.duration):
            time.sleep(10)
            state = stream.state()
            samples.append({"at_s": round(time.time() - started, 1), **state})
            print(json.dumps(samples[-1], ensure_ascii=False), flush=True)
    finally:
        stream.stop()
    summary = {
        "status": "ok",
        "model": args.model,
        "duration_s": round(time.time() - started, 1),
        "output": str(output),
        "final": stream.state(),
        "samples": samples,
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
