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


class PresenceBackoffTests(unittest.TestCase):
    def _watcher(self, vision, interval=10.0):
        return ScreenDeltaWatcher(vision, TurnArbiter(), interval_seconds=interval)

    def test_unchanged_screen_backs_off_polling(self):
        class FakeVision:
            def look(self, prompt, *, session_id):
                return {"status": "unchanged", "description": "same", "vlm_called": False}

        watcher = self._watcher(FakeVision())
        waits = []
        for _ in range(6):
            watcher.poll_once()
            waits.append(watcher.state()["next_wait_seconds"])
        self.assertEqual(waits[0], 10.0)
        self.assertEqual(waits[1], 20.0)
        self.assertEqual(waits[2], 30.0)
        self.assertEqual(waits[3], 40.0)
        self.assertEqual(waits[5], 40.0)

    def test_published_change_resets_backoff(self):
        class FakeVision:
            status = "unchanged"

            def look(self, prompt, *, session_id):
                return {"status": self.status, "description": "frame"}

        vision = FakeVision()
        watcher = self._watcher(vision)
        for _ in range(4):
            watcher.poll_once()
        self.assertGreater(watcher.state()["next_wait_seconds"], 10.0)
        vision.status = "ok"
        watcher.poll_once()
        self.assertEqual(watcher.state()["idle_polls"], 0)
        self.assertEqual(watcher.state()["next_wait_seconds"], 10.0)

    def test_deferred_user_turn_clears_backoff(self):
        class FakeVision:
            def look(self, prompt, *, session_id):
                return {"status": "unchanged", "description": "same"}

        arbiter = TurnArbiter()
        watcher = ScreenDeltaWatcher(FakeVision(), arbiter, interval_seconds=10.0)
        for _ in range(3):
            watcher.poll_once()
        self.assertEqual(watcher.state()["next_wait_seconds"], 30.0)
        user_turn = arbiter.begin(TurnPriority.USER_FINAL)
        self.assertEqual(watcher.poll_once()["status"], "deferred")
        arbiter.complete(user_turn)
        self.assertEqual(watcher.state()["next_wait_seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
