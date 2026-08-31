import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority  # noqa: E402


class TurnArbiterTests(unittest.TestCase):
    def test_user_turn_preempts_background_and_cancels_stale_queue(self):
        arbiter = TurnArbiter()
        background = arbiter.begin(TurnPriority.BACKGROUND)
        screen = arbiter.begin(TurnPriority.SCREEN_DELTA)
        user = arbiter.begin(TurnPriority.USER_FINAL)
        self.assertTrue(background.cancelled)
        self.assertTrue(screen.cancelled)
        self.assertTrue(arbiter.is_current(user))

    def test_lower_priority_work_waits_and_is_promoted(self):
        arbiter = TurnArbiter()
        user = arbiter.begin(TurnPriority.USER_FINAL)
        background = arbiter.begin(TurnPriority.BACKGROUND)
        self.assertFalse(background.active)
        promoted = arbiter.complete(user)
        self.assertIs(promoted, background)
        self.assertTrue(arbiter.is_current(background))

    def test_newer_equal_priority_turn_cancels_old_turn(self):
        arbiter = TurnArbiter()
        old_user = arbiter.begin(TurnPriority.USER_FINAL)
        new_user = arbiter.begin(TurnPriority.USER_FINAL)
        self.assertTrue(old_user.cancelled)
        self.assertEqual(old_user.cancel_reason, "superseded_by_newer_priority_turn")
        self.assertTrue(arbiter.is_current(new_user))


if __name__ == "__main__":
    unittest.main()

