"""Laya-multilingual RU smoke: System-1 typed decisions on Russian state.

Usage: python -X utf8 scripts/run_laya_ru_smoke.py [model_dir] [device=cpu]
Prints answers; exit 0 on success.
"""
from __future__ import annotations

import sys
from pathlib import Path

MODEL_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else r"G:\AI\JAWL-VoiceCompanion\runtime\models\laya-multilingual")
DEVICE = sys.argv[2] if len(sys.argv) > 2 else "cpu"

STATES = [
    {"body": "Сегодня утром снова завис браузер, пока я работал с отчётом. Ошибка каждый раз при открытии вкладки."},
    {"body": "Вижу в счёте двойное списание за подписку, верните деньги на карту."},
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
    "urgency": {
        "type": "choice",
        "instructions": "Насколько срочное обращение?",
        "criteria": {"low": "нет срочности", "high": "система не работает / деньги потеряны"},
    },
}


def main() -> int:
    if not (MODEL_DIR / "model.safetensors").exists():
        print(f"Веса Laya ещё не скачаны: {MODEL_DIR}", file=sys.stderr)
        return 3
    import laya

    print(f"Загрузка Laya из {MODEL_DIR} ...")
    agent = laya.load(str(MODEL_DIR), device=DEVICE)
    for i, state in enumerate(STATES, 1):
        try:
            result = agent.predict(state, QUESTIONS)
            answers = result["answers"]
            print(f"state {i}: {state['body'][:50]}...")
            for q, a in answers.items():
                print(f"  {q}: {a}")
        except Exception as exc:  # noqa: BLE001
            print(f"state {i}: ERROR {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())