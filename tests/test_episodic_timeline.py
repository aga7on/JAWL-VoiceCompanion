"""Episodic timeline: single TimeService semantics, bounded state."""

from __future__ import annotations

import unittest

from jawl_voicecompanion.episodic_timeline import EpisodicTimeline


class FakeClock:
    def __init__(self) -> None:
        self.t = 1_700_000_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class EpisodicTimelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.tl = EpisodicTimeline(silence_cut_s=120.0, clock=self.clock)

    def test_starts_in_one_open_idle_episode(self) -> None:
        state = self.tl.state()
        self.assertTrue(state["ok"])
        self.assertEqual(state["episode_count"], 1)
        self.assertEqual(state["current"]["kind"], "idle")
        self.assertTrue(state["current"]["open"])

    def test_conversation_cuts_episode(self) -> None:
        start_id = self.tl.current()["episode_id"]
        self.clock.advance(10)
        new_id = self.tl.record("conversation", "user_voice", "привет")
        self.assertNotEqual(new_id, start_id)
        cur = self.tl.current()
        self.assertEqual(cur["kind"], "conversation")
        self.assertEqual(cur["episode_id"], new_id)
        # Previous episode is closed.
        recent = self.tl.recent()
        self.assertEqual(len(recent), 2)
        self.assertFalse(recent[1]["open"])

    def test_same_kind_does_not_recut(self) -> None:
        self.tl.record("conversation", "user_voice", "one")
        first = self.tl.current()["episode_id"]
        self.clock.advance(5)
        self.tl.record("conversation", "user_voice", "two")
        self.assertEqual(self.tl.current()["episode_id"], first)
        self.assertEqual(self.tl.state()["episode_count"], 2)

    def test_silence_cut_on_poll(self) -> None:
        self.tl.record("conversation", "user_voice", "hello")
        conv = self.tl.current()["episode_id"]
        self.clock.advance(200)  # beyond silence_cut_s
        self.assertTrue(self.tl.poll())
        self.assertEqual(self.tl.current()["kind"], "idle")
        self.assertNotEqual(self.tl.current()["episode_id"], conv)
        # Polling again with no new activity does not cut again.
        self.assertFalse(self.tl.poll())

    def test_sleep_and_wake(self) -> None:
        self.tl.record("conversation", "user_voice", "msg")
        self.tl.sleep()
        self.assertEqual(self.tl.current()["kind"], "sleep")
        # Sleep is not cut by silence.
        self.clock.advance(10_000)
        self.assertFalse(self.tl.poll())
        self.assertEqual(self.tl.current()["kind"], "sleep")
        self.tl.wake()
        self.assertEqual(self.tl.current()["kind"], "idle")

    def test_bounded_episodes(self) -> None:
        tl = EpisodicTimeline(silence_cut_s=60.0, max_episodes=64, clock=self.clock)
        for i in range(300):
            self.clock.advance(61)
            tl.record("conversation", "test", f"m{i}")
            self.clock.advance(61)
            tl.poll()
        self.assertLessEqual(tl.state()["episode_count"], 64)

    def test_window_returns_overlapping(self) -> None:
        self.tl.record("conversation", "user_voice", "a")
        self.clock.advance(30)
        self.tl.record("focus", "screen", "editor")
        self.clock.advance(30)
        recent = self.tl.window(120)
        kinds = {e["kind"] for e in recent}
        self.assertIn("conversation", kinds)
        self.assertIn("ambient", kinds)

    def test_state_fields_present(self) -> None:
        state = self.tl.state()
        for key in ("now", "episode_count", "current", "last_activity_age_s", "silence_cut_s"):
            self.assertIn(key, state)


if __name__ == "__main__":
    unittest.main()
