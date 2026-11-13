"""Isolate why real turns run at 6 tok/s while raw decode is 36 tok/s.

Raw probe: decode 35.8 tok/s, prefill 1111 tok/s, prompt cache hits.
Real turn: 258 tokens in 42 s. The difference must come from how the request is
made, not from the model. The prime suspect is grammar-constrained JSON output
(``tool_transport: json_envelope``), which forces per-token mask evaluation over
a large schema.

This probe measures the same prompt with and without a JSON grammar so the cost
is attributed to the grammar rather than guessed at.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"

# A small schema shaped like the JAWL action envelope: one required object with a
# few scalar fields. Real JAWL schemas are larger, so this is a lower bound.
ENVELOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "thoughts": {"type": "string"},
        "action": {"type": "string"},
        "parameters": {"type": "object"},
        "final": {"type": "string"},
    },
    "required": ["thoughts", "action"],
}


def post(payload: dict, timeout: float = 300.0) -> dict:
    request = urllib.request.Request(
        f"{BRAIN}/completion",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run(label: str, payload: dict) -> dict:
    began = time.perf_counter()
    try:
        data = post(payload)
    except Exception as exc:  # noqa: BLE001 - diagnostic probe
        print(f"{label:24} FAILED {type(exc).__name__}: {exc}")
        return {"label": label, "error": str(exc)[:200]}
    wall = time.perf_counter() - began
    timings = data.get("timings") or {}
    predicted_n = int(timings.get("predicted_n") or 0)
    predicted_ms = float(timings.get("predicted_ms") or 0.0)
    prompt_n = int(timings.get("prompt_n") or 0)
    prompt_ms = float(timings.get("prompt_ms") or 0.0)
    out = {
        "label": label,
        "prompt_tokens": prompt_n,
        "predicted_tokens": predicted_n,
        "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
        "decode_tok_s": round(predicted_n / (predicted_ms / 1000.0), 1) if predicted_ms else 0.0,
        "wall_s": round(wall, 2),
    }
    print(
        f"{label:24} prompt={prompt_n:6d} out={predicted_n:4d} "
        f"prefill={out['prefill_tok_s']:7.1f} decode={out['decode_tok_s']:6.1f} tok/s "
        f"wall={wall:6.1f}s"
    )
    return out


def main() -> int:
    instr = (
        "Ты голосовой компаньон. Ответь JSON-объектом с полями thoughts, action, "
        "parameters, final. Вопрос: какой сегодня статус проекта?"
    )
    results = []

    # 1. Free-form text, no grammar.
    results.append(run("free_text", {
        "prompt": instr,
        "n_predict": 200,
        "temperature": 0.0,
    }))

    # 2. JSON schema via response_format (server builds the grammar).
    results.append(run("json_schema", {
        "prompt": instr,
        "n_predict": 200,
        "temperature": 0.0,
        "response_format": {"type": "json_schema", "schema": ENVELOPE_SCHEMA},
    }))

    # 3. Explicit GBNF grammar: same shape, hand-written.
    gbnf = r'''
root ::= object
object ::= "{" ws "\"thoughts\"" ws ":" ws string ws "," ws "\"action\"" ws ":" ws string ws "," ws "\"final\"" ws ":" ws string ws "}"
string ::= "\"" [^"]* "\""
ws ::= [ \t\n]*
'''
    results.append(run("gbnf_grammar", {
        "prompt": instr,
        "n_predict": 200,
        "temperature": 0.0,
        "grammar": gbnf,
    }))

    baseline = next((r for r in results if r["label"] == "free_text" and "decode_tok_s" in r), None)
    print()
    if baseline:
        for item in results:
            if item.get("label") == "free_text" or "decode_tok_s" not in item:
                continue
            slowdown = baseline["decode_tok_s"] / max(item["decode_tok_s"], 0.001)
            print(f"{item['label']:24} decode {item['decode_tok_s']:6.1f} tok/s  = {slowdown:5.2f}x slower than free text")

    out = ROOT / "runtime" / "instances" / "brain_grammar_cost.json"
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())