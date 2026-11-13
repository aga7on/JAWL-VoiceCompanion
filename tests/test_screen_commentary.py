"""Tests for the D4 screen-commentary initiative lane (own MOSS-Live analog).

Covers the owner requirements: the brain must get a bounded screen event and
may answer «тишина» to decline; accepted comments reach the proactive feed;
filler answers («Работаю»/«Готово») are rejected; rate limits gate repeats;
delivery bypasses the echo scan of the chat-history poll.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.proactive import ProactiveFeed  # noqa: E402
from jawl_voicecompanion.screen_commentary import (  # noqa: E402
    ScreenCommentaryScheduler,
    _is_noise_answer,
)

_EVENT = {
    "event_id": "ev-1",
    "created_at": "2026-11-10T01:00:00",
    "description": "На экране появился отчёт с большими числами за квартал.",
}


class _FakeWatcher:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = list(events)

    def events(self) -> list[dict[str, object]]:
        return list(self._events)


class _FakeBus:
    def chat_history(self, limit: int = 50) -> list[dict[str, str]]:
        return []


class _FakeGateway:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.history_store = None

    def handle_text(self, text: str, **_kwargs: object) -> dict[str, object]:
        self.prompts.append(text)
        return {"admitted": True, "text": self.reply, "speak": True}


class _NoMuteFeed(ProactiveFeed):
    """Idle feed: everything queued is delivered immediately."""

    def _idle(self, now: float) -> bool:  # noqa: D401 — historical helper name
        return True


class ScreenCommentaryTests(unittest.TestCase):
    def _scheduler(
        self,
        reply: str,
        events: list[dict[str, object]] | None = None,
        **kwargs: object,
    ) -> tuple[ScreenCommentaryScheduler, _FakeGateway, _NoMuteFeed]:
        gateway = _FakeGateway(reply)
        feed = _NoMuteFeed(_FakeBus(), min_gap_s=0.0, max_per_hour=10)
        options = {"enabled": True, "idle_after_turn_s": 0.0, "min_gap_s": 0.0, "max_per_hour": 5}
        options.update(kwargs)
        actual_events = [_EVENT] if events is None else events
        scheduler = ScreenCommentaryScheduler(
            lambda: _FakeWatcher(actual_events), gateway, feed, **options
        )
        return scheduler, gateway, feed

    def test_accepted_comment_reaches_feed(self) -> None:
        scheduler, gateway, feed = self._scheduler("Вижу готовый отчёт, вы просили напомнить.")
        scheduler.tick()
        self.assertTrue(scheduler.join_inflight(timeout=5.0))
        self.assertIn("НАБЛЮДЕНИЕ ЭКРАНА", gateway.prompts[0])
        self.assertEqual(feed._delivered[-1]["text"], "Вижу готовый отчёт, вы просили напомнить.")
        self.assertEqual(feed._delivered[-1]["source"], "screen_commentary")
        self.assertEqual(scheduler.state()["deliveries"], 1)

    def test_silence_answer_is_suppressed(self) -> None:
        scheduler, gateway, feed = self._scheduler("тишина")
        scheduler.tick()
        self.assertTrue(scheduler.join_inflight(timeout=5.0))
        self.assertEqual(feed._delivered, [])
        self.assertEqual(scheduler.state()["suppressed_silence"], 1)

    def test_filler_answer_is_rejected(self) -> None:
        scheduler, _gateway, feed = self._scheduler("Готово")
        scheduler.tick()
        self.assertTrue(scheduler.join_inflight(timeout=5.0))
        self.assertEqual(feed._delivered, [])
        self.assertEqual(scheduler.state()["suppressed_silence"], 1)
        self.assertTrue(_is_noise_answer("Работаю"))
        self.assertFalse(_is_noise_answer("Источник растёт: отчёт за квартал вырос на 40%."))

    def test_min_gap_blocks_repeat_turns(self) -> None:
        scheduler, gateway, _feed = self._scheduler("Короткий комментарий.", min_gap_s=600.0)
        scheduler.tick()
        self.assertTrue(scheduler.join_inflight(timeout=5.0))
        before = len(gateway.prompts)
        scheduler.tick()
        self.assertTrue(scheduler.join_inflight(timeout=2.0))
        self.assertEqual(len(gateway.prompts), before)

    def test_disabled_lane_never_spawns_turns(self) -> None:
        scheduler, gateway, _feed = self._scheduler("Короткий комментарий.", enabled=False)
        scheduler.tick()
        self.assertEqual(gateway.prompts, [])

    def test_no_events_is_noop(self) -> None:
        scheduler, gateway, _feed = self._scheduler("Короткий комментарий.", events=[])
        scheduler.tick()
        self.assertEqual(gateway.prompts, [])

    def test_sensory_motivation_suppresses_low_novelty_events(self) -> None:
        from jawl_voicecompanion.sensory_motivation import SensoryMotivation, SensoryMotivationConfig

        sm = SensoryMotivation(SensoryMotivationConfig(threshold=0.8, rise_gain=0.1, cooldown_s=0.0))
        scheduler, gateway, _feed = self._scheduler(
            "Короткий комментарий.", sensory_motivation=sm
        )
        scheduler.tick()
        self.assertEqual(gateway.prompts, [])
        self.assertEqual(scheduler.state()["suppressed_motivation"], 1)

    def test_sensory_motivation_passes_high_novelty_change_event(self) -> None:
        from jawl_voicecompanion.sensory_motivation import SensoryMotivation, SensoryMotivationConfig

        sm = SensoryMotivation(SensoryMotivationConfig(threshold=0.3, rise_gain=0.9, cooldown_s=0.0))
        event = {
            "event_id": "ev-crit",
            "created_at": "2026-11-10T01:05:00",
            "description": "Появилось диалоговое окно с критической ошибкой компиляции кода и предупреждением.",
        }
        scheduler, gateway, feed = self._scheduler(
            "Обнаружена ошибка компиляции в проекте.", events=[event], sensory_motivation=sm
        )
        scheduler.tick()
        self.assertTrue(scheduler.join_inflight(timeout=5.0))
        self.assertEqual(len(gateway.prompts), 1)
        self.assertEqual(feed._delivered[-1]["text"], "Обнаружена ошибка компиляции в проекте.")
        self.assertEqual(scheduler.state()["suppressed_motivation"], 0)
        self.assertEqual(scheduler.state()["deliveries"], 1)



class DeliverDirectTests(unittest.TestCase):
    def test_direct_delivery_reaches_state_and_skips_history_scan(self) -> None:
        feed = _NoMuteFeed(_FakeBus(), min_gap_s=0.0, max_per_hour=10)
        result = feed.deliver_direct("Отчёт за квартал готов, впервые вырос на 8%.", source="screen_commentary")
        self.assertTrue(result["queued"])
        state = feed.poll_state()
        self.assertIn("screen_commentary", state["delivered"][-1].get("source", "screen_commentary"))

    def test_duplicate_direct_delivery_is_suppressed(self) -> None:
        feed = _NoMuteFeed(_FakeBus(), min_gap_s=0.0, max_per_hour=10)
        first = feed.deliver_direct("Отчёт за квартал готов.")
        second = feed.deliver_direct("Отчёт за квартал готов.")
        self.assertTrue(first["queued"])
        self.assertFalse(second["queued"])
        self.assertEqual(second.get("reason"), "duplicate")


if __name__ == "__main__":
    unittest.main()
