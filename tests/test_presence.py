import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority  # noqa: E402
from jawl_voicecompanion.presence import ScreenDeltaWatcher  # noqa: E402


class PresenceTests(unittest.TestCase):
    def test_poll_publishes_bounded_screen_delta_without_image(self):
        class FakeVision:
            def look(self, prompt, *, session_id):
                return {
                    "status": "ok",
                    "description": "В окне редактора появилась ошибка.",
                    "captured_at": "2026-09-01T12:00:00+00:00",
                    "persisted": False,
                }

        events = []
        watcher = ScreenDeltaWatcher(
            FakeVision(),
            TurnArbiter(),
            event_sink=events.append,
        )
        result = watcher.poll_once()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["type"], "SCREEN_DELTA")
        self.assertEqual(event["priority"], int(TurnPriority.SCREEN_DELTA))
        self.assertEqual(event["payload"]["summary"], "В окне редактора появилась ошибка.")
        self.assertFalse(event["payload"]["raw_frame_persisted"])
        self.assertNotIn("image", event)

    def test_poll_is_deferred_while_user_turn_is_active(self):
        class FakeVision:
            calls = 0

            def look(self, prompt, *, session_id):
                self.calls += 1
                return {"status": "ok", "description": "не должно вызваться"}

        arbiter = TurnArbiter()
        user_turn = arbiter.begin(TurnPriority.USER_FINAL)
        vision = FakeVision()
        watcher = ScreenDeltaWatcher(vision, arbiter)
        result = watcher.poll_once()
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(vision.calls, 0)
        self.assertTrue(arbiter.is_current(user_turn))
        arbiter.complete(user_turn)

    def test_event_sink_failure_does_not_break_poll(self):
        class FakeVision:
            def look(self, prompt, *, session_id):
                return {"status": "ok", "description": "изменение"}

        def broken_sink(event):
            raise RuntimeError("consumer failed")

        watcher = ScreenDeltaWatcher(FakeVision(), TurnArbiter(), event_sink=broken_sink)
        result = watcher.poll_once()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(watcher.state()["last_error"], "screen_event_sink_failed")


if __name__ == "__main__":
    unittest.main()
