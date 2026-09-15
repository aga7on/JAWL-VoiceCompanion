import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.proactive import ProactiveFeed  # noqa: E402


class FakeClient:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = 0

    def chat_history(self, limit=50):
        self.calls += 1
        return list(self.rows[-limit:])


class FakeHistory:
    def __init__(self, turns=None):
        self._turns = list(turns or [])

    def turns(self, limit=100):
        return list(self._turns[-limit:])


def _turn(text, age_s=3600.0):
    created = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {
        "created_at": created.isoformat(),
        "user": "q",
        "response": {"text": text},
    }


def _row(text, sender="Companion", time="2026-09-12 09:00:00"):
    return {"sender": sender, "text": text, "time": time}


class ProactiveFeedTests(unittest.TestCase):
    def test_baseline_history_is_not_delivered(self):
        client = FakeClient([_row("old braindump", time="2026-09-12 08:00:00")])
        feed = ProactiveFeed(client, history=FakeHistory(), poll_interval_s=1.0)
        self.assertEqual(feed.poll(now=1000.0), [])
        self.assertEqual(feed.poll(now=1010.0), [])
        self.assertEqual(feed.state()["queued"], [])

    def test_new_message_delivered_when_idle(self):
        client = FakeClient()
        feed = ProactiveFeed(client, history=FakeHistory(), poll_interval_s=1.0)
        feed.poll(now=1000.0)
        client.rows.append(_row("new initiative", time="2026-09-12 09:10:00"))
        delivered = feed.poll(now=1010.0)
        self.assertEqual([item["text"] for item in delivered], ["new initiative"])
        self.assertTrue(delivered[0]["speak"] is True)

    def test_reply_echo_is_not_proactive(self):
        client = FakeClient()
        history = FakeHistory([_turn("Привет, это ответ на ход.")])
        feed = ProactiveFeed(client, history=history, poll_interval_s=1.0)
        feed.poll(now=1000.0)
        client.rows.append(_row("Привет, это ответ на ход.", time="2026-09-12 09:11:00"))
        self.assertEqual(feed.poll(now=1010.0), [])

    def test_muted_queues_and_unmute_delivers(self):
        client = FakeClient()
        feed = ProactiveFeed(client, history=FakeHistory(), poll_interval_s=1.0)
        feed.poll(now=1000.0)
        feed.update_settings(muted=True)
        client.rows.append(_row("не сейчас", time="2026-09-12 09:12:00"))
        self.assertEqual(feed.poll(now=1010.0), [])
        self.assertEqual(len(feed.state()["queued"]), 1)
        feed.update_settings(muted=False)
        delivered = feed.poll(now=1020.0)
        self.assertEqual([item["text"] for item in delivered], ["не сейчас"])
        self.assertEqual(feed.state()["queued"], [])

    def test_rate_limit_holds_second_message(self):
        client = FakeClient()
        feed = ProactiveFeed(client, history=FakeHistory(), poll_interval_s=1.0, min_gap_s=300.0)
        feed.poll(now=1000.0)
        client.rows.append(_row("первое", time="2026-09-12 09:13:00"))
        first = feed.poll(now=1010.0)
        self.assertEqual(len(first), 1)
        client.rows.append(_row("второе", time="2026-09-12 09:14:00"))
        self.assertEqual(feed.poll(now=1020.0), [])
        hold = feed.poll(now=1400.0)
        self.assertEqual([item["text"] for item in hold], ["второе"])

    def test_recent_turn_holds_delivery(self):
        client = FakeClient()
        history = FakeHistory([_turn("только что ответили", age_s=5.0)])
        feed = ProactiveFeed(client, history=history, poll_interval_s=1.0, idle_after_turn_s=45.0)
        feed.poll(now=1000.0)
        client.rows.append(_row("инициатива", time="2026-09-12 09:15:00"))
        self.assertEqual(feed.poll(now=1010.0), [])
        self.assertEqual(len(feed.state()["queued"]), 1)

    def test_hourly_cap(self):
        client = FakeClient()
        feed = ProactiveFeed(
            client, history=FakeHistory(), poll_interval_s=1.0,
            min_gap_s=0.0, max_per_hour=2,
        )
        feed.poll(now=1000.0)
        for index in range(3):
            client.rows.append(_row(f"msg {index}", time=f"2026-09-12 09:2{index}:00"))
            feed.poll(now=1010.0 + index * 10)
        state = feed.state(now=1030.0)
        self.assertEqual(state["delivered_last_hour"], 2)
        self.assertEqual(len(state["queued"]), 1)

    def test_noise_feedback_opens_quiet_window(self):
        client = FakeClient()
        feed = ProactiveFeed(client, history=FakeHistory(), poll_interval_s=1.0, min_gap_s=0.0)
        feed.poll(now=1000.0)
        client.rows.append(_row("шумная инициатива", time="2026-09-12 09:30:00"))
        delivered = feed.poll(now=1010.0)
        self.assertEqual(len(delivered), 1)
        feed.note_feedback(delivered[0]["id"], "noise")
        client.rows.append(_row("следующая", time="2026-09-12 09:31:00"))
        self.assertEqual(feed.poll(now=1020.0), [])
        self.assertGreater(feed.state(now=1020.0)["quiet_for_s"], 0.0)
        self.assertEqual(len(feed.state(now=1020.0)["queued"]), 1)
        feed.note_feedback(delivered[0]["id"], "useful")
        self.assertEqual(feed.state(now=1021.0)["noise_streak"], 0)
        self.assertEqual(len(feed.poll(now=1030.0)), 1)

    def test_duplicate_text_suppressed_within_day(self):
        client = FakeClient()
        feed = ProactiveFeed(client, history=FakeHistory(), poll_interval_s=1.0, min_gap_s=0.0)
        feed.poll(now=1000.0)
        client.rows.append(_row("нет новых задач", time="2026-09-12 09:40:00"))
        self.assertEqual(len(feed.poll(now=1010.0)), 1)
        client.rows.append(_row("нет новых задач", time="2026-09-12 09:41:00"))
        self.assertEqual(feed.poll(now=1020.0), [])
        self.assertEqual(feed.state(now=1020.0)["suppressed_duplicates"], 1)

    def test_inactive_hour_queues_delivery(self):
        import datetime

        def _stamp(day, hour):
            return datetime.datetime(
                2026, 9, day, hour, 0, tzinfo=datetime.timezone.utc
            ).isoformat()

        history = FakeHistory([
            {"created_at": _stamp(10, 10), "user": "q", "response": {"text": "a"}},
            {"created_at": _stamp(11, 10), "user": "q", "response": {"text": "b"}},
            {"created_at": _stamp(11, 14), "user": "q", "response": {"text": "c"}},
        ])
        feed = ProactiveFeed(FakeClient(), history=history, poll_interval_s=1.0, min_gap_s=0.0)
        active = feed._active_hours(1010.0)
        self.assertEqual(active, {10})
        client = feed.client
        feed.poll(now=1010.0)
        client.rows.append(_row("инициатива", time="2026-09-12 14:10:00"))
        moment_14 = datetime.datetime(2026, 9, 12, 14, 10, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(feed.poll(now=moment_14), [])
        self.assertEqual(len(feed.state(now=moment_14)["queued"]), 1)

    def test_quiet_state_persists_across_restart(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proactive-state.json"
            client = FakeClient()
            feed = ProactiveFeed(
                client, history=FakeHistory(), poll_interval_s=1.0,
                min_gap_s=0.0, state_path=state_path,
            )
            feed.poll(now=1000.0)
            client.rows.append(_row("раздражающая", time="2026-09-12 09:50:00"))
            delivered = feed.poll(now=1010.0)
            feed.note_feedback(delivered[0]["id"], "noise")
            fresh = ProactiveFeed(
                FakeClient(), history=FakeHistory(), poll_interval_s=1.0,
                min_gap_s=0.0, state_path=state_path,
            )
            self.assertGreater(fresh.state()["quiet_for_s"], 0.0)
            self.assertEqual(fresh.state()["noise_streak"], 1)

    def test_queued_items_persist_across_restart(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proactive-state.json"
            client = FakeClient()
            feed = ProactiveFeed(
                client, history=FakeHistory(), poll_interval_s=1.0,
                min_gap_s=0.0, state_path=state_path,
            )
            feed.poll(now=1000.0)
            feed.update_settings(muted=True)
            client.rows.append(_row("переживу рестарт", time="2026-09-12 09:56:00"))
            feed.poll(now=1010.0)
            self.assertEqual(len(feed.state(now=1010.0)["queued"]), 1)
            fresh = ProactiveFeed(
                FakeClient(), history=FakeHistory(), poll_interval_s=1.0,
                min_gap_s=0.0, state_path=state_path,
            )
            state = fresh.state(now=1011.0)
            self.assertEqual(len(state["queued"]), 1)
            self.assertEqual(state["queued"][0]["text"], "переживу рестарт")


if __name__ == "__main__":
    unittest.main()
