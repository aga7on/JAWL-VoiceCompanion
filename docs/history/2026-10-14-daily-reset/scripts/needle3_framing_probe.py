"""Needle3 framing probe: which input framing actually produces a typed decision?

Follow-up to needle3_system1_probe.py, which returned 0/20 with *no* function
calls at all when the canonical event state was passed as the raw request.
Needle is a request->call model, so the framing matters.

Framings tested per case:
  A raw     : the state JSON alone (as in the first probe)
  B instruct: short English instruction + the state fields
  C prose   : the event restated as a natural English sentence

Usage: python -X utf8 scripts/needle3_framing_probe.py [seed.jsonl] [tools.json] [weights.cact]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(r"G:\AI\JAWL-VoiceCompanion")
SEED = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "config" / "needle_system1_seed.jsonl")
TOOLS = Path(sys.argv[2] if len(sys.argv) > 2 else REPO / "config" / "needle_system1_tools.json")
WEIGHTS = Path(sys.argv[3] if len(sys.argv) > 3 else REPO / "runtime" / "models" / "needle3" / "needle3.cact")

IDS = ["ev-001", "ev-002", "ev-007", "ev-009", "ev-014"]


def prose(state: dict) -> str:
    bits = []
    for key, value in state.items():
        bits.append(f"{key.replace('_', ' ')} is {value}")
    return "Event observed by the companion: " + "; ".join(bits) + ". What should the companion do?"


def main() -> int:
    if not WEIGHTS.exists():
        print(f"Веса не найдены: {WEIGHTS}", file=sys.stderr)
        return 2
    import needle

    tools = json.loads(TOOLS.read_text(encoding="utf-8"))
    cases = {json.loads(line)["id"]: json.loads(line)
             for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()}
    print(f"weights={WEIGHTS.name} cases={len(IDS)}")

    for case_id in IDS:
        case = cases[case_id]
        state = case["state"]
        framings = {
            "A_raw": json.dumps(state, ensure_ascii=False),
            "B_instruct": (
                "Choose the attention_decision for this observed event. State: "
                + json.dumps(state, ensure_ascii=False)
            ),
            "C_prose": prose(state),
        }
        for name, text in framings.items():
            agent = needle.Needle(weights=str(WEIGHTS), tools=tools)
            try:
                result = agent.run(text)
                calls = result.get("function_calls") or []
                args = calls[0].get("arguments", {}) if calls else None
                conf = result.get("confidence")
                print(f"{case_id} {name}: calls={len(calls)} conf={conf} args={json.dumps(args, ensure_ascii=False)}")
            except Exception as exc:  # noqa: BLE001
                print(f"{case_id} {name}: ERROR {str(exc)[:100]}")
            finally:
                try:
                    agent.close()
                except Exception:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
