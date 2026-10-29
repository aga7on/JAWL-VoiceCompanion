import asyncio
import asyncio
import time
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.native_goal_wakeup_backoff import install_native_goal_wakeup_backoff


class GoalWakeupBackoffTests(unittest.TestCase):
    def test_future_deadline_suppresses_pending_goal_until_due(self):
        class Manager:
            suppress_waiting_heartbeats = False
            active_goal = SimpleNamespace(pending_work=True, next_wakeup_at=130.0)

            def should_run_heartbeat(self, now=None):
                return True

            def seconds_until_wakeup(self, now=None):
                return 0.0

            async def mark_event_pending(self, event_name):
                self.active_goal.pending_work = True

            async def finish_cycle(self, *, state, summary="", wake_after_seconds=None):
                return self.active_goal

        installed = install_native_goal_wakeup_backoff(Manager)
        manager = Manager()
        self.assertFalse(manager.should_run_heartbeat(now=100))
        self.assertEqual(manager.seconds_until_wakeup(now=100), 30.0)
        self.assertTrue(manager.should_run_heartbeat(now=130))
        self.assertEqual(manager.seconds_until_wakeup(now=130), 0.0)
        self.assertIs(install_native_goal_wakeup_backoff(Manager), installed)

    def test_external_event_clears_backoff_and_heartbeat_does_not(self):
        class Manager:
            suppress_waiting_heartbeats = True
            active_goal = SimpleNamespace(pending_work=True, next_wakeup_at=130.0)

            def should_run_heartbeat(self, now=None):
                return True

            def seconds_until_wakeup(self, now=None):
                return 0.0

            async def mark_event_pending(self, event_name):
                self.active_goal.pending_work = True

            async def finish_cycle(self, *, state, summary="", wake_after_seconds=None):
                return self.active_goal

        install_native_goal_wakeup_backoff(Manager)
        manager = Manager()
        asyncio.run(manager.mark_event_pending("HEARTBEAT"))
        self.assertEqual(manager.active_goal.next_wakeup_at, 130.0)
        asyncio.run(manager.mark_event_pending("USER_MESSAGE"))
        self.assertIsNone(manager.active_goal.next_wakeup_at)
        self.assertTrue(manager.should_run_heartbeat(now=100))

    def test_duplicate_successes_back_off_then_block_after_bounded_retries(self):
        class Manager:
            def __init__(self):
                self.active_goal = SimpleNamespace(
                    goal_id="g1", pending_work=True, next_wakeup_at=None,
                    last_summary="", last_cycle_status="running:HEARTBEAT",
                )

            def should_run_heartbeat(self, now=None):
                return True

            def seconds_until_wakeup(self, now=None):
                return 0.0

            async def mark_event_pending(self, event_name):
                self.active_goal.pending_work = True

            async def finish_cycle(self, *, state, summary="", wake_after_seconds=None):
                goal = self.active_goal
                goal.last_cycle_status = state
                goal.last_summary = summary
                goal.pending_work = state in {"continue", "failed", "exhausted"}
                goal.next_wakeup_at = (
                    time.time() + wake_after_seconds
                    if wake_after_seconds is not None else None
                )
                return goal

        install_native_goal_wakeup_backoff(Manager)
        manager = Manager()
        duplicate_summary = (
            "A previously successful native action batch was proposed again; "
            "it was not re-executed."
        )
        observed_delays = []
        for expected in (1, 2, 4, 8, 16):
            goal = asyncio.run(manager.finish_cycle(
                state="continue", summary=duplicate_summary, wake_after_seconds=1
            ))
            self.assertEqual(goal.last_cycle_status, "continue")
            self.assertIn(f"no-progress-repeat={len(observed_delays) + 1}", goal.last_summary)
            delay = goal.next_wakeup_at - time.time()
            observed_delays.append(round(delay))
            self.assertEqual(observed_delays[-1], expected)
            self.assertFalse(manager.should_run_heartbeat(now=time.time()))
        goal = asyncio.run(manager.finish_cycle(
            state="continue", summary=duplicate_summary, wake_after_seconds=1
        ))
        self.assertEqual(goal.last_cycle_status, "blocked")
        self.assertFalse(goal.pending_work)
        self.assertIsNone(goal.next_wakeup_at)
        self.assertIn("operator review is required", goal.last_summary)

    def test_external_event_resets_duplicate_retry_budget(self):
        class Manager:
            def __init__(self):
                self.active_goal = SimpleNamespace(
                    goal_id="g2", pending_work=True, next_wakeup_at=None,
                    last_summary="", last_cycle_status="running:HEARTBEAT",
                )

            def should_run_heartbeat(self, now=None):
                return True

            def seconds_until_wakeup(self, now=None):
                return 0.0

            async def mark_event_pending(self, event_name):
                self.active_goal.pending_work = True

            async def finish_cycle(self, *, state, summary="", wake_after_seconds=None):
                goal = self.active_goal
                goal.last_cycle_status = state
                goal.last_summary = summary
                goal.pending_work = True
                goal.next_wakeup_at = time.time() + (wake_after_seconds or 1)
                return goal

        install_native_goal_wakeup_backoff(Manager)
        manager = Manager()
        summary = "A previously successful native action batch was proposed again."
        asyncio.run(manager.finish_cycle(state="continue", summary=summary, wake_after_seconds=1))
        asyncio.run(manager.finish_cycle(state="continue", summary=summary, wake_after_seconds=1))
        self.assertIn("no-progress-repeat=2", manager.active_goal.last_summary)
        asyncio.run(manager.mark_event_pending("USER_MESSAGE"))
        self.assertIsNone(manager.active_goal.next_wakeup_at)
        goal = asyncio.run(manager.finish_cycle(state="continue", summary=summary, wake_after_seconds=1))
        self.assertIn("no-progress-repeat=1", goal.last_summary)

    def test_pending_without_deadline_keeps_native_manager_semantics(self):
        class Manager:
            suppress_waiting_heartbeats = True
            active_goal = SimpleNamespace(pending_work=True, next_wakeup_at=None)

            def should_run_heartbeat(self, now=None):
                return self.active_goal.pending_work

            def seconds_until_wakeup(self, now=None):
                return 9.0

            async def mark_event_pending(self, event_name):
                pass

            async def finish_cycle(self, *, state, summary="", wake_after_seconds=None):
                return self.active_goal

        install_native_goal_wakeup_backoff(Manager)
        manager = Manager()
        self.assertTrue(manager.should_run_heartbeat(now=10))
        self.assertEqual(manager.seconds_until_wakeup(now=10), 0.0)
        manager.suppress_waiting_heartbeats = False
        self.assertTrue(manager.should_run_heartbeat(now=10))


if __name__ == "__main__":
    unittest.main()
