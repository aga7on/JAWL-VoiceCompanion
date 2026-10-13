"""Speech leases track provider calls, not the lifetime of HTTP consumers."""

import io
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.resources import ResourceGovernor
from jawl_voicecompanion.tts import TTSCancelled, TTSService, TTSUnavailable


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * 160)
    return output.getvalue()


class ControlledProvider:
    def __init__(self, *, cooperative=False):
        self.cooperative = cooperative
        self.entered = {key: threading.Event() for key in ("A.", "B.", "C.", "D.")}
        self.release = {key: threading.Event() for key in self.entered}
        self.tokens = {}
        self.lock = threading.Lock()
        self.calls = 0
        self.maximum = 0

    def synthesize(self, text, *, cancel_event=None, **_kwargs):
        with self.lock:
            self.calls += 1
            self.maximum = max(self.maximum, self.calls)
            self.tokens[text] = cancel_event
            self.entered[text].set()
        try:
            while not self.release[text].wait(0.005):
                if self.cooperative and cancel_event.is_set():
                    raise TTSCancelled()
            return wav_bytes()
        finally:
            with self.lock:
                self.calls -= 1

    def cancel_generation(self, token):
        token.set()  # Deliberately cannot force an uncooperative call to return.

    def unblock(self):
        for released in self.release.values():
            released.set()


class SpeechAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.provider = ControlledProvider()
        self.governor = ResourceGovernor()
        self.service = TTSService(self.provider, self.governor, replacement_timeout_seconds=0.4)
        self.threads = []

    def tearDown(self):
        self.provider.unblock()
        self.service.close()
        for thread in self.threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.until(lambda: not self.service._leases)
        self.assertEqual(self.governor.state()["active"], {})

    def until(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("bounded condition did not become true")
            threading.Event().wait(0.005)

    def begin(self, text, *, stream=False, request_id=None):
        outcome = []
        def run():
            try:
                call = self.service.stream if stream else self.service.synthesize
                value = call(text, request_id=request_id or text[0])
                outcome.append(list(value) if stream else value)
            except Exception as exc:
                outcome.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread, outcome

    def latest_is(self, request_id):
        with self.service._lock, self.service._requests._lock:
            entry = self.service._requests._entries.get(request_id)
            return entry is not None and self.service._latest is entry[0]

    def test_replacement_cancels_before_waiting_for_actual_provider_return(self):
        self.provider.cooperative = True
        old, old_result = self.begin("A.")
        self.assertTrue(self.provider.entered["A."].wait(1))
        self.provider.release["B."].set()
        new, new_result = self.begin("B.")
        old.join(1)
        new.join(1)
        self.assertIsInstance(old_result[0], TTSCancelled)
        self.assertEqual(new_result, [wav_bytes()])
        self.assertEqual(self.provider.maximum, 1)

    def test_consumer_cancel_keeps_slot_until_uncooperative_call_returns(self):
        old, result = self.begin("A.", stream=True)
        self.assertTrue(self.provider.entered["A."].wait(1))
        self.service.cancel(request_id="A")
        old.join(1)
        self.assertFalse(old.is_alive())
        self.assertIsInstance(result[0], TTSCancelled)
        self.assertEqual(self.governor.state()["active"], {"speech": 1})
        with self.assertRaises(TTSUnavailable):
            self.service.synthesize("B.", request_id="B")
        self.assertFalse(self.provider.entered["B."].is_set())
        self.provider.release["A."].set()
        self.until(lambda: not self.governor.state()["active"])
        self.provider.release["C."].set()
        self.assertEqual(self.service.synthesize("C.", request_id="C"), wav_bytes())
        self.assertEqual(self.provider.maximum, 1)

    def test_paused_audio_consumer_does_not_block_new_computation_or_release_it_late(self):
        self.provider.release["A."].set()
        old = self.service.stream("A.", request_id="A")
        self.addCleanup(old.close)
        self.assertEqual(next(old), wav_bytes())
        new, result = self.begin("B.")
        self.assertTrue(self.provider.entered["B."].wait(1))
        old.close()
        self.assertFalse(self.provider.tokens["B."].is_set())
        self.assertEqual(self.governor.state()["active"], {"speech": 1})
        self.provider.release["B."].set()
        new.join(1)
        self.assertEqual(result, [wav_bytes()])

    def test_rapid_replacements_never_publish_the_superseded_waiter(self):
        self.service._replacement_timeout = 2
        old, _ = self.begin("A.")
        self.assertTrue(self.provider.entered["A."].wait(1))
        middle, middle_result = self.begin("B.")
        self.until(lambda: self.latest_is("B"))
        newest, newest_result = self.begin("C.")
        self.until(lambda: self.latest_is("C"))
        middle.join(1)
        self.assertFalse(middle.is_alive())
        self.assertIsInstance(middle_result[0], TTSCancelled)
        self.assertFalse(self.provider.entered["B."].is_set())
        self.provider.release["A."].set()
        old.join(1)
        self.assertTrue(self.provider.entered["C."].wait(1))
        self.service.cancel(request_id="B")
        self.assertFalse(self.provider.tokens["C."].is_set())
        self.provider.release["C."].set()
        newest.join(1)
        self.assertEqual(newest_result, [wav_bytes()])
        self.assertEqual(self.provider.maximum, 1)

    def test_scoped_cancel_of_waiter_does_not_admit_it_later(self):
        old, _ = self.begin("A.")
        self.assertTrue(self.provider.entered["A."].wait(1))
        waiting, result = self.begin("B.")
        self.until(lambda: self.latest_is("B"))
        self.service.cancel(request_id="B")
        waiting.join(1)
        self.assertIsInstance(result[0], TTSCancelled)
        self.provider.release["A."].set()
        old.join(1)
        self.assertFalse(self.provider.entered["B."].is_set())

    def test_close_wakes_waiters_rejects_new_work_but_does_not_fake_resource_release(self):
        old, _ = self.begin("A.")
        self.assertTrue(self.provider.entered["A."].wait(1))
        waiting, result = self.begin("B.")
        self.until(lambda: self.latest_is("B"))
        self.service.close()
        self.service.close()
        waiting.join(1)
        self.assertIsInstance(result[0], TTSCancelled)
        self.assertEqual(self.service.health()["status"], "closed")
        self.assertEqual(self.governor.state()["active"], {"speech": 1})
        with self.assertRaises(TTSUnavailable):
            self.service.synthesize("C.", request_id="C")
        self.provider.release["A."].set()
        old.join(1)

    def test_external_governor_owner_is_not_stolen_on_busy_timeout(self):
        self.assertTrue(self.governor.try_acquire("speech"))
        try:
            with self.assertRaises(TTSUnavailable):
                self.service.synthesize("A.")
            self.assertEqual(self.governor.state()["active"], {"speech": 1})
            self.assertFalse(self.provider.entered["A."].is_set())
        finally:
            self.governor.release("speech")

    def test_governor_cannot_be_replaced_under_an_active_lease(self):
        active, _ = self.begin("A.")
        self.assertTrue(self.provider.entered["A."].wait(1))
        with self.assertRaises(TTSUnavailable):
            self.service.set_governor(ResourceGovernor())
        self.provider.release["A."].set()
        active.join(1)
        self.service.set_governor(None)

    def test_early_cancelled_replay_does_not_supersede_live_owner(self):
        self.service.cancel(request_id="B")
        active, result = self.begin("A.")
        self.assertTrue(self.provider.entered["A."].wait(1))
        with self.assertRaises(TTSCancelled):
            self.service.synthesize("B.", request_id="B")
        self.assertFalse(self.provider.tokens["A."].is_set())
        self.provider.release["A."].set()
        active.join(1)
        self.assertEqual(result, [wav_bytes()])

    def test_provider_timeout_error_is_not_confused_with_future_poll_timeout(self):
        with patch.object(self.provider, "synthesize", side_effect=TimeoutError("provider timeout")):
            with self.assertRaisesRegex(TimeoutError, "provider timeout"):
                list(self.service.stream("A.", request_id="A"))

    def test_pool_construction_failure_releases_its_lease(self):
        with patch("jawl_voicecompanion.tts.ThreadPoolExecutor", side_effect=RuntimeError("setup failed")):
            with self.assertRaisesRegex(RuntimeError, "setup failed"):
                list(self.service.stream("A.", request_id="A"))
        self.assertEqual(self.governor.state()["active"], {})
        self.assertIsNone(self.service._active)

    def test_partial_submit_failure_keeps_slot_until_started_call_returns(self):
        from concurrent.futures import ThreadPoolExecutor
        real_pool = ThreadPoolExecutor(max_workers=1)
        submit = real_pool.submit
        submitted = [0]
        def fail_second(*args, **kwargs):
            submitted[0] += 1
            if submitted[0] == 2:
                self.assertTrue(self.provider.entered["A."].wait(1))
                raise RuntimeError("submit failed")
            return submit(*args, **kwargs)
        real_pool.submit = fail_second
        with patch("jawl_voicecompanion.tts.ThreadPoolExecutor", return_value=real_pool):
            with self.assertRaisesRegex(RuntimeError, "submit failed"):
                list(self.service.stream("A. B.", request_id="A"))
        self.assertTrue(self.provider.tokens["A."].is_set())
        self.assertFalse(self.provider.entered["B."].is_set())
        self.assertEqual(self.governor.state()["active"], {"speech": 1})
        self.provider.release["A."].set()
        self.until(lambda: not self.governor.state()["active"])

    def test_native_iterator_is_closed_before_replacement_enters_and_not_closed_twice(self):
        closed = []
        class NativeProvider(ControlledProvider):
            def stream_synthesize(inner, text, **kwargs):
                try:
                    if text == "B.":
                        self.assertEqual(closed, ["A."])
                    yield inner.synthesize(text, **kwargs)
                finally:
                    closed.append(text)
        self.provider = NativeProvider()
        self.service.provider = self.provider
        self.provider.release["A."].set()
        old = self.service.stream("A.", request_id="A")
        self.addCleanup(old.close)
        self.assertEqual(next(old), wav_bytes())
        current, outcome = self.begin("B.", stream=True)
        self.assertTrue(self.provider.entered["B."].wait(1))
        self.assertEqual(closed, ["A."])
        old.close()
        self.assertEqual(closed, ["A."])
        self.assertEqual(self.governor.state()["active"], {"speech": 1})
        self.provider.release["B."].set()
        current.join(1)
        self.assertEqual(outcome, [[wav_bytes()]])
        self.assertEqual(closed, ["A.", "B."])

    def test_cancellation_during_native_factory_does_not_lose_iterator_cleanup(self):
        closed = []
        class NativeFactory(ControlledProvider):
            def stream_synthesize(inner, text, **kwargs):
                inner.synthesize(text, **kwargs)  # Blocking non-generator factory.
                class Iterator:
                    def __iter__(iterator): return iterator
                    def __next__(iterator): raise StopIteration
                    def close(iterator): closed.append(text)
                return Iterator()
        self.provider = NativeFactory()
        self.service.provider = self.provider
        active, outcome = self.begin("A.", stream=True)
        self.assertTrue(self.provider.entered["A."].wait(1))
        self.service.cancel(request_id="A")
        self.assertEqual(self.governor.state()["active"], {"speech": 1})
        self.provider.release["A."].set()
        active.join(1)
        self.assertIsInstance(outcome[0], TTSCancelled)
        self.assertEqual(closed, ["A."])

    def test_reentrant_native_iterator_cancel_releases_lease_exactly_once(self):
        closed = []
        class Iterator:
            def __iter__(inner): return inner
            def __next__(inner): return wav_bytes()
            def close(inner):
                closed.append(True)
                self.service.cancel(request_id="A")
        class NativeProvider:
            def stream_synthesize(inner, *_args, **_kwargs): return Iterator()
        self.service.provider = NativeProvider()
        old = self.service.stream("A.", request_id="A")
        self.addCleanup(old.close)
        next(old)
        self.service.cancel(request_id="A")
        old.close()
        self.assertEqual(closed, [True])
        self.assertEqual(self.governor.state()["active"], {})

    def test_planner_concurrency_is_bounded_across_cancelled_replies(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class Planner:
            timeout_seconds = 2
            def plan(inner, parts):
                calls.append(parts)
                entered.set()
                release.wait(2)
                return None
        self.service.prosody_planner = Planner()
        self.addCleanup(release.set)
        self.provider.unblock()
        old = self.service.stream("A. B.", request_id="A")
        self.addCleanup(old.close)
        next(old)
        self.assertTrue(entered.wait(1))
        old.close()
        newer = self.service.stream("C. D.", request_id="C")
        self.addCleanup(newer.close)
        next(newer)
        newer.close()
        self.assertEqual(len(calls), 1)
        release.set()

    def test_cancellation_does_not_wait_for_planner_network_timeout(self):
        entered, release = threading.Event(), threading.Event()
        class Planner:
            timeout_seconds = 2
            def plan(inner, _parts):
                entered.set()
                release.wait(2)
                return None
        self.service.prosody_planner = Planner()
        self.addCleanup(release.set)
        self.provider.unblock()
        stream = self.service.stream("A. B.", request_id="A")
        self.addCleanup(stream.close)
        next(stream)
        self.assertTrue(entered.wait(1))
        outcome = []
        def advance():
            try:
                outcome.append(next(stream))
            except Exception as exc:
                outcome.append(exc)
        thread = threading.Thread(target=advance, daemon=True)
        self.threads.append(thread)
        thread.start()
        self.service.cancel(request_id="A")
        thread.join(0.5)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcome[0], TTSCancelled)
        self.assertFalse(self.provider.entered["B."].is_set())
        release.set()


if __name__ == "__main__":
    unittest.main()
