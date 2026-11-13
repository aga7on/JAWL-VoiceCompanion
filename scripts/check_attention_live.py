"""One-shot live check: does the attention gate behave with real activity data?"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.attention import AttentionPresence  # noqa: E402
from jawl_voicecompanion.user_activity import WindowsUserActivity  # noqa: E402

activity = WindowsUserActivity(idle_threshold_seconds=60.0)
print("activity sample:", activity.sample())

delivered: list[dict] = []
gate = AttentionPresence(
    cooldown_seconds=0.0,
    budget_per_hour=100,
    intent_sink=delivered.append,
    activity_provider=activity.sample,
)

cases = [
    ("Появилась ошибка в редакторе кода", 3),
    ("Уведомление: обновление доступно", 2),
    ("Список файлов прокручен вниз", 2),
]
for summary, significance in cases:
    result = gate.consume(
        {
            "type": "SCREEN_DELTA",
            "event_id": summary,
            "payload": {"changed": True, "summary": summary, "significance": significance},
        }
    )
    print(f"  {summary[:38]:40} -> {result['status']:10} {result.get('reason') or ''}")
print("delivered intents:", len(delivered))