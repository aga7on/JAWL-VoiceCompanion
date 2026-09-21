"""Needle3 System-1 probe on canonical typed state (ADR-043 candidate gate).

Tests the *post-cognition-boundary* role: Needle receives structured event
state (canonical keys/enums, no natural-language prose in Russian) and must
return a typed decision via one tool call.

Gate metrics (ADR-043): false wake, false memory promotion, missed important,
p95 latency, and confidence-vs-error. Accuracy alone is NOT the criterion.

Usage:
  python -X utf8 scripts/needle3_system1_probe.py [seed.jsonl] [tools.json] [weights.cact]

NOTE: labels in the seed file are the author's deterministic policy, not
owner-annotated production data. The 500-1000 case corpus from ADR-043 still
needs real labels; this probe proves the harness and gives a first signal.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(r"G:\AI\JAWL-VoiceCompanion")
SEED = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "config" / "needle_system1_seed.jsonl")
TOOLS = Path(sys.argv[2] if len(sys.argv) > 2 else REPO / "config" / "needle_system1_tools.json")
WEIGHTS = Path(sys.argv[3] if len(sys.argv) > 3 else REPO / "runtime" / "models" / "needle3" / "needle3.cact")

FIELDS = ("attention", "priority", "memory_candidate", "route")


def main() -> int:
    if not WEIGHTS.exists():
        print(f"Веса не найдены: {WEIGHTS}", file=sys.stderr)
        return 2
    import needle

    tools = json.loads(TOOLS.read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"weights={WEIGHTS.name} cases={len(cases)} fields={len(FIELDS)}")

    agent = needle.Needle(weights=str(WEIGHTS), tools=tools)
    latencies: list[float] = []
    conf_pass: list[float] = []
    conf_fail: list[float] = []
    passed = 0
    false_wake = false_memory = missed_important = 0
    field_hits = {f: 0 for f in FIELDS}

    for i, case in enumerate(cases):
        if i > 0:
            try:
                agent.reset()
            except Exception:
                agent = needle.Needle(weights=str(WEIGHTS), tools=tools)
        state = json.dumps(case["state"], ensure_ascii=False)
        expect = case["expect"]
        t0 = time.perf_counter()
        try:
            result = agent.run(state)
            dt = (time.perf_counter() - t0) * 1000
            calls = result.get("function_calls") or []
            args = calls[0].get("arguments", {}) if calls else {}
            conf = float(result.get("confidence") or 0.0)
        except Exception as exc:  # noqa: BLE001
            print(f"{case['id']}: ERROR {str(exc)[:120]}")
            continue
        latencies.append(dt)

        got = {f: args.get(f) for f in FIELDS}
        ok_fields = [f for f in FIELDS if got[f] == expect[f]]
        for f in ok_fields:
            field_hits[f] += 1
        case_ok = len(ok_fields) == len(FIELDS)
        passed += case_ok
        (conf_pass if case_ok else conf_fail).append(conf)

        if expect["attention"] != "wake" and got.get("attention") == "wake":
            false_wake += 1
        if not expect["memory_candidate"] and got.get("memory_candidate") is True:
            false_memory += 1
        if expect["attention"] == "wake" and got.get("attention") != "wake":
            missed_important += 1

        mark = "PASS" if case_ok else "FAIL"
        print(f"{case['id']}: {mark} {dt:6.0f}ms conf={conf:.2f} got={json.dumps(got, ensure_ascii=False)}")
        if not case_ok:
            print(f"        expect={json.dumps(expect, ensure_ascii=False)}")

    n = len(latencies) or 1
    p95 = sorted(latencies)[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))] if latencies else 0
    print("---")
    print(f"full-case pass {passed}/{len(cases)}")
    print("field accuracy: " + " ".join(f"{f}={field_hits[f]}/{len(cases)}" for f in FIELDS))
    print(f"false_wake={false_wake} false_memory_promotion={false_memory} missed_important={missed_important}")
    print(f"latency p50={statistics.median(latencies):.0f}ms p95={p95:.0f}ms max={max(latencies) if latencies else 0:.0f}ms")
    if conf_pass:
        print(f"confidence pass mean={statistics.mean(conf_pass):.3f}")
    if conf_fail:
        print(f"confidence fail mean={statistics.mean(conf_fail):.3f}")
    try:
        agent.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
