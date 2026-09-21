"""Needle3 extract-mode probe (documented classification path, Needle3 alone).

llms.txt says: "Text goes in, a JSON tool call comes back" and
`needle.extract(text, schema, ...)` is the one-shot extraction entry point that
"generalises to classification". Earlier probes used agent.run(), which is the
agentic loop that executes Python functions - the wrong entry point for a pure
decision task.

This probe calls needle.extract() with the canonical JSON schema and reports the
ADR-043 gate metrics (false wake / false memory promotion / missed important).

Usage: python -X utf8 scripts/needle3_extract_probe.py [seed.jsonl] [tools.json] [weights.cact]
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

    tool = json.loads(TOOLS.read_text(encoding="utf-8"))[0]
    schema = dict(tool["parameters"])
    schema["title"] = tool["name"]
    cases = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"weights={WEIGHTS.name} cases={len(cases)} mode=extract")

    latencies: list[float] = []
    passed = 0
    none_results = 0
    false_wake = false_memory = missed_important = 0
    field_hits = {f: 0 for f in FIELDS}

    for case in cases:
        text = json.dumps(case["state"], ensure_ascii=False)
        expect = case["expect"]
        t0 = time.perf_counter()
        try:
            got = needle.extract(text, schema, weights=str(WEIGHTS))
        except Exception as exc:  # noqa: BLE001
            print(f"{case['id']}: ERROR {str(exc)[:110]}")
            continue
        latencies.append((time.perf_counter() - t0) * 1000)
        if got is None:
            none_results += 1
            print(f"{case['id']}: NONE")
            continue
        if not isinstance(got, dict):
            got = dict(got)
        hits = [f for f in FIELDS if got.get(f) == expect[f]]
        for f in hits:
            field_hits[f] += 1
        ok = len(hits) == len(FIELDS)
        passed += ok
        if expect["attention"] != "wake" and got.get("attention") == "wake":
            false_wake += 1
        if not expect["memory_candidate"] and got.get("memory_candidate") is True:
            false_memory += 1
        if expect["attention"] == "wake" and got.get("attention") != "wake":
            missed_important += 1
        print(f"{case['id']}: {'PASS' if ok else 'FAIL'} "
              f"{json.dumps({f: got.get(f) for f in FIELDS}, ensure_ascii=False)}")

    print("---")
    print(f"full-case pass {passed}/{len(cases)}  none={none_results}")
    print("field accuracy: " + " ".join(f"{f}={field_hits[f]}/{len(cases)}" for f in FIELDS))
    print(f"false_wake={false_wake} false_memory_promotion={false_memory} missed_important={missed_important}")
    if latencies:
        print(f"latency p50={statistics.median(latencies):.0f}ms max={max(latencies):.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
