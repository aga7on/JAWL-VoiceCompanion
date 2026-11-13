"""Regenerate the canonical Russian question WAV fixtures through OmniVoice.

The daily voice acceptance harnesses (``run_connected_daily_acceptance``,
``run_owned_gateway_acceptance``, ``run_synthetic_questions_live``) read
``runtime/synthetic-questions/question-01..03.wav`` and score GigaAM transcripts
against fixed expected words. Those fixtures are build artifacts, not source:
this script recreates them from the canonical TTS worker so a fresh checkout or
a cleaned runtime does not silently lose voice acceptance.

Usage (worker must already be serving):
    python -X utf8 scripts/make_synthetic_question_fixtures.py --url http://127.0.0.1:9895
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime" / "synthetic-questions"

# (text, expected transcript words used by the acceptance harnesses)
QUESTIONS = (
    ("Какой сегодня статус моего проекта?", ("статус",)),
    ("Запомни, пожалуйста, что я предпочитаю короткие ответы.", ("короткие",)),
    ("Сможешь проверить тестовый файл и сообщить результат?", ("тестовый",)),
)


def synthesize(url: str, text: str, timeout_s: float) -> bytes:
    payload = json.dumps({"text": text, "speed": 1.0}).encode("utf-8")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/tts",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9890")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, (text, expected) in enumerate(QUESTIONS, start=1):
        target = OUT_DIR / f"question-{index:02d}.wav"
        try:
            wav = synthesize(args.url, text, args.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"FAILED question-{index:02d}: {exc}", file=sys.stderr)
            return 1
        if len(wav) < 1024 or not wav.startswith(b"RIFF"):
            print(f"FAILED question-{index:02d}: worker returned no usable WAV", file=sys.stderr)
            return 1
        target.write_bytes(wav)
        print(f"wrote {target.name} ({len(wav)} bytes)")
        manifest.append({"file": target.name, "text": text, "expected_words": list(expected)})

    (OUT_DIR / "fixtures.json").write_text(
        json.dumps({"source": args.url, "fixtures": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(manifest)} fixtures into {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())