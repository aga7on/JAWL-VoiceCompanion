"""Test the prompt-cache hypothesis at real-turn context size.

Direct probe showed the server caches a repeated prompt (4 tokens on repeat).
But JAWL's own log reports prompt_reuse ~0 on every step. The difference: in a
ReAct loop the prompt changes between steps, so llama.cpp cannot match the prefix
and reprocesses everything.

This probe measures exactly that: prefill cost at ~22k tokens, and whether
changing a leading part of the prompt (as RAG/tool results do) forces a full
reprocess.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"


def make_filler(chars: int) -> str:
    sentence = "Служебный контекст для измерения скорости обработки промпта моделью. "
    repeats = max(1, chars // len(sentence))
    return sentence * repeats


def completion(prompt: str, n_predict: int = 8) -> dict:
    payload = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.0,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{BRAIN}/completion",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    began = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        data = json.loads(response.read().decode("utf-8"))
    wall = time.perf_counter() - began
    timings = data.get("timings") or {}
    prompt_n = int(timings.get("prompt_n") or 0)
    prompt_ms = float(timings.get("prompt_ms") or 0.0)
    return {
        "wall_s": round(wall, 2),
        "prompt_tokens": prompt_n,
        "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
        "prefill_s": round(prompt_ms / 1000.0, 2),
    }


def show(label: str, r: dict) -> None:
    print(
        f"{label:34} tokens={r['prompt_tokens']:6d} "
        f"prefill={r['prefill_tok_s']:8.1f} tok/s  {r['prefill_s']:6.2f}s"
    )


def main() -> int:
    print("=" * 100)
    print("  Prompt cache behaviour at real-turn size")
    print("=" * 100)

    # Calibrate filler size to reach ~22k tokens.
    base = make_filler(20_000)
    calib = completion(base, 4)
    tokens_per_char = calib["prompt_tokens"] / max(len(base), 1)
    target_chars = int(22_000 / max(tokens_per_char, 1e-6))
    print(f"calibration: {len(base)} chars -> {calib['prompt_tokens']} tokens "
          f"({tokens_per_char:.3f} tok/char)")
    print()

    filler = make_filler(target_chars)
    head_marker = "НАЧАЛО КОНТЕКСТА. "
    tail = "\nОтветь одним словом: да."

    results = []
    # 1. Cold prefill at ~22k.
    prompt_cold = head_marker + filler + tail
    r1 = completion(prompt_cold, 4)
    r1["case"] = "cold"
    results.append(r1)
    show("cold ~22k", r1)

    # 2. Identical prompt again: prefix cache should make this nearly free.
    r2 = completion(prompt_cold, 4)
    r2["case"] = "identical_repeat"
    results.append(r2)
    show("identical repeat", r2)

    # 3. Same prompt but the FIRST line changed — this is what RAG/tool output
    #    does between ReAct steps: new material lands before the final question.
    prompt_changed_head = "ДРУГОЕ НАЧАЛО КОНТЕКСТА. " + filler + tail
    r3 = completion(prompt_changed_head, 4)
    r3["case"] = "changed_head"
    results.append(r3)
    show("changed first line", r3)

    # 4. Same prompt with an appended block (a tool result at the end).
    prompt_appended = prompt_cold + "\nДОПОЛНЕНИЕ: прочитан файл snake.html на 2807 символов."
    r4 = completion(prompt_appended, 4)
    r4["case"] = "appended_tail"
    results.append(r4)
    show("appended at end", r4)

    out = ROOT / "runtime" / "instances" / "brain_cache_behaviour.json"
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("interpretation:")
    print(f"  identical repeat: {r2['prompt_tokens']} tokens processed "
          f"({'CACHE HIT' if r2['prompt_tokens'] < r1['prompt_tokens'] * 0.9 else 'CACHE MISS'})")
    print(f"  changed head:     {r3['prompt_tokens']} tokens processed "
          f"({'full reprocess' if r3['prompt_tokens'] > r1['prompt_tokens'] * 0.9 else 'partial reuse'})")
    print(f"  appended tail:    {r4['prompt_tokens']} tokens processed "
          f"({'partial reuse' if r4['prompt_tokens'] < r1['prompt_tokens'] * 0.5 else 'full reprocess'})")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())