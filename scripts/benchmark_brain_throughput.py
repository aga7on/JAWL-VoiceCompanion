"""Measure raw brain throughput: prefill and decode separately.

The turn trace showed 258 tokens in 42 s (about 6 tok/s) with prompt_reuse ~0.
That is far below what a 9B Q4 model should do on an RTX 5080, so this probe
separates the two numbers that matter:

  * prefill  — how fast the ~20k-token prompt is processed (TTFT);
  * decode   — how fast output tokens are produced (tok/s).

Both are read from llama-server's own timings, not inferred from wall clock.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"


def post(path: str, payload: dict, timeout: float = 300.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BRAIN}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get(path: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(f"{BRAIN}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run_case(label: str, prompt: str, n_predict: int) -> dict:
    began = time.perf_counter()
    data = post(
        "/completion",
        {
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": 0.0,
            "stream": False,
        },
    )
    wall = time.perf_counter() - began
    timings = data.get("timings") or {}
    prompt_n = int(timings.get("prompt_n") or 0)
    predicted_n = int(timings.get("predicted_n") or 0)
    prompt_ms = float(timings.get("prompt_ms") or 0.0)
    predicted_ms = float(timings.get("predicted_ms") or 0.0)
    result = {
        "label": label,
        "wall_s": round(wall, 2),
        "prompt_tokens": prompt_n,
        "predicted_tokens": predicted_n,
        "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
        "decode_tok_s": round(predicted_n / (predicted_ms / 1000.0), 1) if predicted_ms else 0.0,
        "ttft_ms": round(prompt_ms or 0.0, 0),
    }
    print(
        f"{label:22} prompt={prompt_n:6d} tok  prefill={result['prefill_tok_s']:7.1f} tok/s  "
        f"decode={result['decode_tok_s']:6.1f} tok/s  wall={wall:6.1f}s"
    )
    return result


def main() -> int:
    print("=" * 100)
    print("  Brain throughput probe")
    print("=" * 100)
    try:
        props = get("/props")
    except Exception as exc:  # noqa: BLE001 - diagnostics
        print(f"brain is not reachable at {BRAIN}: {exc}")
        return 2

    defaults = props.get("default_generation_settings") or {}
    print("model:", props.get("model_path") or props.get("model_alias"))
    print("n_ctx:", defaults.get("n_ctx"))
    print("n_slots:", props.get("total_slots"))
    print()

    results = []
    # Short prompt: isolates decode speed from prefill.
    results.append(run_case("decode_short", "Скажи одно слово: да.", 128))
    # Long prompt similar in size to the real JAWL turn (~20k tokens).
    filler = "Это служебный текст для измерения скорости обработки промпта. " * 850
    long_prompt = (
        "Ниже длинный служебный контекст. Не отвечай на него.\n"
        f"{filler}\n\nТеперь ответь одним словом: да."
    )
    results.append(run_case("prefill_long", long_prompt, 16))
    # Same long prompt twice: the second call shows whether the server caches it.
    results.append(run_case("prefill_repeat", long_prompt, 16))

    short = results[0]
    long_first = results[1]
    long_second = results[2]
    print()
    print("cache check: repeat prefill speed %.1f -> %.1f tok/s" % (
        long_first["prefill_tok_s"], long_second["prefill_tok_s"]
    ))
    if long_second["prompt_tokens"] < long_first["prompt_tokens"] * 0.9:
        print("  -> prompt cache HIT (fewer tokens processed on repeat)")
    else:
        print("  -> prompt cache MISS (full prompt reprocessed)")

    out = ROOT / "runtime" / "instances" / "brain_throughput.json"
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())