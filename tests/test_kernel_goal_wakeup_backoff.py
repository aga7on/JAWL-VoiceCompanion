"""Kernel Goal wakeup backoff for the native JAWL goal manager.

Spec lineage: the retired product extension ``native_goal_wakeup_backoff``
(ADR-049 slice 7). ``GoalManager`` delegates natively to ``goals.wakeup_backoff``;
wake deadlines persist while external events resume early.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-backoff-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l3_agent.goals import wakeup_backoff  # noqa: E402


class GoalWakeupBackoffTests(unittest.TestCase):
    def test_future_deadline_suppresses_pending_goal_until_due(self):
        manager = SimpleNamespace(
            suppress_waiting_heartbeats=False,
            active_goal=SimpleNamespace(pending_work=True, next_wakeup_at=130.0),
        )
        self.assertFalse(wakeup_backoff.should_run(manager, now=100))
        self.assertEqual(wakeup_backoff.seconds_until(manager, now=100), 30.0)
        self.assertTrue(wakeup_backoff.should_run(manager, now=130))
        self.assertEqual(wakeup_backoff.seconds_until(manager, now=130), 0.0)

    def test_external_event_clears_backoff_and_heartbeat_does_not(self):
        goal = SimpleNamespace(pending_work=True, next_wakeup_at=130.0, goal_id="g0")
        manager = SimpleNamespace(
            suppress_waiting_heartbeats=True, active_goal=goal,
            _jawl_duplicate_action_counts={"g0": 2},
        )
        wakeup_backoff.clear_backoff_for_event(manager, "HEARTBEAT")
        self.assertEqual(goal.next_wakeup_at, 130.0)
        wakeup_backoff.clear_backoff_for_event(manager, "USER_MESSAGE")
        self.assertIsNone(goal.next_wakeup_at)
        self.assertNotIn("g0", manager._jawl_duplicate_action_counts)
        self.assertTrue(wakeup_backoff.should_run(manager, now=100))

    def test_duplicate_successes_back_off_then_block_after_bounded_retries(self):
        manager = SimpleNamespace(
            active_goal=SimpleNamespace(
                goal_id="g1", pending_work=True, next_wakeup_at=None,
            ),
        )
        duplicate_summary = (
            "A previously successful native action batch was proposed again; "
            "it was not re-executed."
        )
        observed_delays = []
        for expected in (1, 2, 4, 8, 16):
            state, summary, wake = wakeup_backoff.apply_duplicate_backoff(
                manager, state="continue", summary=duplicate_summary, wake_after_seconds=1
            )
            self.assertEqual(state, "continue")
            self.assertIn(f"no-progress-repeat={len(observed_delays) + 1}", summary)
            self.assertEqual(wake, expected)
            observed_delays.append(wake)
        state, summary, wake = wakeup_backoff.apply_duplicate_backoff(
            manager, state="continue", summary=duplicate_summary, wake_after_seconds=1
        )
        self.assertEqual(state, "blocked")
        self.assertIsNone(wake)
        self.assertIn("operator review is required", summary)
        self.assertNotIn("g1", wakeup_backoff.duplicate_counts(manager))

    def test_external_event_resets_duplicate_retry_budget(self):
        manager = SimpleNamespace(
            active_goal=SimpleNamespace(goal_id="g2", pending_work=True, next_wakeup_at=None),
        )
        summary = "A previously successful native action batch was proposed again."
        wakeup_backoff.apply_duplicate_backoff(
            manager, state="continue", summary=summary, wake_after_seconds=1
        )
        _, summary2, _ = wakeup_backoff.apply_duplicate_backoff(
            manager, state="continue", summary=summary, wake_after_seconds=1
        )
        self.assertIn("no-progress-repeat=2", summary2)
        wakeup_backoff.clear_backoff_for_event(manager, "USER_MESSAGE")
        _, summary3, _ = wakeup_backoff.apply_duplicate_backoff(
            manager, state="continue", summary=summary, wake_after_seconds=1
        )
        self.assertIn("no-progress-repeat=1", summary3)

    def test_pending_without_deadline_keeps_native_manager_semantics(self):
        manager = SimpleNamespace(
            suppress_waiting_heartbeats=True,
            active_goal=SimpleNamespace(pending_work=True, next_wakeup_at=None),
        )
        self.assertTrue(wakeup_backoff.should_run(manager, now=10))
        self.assertEqual(wakeup_backoff.seconds_until(manager, now=10), 0.0)
        manager.suppress_waiting_heartbeats = False
        self.assertTrue(wakeup_backoff.should_run(manager, now=10))

    def test_goal_manager_delegates_to_the_backoff_module(self):
        source = (_SNAPSHOT / "src/l3_agent/goals/manager.py").read_text(encoding="utf-8")
        self.assertIn("return wakeup_backoff.should_run(self, now)", source)
        self.assertIn("return wakeup_backoff.seconds_until(self, now)", source)
        self.assertIn("wakeup_backoff.clear_backoff_for_event(self, event_name)", source)
        self.assertIn("wakeup_backoff.apply_duplicate_backoff(", source)


if __name__ == "__main__":
    unittest.main()
