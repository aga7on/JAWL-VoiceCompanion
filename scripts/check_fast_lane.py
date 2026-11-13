"""Check the kernel's fast-lane classifier against the real test utterances."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"
sys.path.insert(0, str(SOURCE))
os.environ.setdefault("JAWL_FAST_CONVERSATION", "1")

from src.l3_agent.context.companion import is_conversational_text  # noqa: E402

UTTERANCES = [
    "Какой сегодня статус моего проекта?",
    "Запомни, пожалуйста, что я предпочитаю короткие ответы.",
    "Сможешь проверить тестовый файл и сообщить результат?",
    "Привет, как дела?",
    "Что ты видишь на экране?",
    "Расскажи что-нибудь интересное.",
]

for text in UTTERANCES:
    verdict = is_conversational_text(text)
    print(f"{'FAST' if verdict else 'full':5}  len={len(text):3d}  {text}")
    if not verdict:
        # Show which token triggered the full path.
        import re
        from src.l3_agent.context.companion import _ACTION_KEYWORDS_RE
        match = _ACTION_KEYWORDS_RE.search(text)
        reason = f"keyword={match.group(0)!r}" if match else (
            "too long" if len(text) > 160 else "slash command"
        )
        print(f"        -> {reason}")