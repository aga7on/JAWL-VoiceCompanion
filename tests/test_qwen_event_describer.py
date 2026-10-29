import sys
import time
import unittest
from threading import Event, Lock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.qwen_event_describer import QwenEventDescriber  # noqa: E402


class QwenEventDescriberTests(unittest.TestCase):
    def _wait(self, describer, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            observation = describer.poll()
            if observation is not None:
                return observation
            time.sleep(0.02)
        self.fail("observation was not produced")

    def test_truncated_64_retries_at_128_and_stays_plain_text(self):
        calls = []

        def transport(payload):
            calls.append(payload)
            if payload["max_tokens"] == 64:
                return "A planet Earth is shown from space with lit cities", True
            return "A planet Earth is shown from space with lit cities and oceans.", False

        describer = QwenEventDescriber("http://127.0.0.1:1", transport=transport)
        describer.start()
        try:
            self.assertTrue(describer.submit(b"\xff\xd8fake-jpeg", observed_at=time.time(), source="screen", event_id="evt-1"))
            observation = self._wait(describer)
        finally:
            describer.stop()
        self.assertEqual(observation.budget, 128)
        self.assertFalse(observation.truncated)
        self.assertEqual(observation.source, "screen")
        self.assertEqual(observation.event_id, "evt-1")
        self.assertIn("Earth", observation.caption)
        self.assertEqual(len(calls), 2)
        for payload in calls:
            self.assertNotIn("response_format", payload)
            content = payload["messages"][0]["content"]
            self.assertEqual([part["type"] for part in content], ["text", "image_url"])
            self.assertNotIn("input_audio", payload)
            self.assertNotIn("ocr", str(payload).lower())

    def test_age_and_stale_are_code_owned(self):
        describer = QwenEventDescriber(
            "http://127.0.0.1:1",
            max_age_s=1.0,
            transport=lambda payload: ("A planet Earth is shown from space.", False),
        )
        describer.start()
        try:
            old = time.time() - 5.0
            self.assertTrue(describer.submit(b"\xff\xd8fake-jpeg", observed_at=old))
            observation = self._wait(describer)
        finally:
            describer.stop()
        self.assertGreaterEqual(observation.age_ms, 4000.0)
        self.assertTrue(observation.stale)

    def test_freshness_uses_monotonic_capture_time_not_wall_clock(self):
        describer = QwenEventDescriber(
            "http://127.0.0.1:1",
            max_age_s=0.5,
            transport=lambda payload: ("A classroom is visible.", False),
        )
        describer.start()
        try:
            # A wall timestamp far in the future simulates a clock correction;
            # the monotonic capture age still correctly marks this stale.
            self.assertTrue(describer.submit(
                b"frame",
                observed_at=time.time() + 3600.0,
                captured_monotonic=time.monotonic() - 2.0,
            ))
            observation = self._wait(describer)
        finally:
            describer.stop()
        self.assertGreaterEqual(observation.age_ms, 1900.0)
        self.assertTrue(observation.stale)

    def test_latest_pending_wins(self):
        describer = QwenEventDescriber(
            "http://127.0.0.1:1",
            transport=lambda payload: ("A planet Earth is shown from space.", False),
        )
        describer.start()
        try:
            self.assertTrue(describer.submit(b"\xff\xd8first", observed_at=time.time(), event_id="first"))
            self.assertTrue(describer.submit(b"\xff\xd8second", observed_at=time.time(), event_id="second"))
            deadline = time.time() + 5.0
            while time.time() < deadline:
                observation = describer.poll()
                if observation is not None and observation.event_id == "second":
                    break
                time.sleep(0.02)
            else:
                self.fail("second observation was not produced")
        finally:
            describer.stop()
        state = describer.state()
        self.assertEqual(state["errors"], 0)

    def test_restart_after_stop_timeout_revives_blocked_worker(self):
        entered_transport = Event()
        release_transport = Event()
        calls_lock = Lock()
        calls = 0

        def transport(payload):
            nonlocal calls
            with calls_lock:
                calls += 1
                call = calls
            if call == 1:
                entered_transport.set()
                if not release_transport.wait(3.0):
                    raise TimeoutError("test transport was not released")
            return (f"Frame {call} is visible.", False)

        describer = QwenEventDescriber("http://127.0.0.1:1", transport=transport)
        describer.start()
        try:
            self.assertTrue(describer.submit(b"first", event_id="first"))
            self.assertTrue(entered_transport.wait(1.0))
            describer.stop(timeout=0.01)
            self.assertTrue(describer.state()["running"])

            # start() while the old transport is still blocked must clear the
            # stop request; it must not launch a second concurrent worker.
            old_thread = describer._thread
            describer.start()
            self.assertIs(describer._thread, old_thread)
            release_transport.set()
            first = self._wait(describer)
            self.assertEqual(first.event_id, "first")

            self.assertTrue(describer.submit(b"second", event_id="second"))
            deadline = time.time() + 2.0
            while time.time() < deadline:
                observation = describer.poll()
                if observation is not None and observation.event_id == "second":
                    break
                time.sleep(0.01)
            else:
                self.fail("revived worker did not process the second frame")
            self.assertTrue(describer.state()["running"])
            self.assertEqual(calls, 2)
        finally:
            release_transport.set()
            describer.stop(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
