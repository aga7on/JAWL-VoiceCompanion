"""Attribute the remaining 15-23 s gap in real turns.

Known: raw decode 35.8 tok/s, prefill 1111 tok/s at 12k tokens, prompt cache hits.
Real turn: 22563-token prompt, 195 output tokens, 41.3 s measured, but the same
numbers predict 25.7 s. Two candidate causes remain:

  1. prefill slows down at longer context (attention is quadratic);
  2. JAWL calls the model with stream=true, paying per-token HTTP overhead the
     non-streaming probe never sees.

This probe measures both, plus a decode-only baseline at high context so the
numbers are directly comparable to the real turn.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"


def filler_tokens(approx: int) -> str:
    """Build a prompt of roughly ``approx`` tokens of Russian prose."""
    sentence = "Это служебный контекст для измерения скорости обработки. "
    # Russian runs ~2.5 chars/token with this tokenizer; aim slightly high.
    repeats = max(1, int(approx * 1.9 / len(sentence)))
    return sentence * repeats


def completion(payload: dict, stream: bool, timeout: float = 600.0) -> dict:
    payload = dict(payload)
    payload["stream"] = stream
    request = urllib.request.Request(
        f"{BRAIN}/completion",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    began = time.perf_counter()
    first_token_at = None
    chunks = 0
    timings = {}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if not stream:
            data = json.loads(response.read().decode("utf-8"))
            timings = data.get("timings") or {}
        else:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    event = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if first_token_at is None and event.get("content"):
                    first_token_at = time.perf_counter()
                    chunks += 1
                elif event.get("content"):
                    chunks += 1
                if event.get("timings"):
                    timings = event["timings"]
    wall = time.perf_counter() - began
    prompt_n = int(timings.get("prompt_n") or 0)
    prompt_ms = float(timings.get("prompt_ms") or 0.0)
    predicted_n = int(timings.get("predicted_n") or 0)
    predicted_ms = float(timings.get("predicted_ms") or 0.0)
    return {
        "stream": stream,
        "wall_s": round(wall, 2),
        "ttft_s": round(first_token_at - began, 2) if first_token_at else None,
        "chunks": chunks,
        "prompt_tokens": prompt_n,
        "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
        "predicted_tokens": predicted_n,
        "decode_tok_s": round(predicted_n / (predicted_ms / 1000.0), 1) if predicted_ms else 0.0,
    }


def report(label: str, result: dict) -> None:
    print(
        f"{label:28} prompt={result['prompt_tokens']:6d} out={result['predicted_tokens']:4d} "
        f"prefill={result['prefill_tok_s']:7.1f} decode={result['decode_tok_s']:6.1f} tok/s "
        f"ttft={str(result['ttft_s']):>6}s wall={result['wall_s']:6.1f}s"
    )


def main() -> int:
    print("=" * 118)
    print("  Prefill scaling and streaming cost")
    print("=" * 118)

    results = []
    # Prefill at increasing context: does throughput collapse at 22k?
    for target in (6_000, 12_000, 22_000, 30_000):
        prompt = filler_tokens(target) + "\nОтветь одним словом: да."
        result = completion({"prompt": prompt, "n_predict": 8, "temperature": 0.0}, stream=False)
        result["case"] = f"prefill_{target}"
        results.append(result)
        report(f"prefill ~{target}", result)

    print()
    # Same payload, non-streaming vs streaming, at real-turn context size.
    big_prompt = filler_tokens(22_000) + "\nОтветь одним словом: да."
    for stream in (False, True):
        result = completion({"prompt": big_prompt, "n_predict": 200, "temperature": 0.0}, stream=stream)
        result["case"] = f"n200_stream_{stream}"
        results.append(result)
        report(f"n=200 stream={stream}", result)

    out = ROOT / "runtime" / "instances" / "brain_prefill_scaling.json"
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("prefill scaling (tok/s by prompt size):")
    for item in results:
        if item["case"].startswith("prefill_"):
            print(f"  {item['prompt_tokens']:6d} tok -> {item['prefill_tok_s']:8.1f} tok/s")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())