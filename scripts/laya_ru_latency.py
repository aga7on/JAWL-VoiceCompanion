"""Laya RU latency + accuracy probe (System-1 gate for Companion routing).

Usage: python -X utf8 scripts/laya_ru_latency.py [model_dir]
Prints per-case latency (cold/warm p50) and correctness; exit 0.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

MODEL_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\laya-multilingual")

CASES = [
    ("Снова завис браузер, не могу работать с отчётом", "technical"),
    ("Верните деньги за двойное списание подписки", "billing"),
    ("Сколько стоит годовая подписка для команды?", "sales"),
    ("Приложение падает при запуске, ошибка 0x80070005", "technical"),
    ("Не пришёл чек об оплате за прошлый месяц", "billing"),
]

QUESTIONS = {
    "department": {
        "type": "choice",
        "instructions": "Какой отдел должен обработать обращение?",
        "criteria": {
            "billing": "счета, платежи, возвраты денег",
            "technical": "ошибки, зависания, сбои программ",
            "sales": "цены, покупки, консультация по продукту",
        },
    },
}


def main() -> int:
    if not (MODEL_DIR / "model.safetensors").exists():
        print(f"Веса Laya не найдены: {MODEL_DIR}", file=sys.stderr)
        return 3
    import laya

    agent = laya.load(str(MODEL_DIR), device="cpu")
    latencies = []
    correct = 0
    for text, expected in CASES:
        t0 = time.perf_counter()
        result = agent.predict({"body": text}, QUESTIONS)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        answer = result["answers"]["department"]
        got = answer["choice"]
        ok = got == expected
        correct += ok
        print(f"{'PASS' if ok else 'FAIL'} {dt:7.0f} ms conf={answer['confidence']:.3f} got={got} expected={expected}")
    print(f"accuracy {correct}/{len(CASES)}  warm p50 {statistics.median(latencies):.0f} ms  max {max(latencies):.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())