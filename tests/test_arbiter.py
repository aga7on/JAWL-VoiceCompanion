import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority  # noqa: E402


class TurnArbiterBoundTests(unittest.TestCase):
    def test_queue_is_bounded_and_overflow_is_cancelled(self):
        arbiter = TurnArbiter()
        holder = arbiter.begin(TurnPriority.USER_FINAL)
        tokens = [arbiter.begin(TurnPriority.BACKGROUND) for _ in range(12)]
        state = arbiter.state()
        self.assertLessEqual(len(state["queued"]), 8)
        cancelled = [token for token in tokens if token.cancelled]
        self.assertEqual(len(cancelled), 4)
        self.assertTrue(all(token.cancel_reason == "queue_overflow" for token in cancelled))

    def test_oldest_waiter_promotes_after_overflow(self):
        arbiter = TurnArbiter()
        holder = arbiter.begin(TurnPriority.USER_FINAL)
        first_waiting = arbiter.begin(TurnPriority.BACKGROUND)
        for _ in range(12):
            arbiter.begin(TurnPriority.BACKGROUND)
        promoted = arbiter.complete(holder)
        self.assertIsNotNone(promoted)
        self.assertIs(promoted, first_waiting)
        self.assertFalse(promoted.cancelled)


if __name__ == "__main__":
    unittest.main()
