"""Needle3 RU tool-call smoke via Python API (UTF-8 native).

Usage: python -X utf8 scripts/run_needle3_ru_smoke.py [weights.cact] [tools.json]
Prints JSON result per query; exit 0 on success.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WEIGHTS = Path(sys.argv[1] if len(sys.argv) > 1 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\needle3\needle3.cact")
TOOLS = Path(sys.argv[2] if len(sys.argv) > 2 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\needle3\tools.json")

QUERIES = [
    "Set a timer for five minutes",          # EN control
    "Поставь таймер на пять минут",          # RU timer
    "Запомни: я люблю кофе",                 # RU remember
    "Отправь Пете сообщение: привет",        # RU send
    "Запусти браузер",                       # RU open_app
]


def main() -> int:
    if not WEIGHTS.exists():
        print(f"Веса не найдены: {WEIGHTS}", file=sys.stderr)
        return 2
    import needle

    tools = json.loads(TOOLS.read_text(encoding="utf-8")) if TOOLS.exists() else []
    print(f"weights={WEIGHTS.name} tools={len(tools)}")

    agent = needle.Needle(weights=str(WEIGHTS), tools=tools)
    for i, q in enumerate(QUERIES):
        try:
            if i > 0:
                try:
                    agent.reset()
                except Exception:
                    agent = needle.Needle(weights=str(WEIGHTS), tools=tools)
            result = agent.run(q)
            calls = result.get("function_calls") or result.get("results") or []
            print(f"IN: {q}")
            print(f"  calls: {json.dumps(calls, ensure_ascii=True)[:300]}")
        except Exception as exc:  # noqa: BLE001
            print(f"IN: {q}\n  ERROR: {exc}")
    try:
        agent.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())