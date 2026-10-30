"""Needle3 RU tool-call verdict: fresh agent per query (no state bleed).

Usage: python -X utf8 scripts/needle3_ru_verdict.py [weights.cact] [tools.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WEIGHTS = Path(sys.argv[1] if len(sys.argv) > 1 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\needle3\needle3.cact")
TOOLS = Path(sys.argv[2] if len(sys.argv) > 2 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\needle3\tools.json")

QUERIES = [
    ("EN control", "Set a timer for five minutes", "timer_set"),
    ("RU timer", "Поставь таймер на пять минут", "timer_set"),
    ("RU remember", "Запомни, что я люблю кофе", "remember_fact"),
    ("RU send", "Отправь Пете сообщение: привет", "send_message"),
    ("RU open_app", "Запусти браузер", "open_app"),
]


def main() -> int:
    if not WEIGHTS.exists():
        print(f"Веса не найдены: {WEIGHTS}", file=sys.stderr)
        return 2
    import needle

    tools = json.loads(TOOLS.read_text(encoding="utf-8")) if TOOLS.exists() else []
    print(f"weights={WEIGHTS.name} tools={len(tools)}")
    for label, q, expected in QUERIES:
        agent = needle.Needle(weights=str(WEIGHTS), tools=tools)
        try:
            result = agent.run(q)
            calls = result.get("function_calls") or result.get("results") or []
            names = [c.get("name") for c in calls if isinstance(c, dict) and c.get("name")]
            ok = names == [expected]
            print(f"{label}: {'PASS' if ok else 'FAIL'} expected={expected} got={names}")
            if not ok:
                print(f"   raw: {json.dumps(calls, ensure_ascii=False)[:400]}")
        except Exception as exc:  # noqa: BLE001
            print(f"{label}: ERROR {exc}")
        finally:
            try:
                agent.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())