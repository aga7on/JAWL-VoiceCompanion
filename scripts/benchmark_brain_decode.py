"""Measure decode throughput the way JAWL actually requests it.

Every previous probe measured decode on 4-200 token outputs. The real turn emits
258-303 tokens under a JSON-object response_format with a 2048-token cap. If
decode degrades as output grows (memory pressure, sampling overhead, growing KV),
the short probes would have missed it entirely.

This probe sweeps output length at a fixed prompt and reports decode tok/s for
each, so degradation is visible rather than averaged away.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"

PROMPT = (
    "Ты ведёшь внутренний журнал. Опиши подробно, что ты сейчас делаешь, "
    "подробно и по шагам, без ограничения длины."
)


def run(label: str, n_predict: int, response_format: dict | None = None) -> dict:
    payload = {
        "prompt": PROMPT,
        "n_predict": n_predict,
        "temperature": 0.0,
        "stream": False,
    }
    if response_format:
        payload["response_format"] = response_format
    request = urllib.request.Request(
        f"{BRAIN}/completion",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    began = time.perf_counter()
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.loads(response.read().decode("utf-8"))
    wall = time.perf_counter() - began
    t = data.get("timings") or {}
    predicted_n = int(t.get("predicted_n") or 0)
    predicted_ms = float(t.get("predicted_ms") or 0.0)
    prompt_n = int(t.get("prompt_n") or 0)
    prompt_ms = float(t.get("prompt_ms") or 0.0)
    out = {
        "label": label,
        "prompt_tokens": prompt_n,
        "predicted_tokens": predicted_n,
        "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
        "decode_tok_s": round(predicted_n / (predicted_ms / 1000.0), 1) if predicted_ms else 0.0,
        "wall_s": round(wall, 2),
    }
    print(
        f"{label:28} out={predicted_n:4d} tok  decode={out['decode_tok_s']:6.1f} tok/s "
        f"wall={wall:6.1f}s"
    )
    return out


def main() -> int:
    print("=" * 92)
    print("  Decode throughput vs output length (real-turn sizes included)")
    print("=" * 92)

    results = []
    for n in (64, 128, 258, 400, 800):
        results.append(run(f"plain n={n}", n))

    print()
    json_object = {"type": "json_object"}
    for n in (258, 400):
        results.append(run(f"json_object n={n}", n, json_object))

    print()
    print("decode degradation (relative to n=64):")
    baseline = next(r["decode_tok_s"] for r in results if r["label"] == "plain n=64")
    for item in results:
        ratio = item["decode_tok_s"] / max(baseline, 1e-9)
        flag = "  <-- degraded" if ratio < 0.85 else ""
        print(f"  {item['label']:22} {item['decode_tok_s']:6.1f} tok/s  = {ratio:4.2f}x{flag}")

    out = ROOT / "runtime" / "instances" / "brain_decode_scaling.json"
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())