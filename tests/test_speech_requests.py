import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.speech_requests import SpeechRequests, validate_speech_request_id
from jawl_voicecompanion.tts import TTSCancelled, TTSService
from jawl_voicecompanion.resources import ResourceGovernor
from jawl_voicecompanion.web import create_server


class SpeechRequestTests(unittest.TestCase):
    def test_ids_are_strict_and_never_truncated(self):
        for value in (None, "", 1, "a" * 129, "a b", "../a", "а", "a\n", []):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_speech_request_id(value)
        self.assertEqual(validate_speech_request_id("speech-123_A"), "speech-123_A")

    def test_cancel_before_begin_and_completed_replay_never_revive(self):
        registry = SpeechRequests()
        cancelled = registry.cancel("before")
        self.assertIs(registry.begin("before"), cancelled)
        self.assertTrue(cancelled.is_set())
        completed = registry.begin("finished")
        registry.finish(completed)
        self.assertIs(registry.begin("finished"), completed)
        self.assertTrue(completed.is_set())

    def test_duplicate_active_is_rejected_without_cancelling_owner(self):
        registry = SpeechRequests()
        owner = registry.begin("same")
        with self.assertRaises(ValueError):
            registry.begin("same")
        self.assertFalse(owner.is_set())
        registry.cancel("same")
        with self.assertRaises(ValueError):
            registry.begin("same")

    def test_cancel_one_id_does_not_change_another(self):
        registry = SpeechRequests()
        old = registry.begin("old")
        current = registry.begin("current")
        self.assertIs(registry.cancel("old"), old)
        self.assertTrue(old.is_set())
        self.assertFalse(current.is_set())

    def test_bounded_ttl_does_not_expire_active_or_evict_cancel_tombstones(self):
        now = [10.0]
        registry = SpeechRequests(limit=2, ttl_seconds=5, clock=lambda: now[0])
        active = registry.begin("active")
        registry.cancel("cancelled")
        with self.assertRaises(RuntimeError):
            registry.begin("overflow")
        with self.assertRaises(RuntimeError):
            registry.cancel("overflow")
        now[0] += 6
        registry.begin("new")
        self.assertFalse(active.is_set())
        with self.assertRaises(ValueError):
            registry.begin("active")

    def test_late_finish_cannot_change_reused_id_after_ttl(self):
        now = [0.0]
        registry = SpeechRequests(limit=1, ttl_seconds=1, clock=lambda: now[0])
        old = registry.begin("same")
        registry.finish(old)
        now[0] = 2
        new = registry.begin("same")
        registry.finish(old)
        self.assertFalse(new.is_set())

    def test_cancel_between_registration_and_activation_releases_admission(self):
        service = TTSService(CooperativeProvider(), governor=ResourceGovernor())
        now = [0.0]
        service._requests = SpeechRequests(limit=1, ttl_seconds=1, clock=lambda: now[0])
        acquire = service.governor.try_acquire

        def cancel_at_admission(kind):
            result = acquire(kind)
            service.cancel(request_id="racing")
            return result

        service.governor.try_acquire = cancel_at_admission
        with self.assertRaises(TTSCancelled):
            list(service.stream("Test.", request_id="racing"))
        self.assertEqual(service.governor.state()["active"], {})
        self.assertIsNone(service._active)
        now[0] = 2
        self.assertFalse(service._requests.begin("next").is_set())


class CooperativeProvider:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.tokens = []
        self.targeted = []

    def stream_synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
        self.tokens.append(cancel_event)
        self.entered.set()
        while not self.release.wait(0.01):
            if cancel_event.is_set():
                raise TTSCancelled()
        if cancel_event.is_set():
            raise TTSCancelled()
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x01\x00" * 160)
        yield output.getvalue()

    def cancel_generation(self, token):
        self.targeted.append(token)

    def cancel(self):
        for token in self.tokens:
            token.set()


class SpeechCancellationHTTPTests(unittest.TestCase):
    """Real HTTP handler + real TTSService/governor, no model or microphone."""

    def setUp(self):
        self.provider = CooperativeProvider()
        self.service = TTSService(self.provider)
        self.server = create_server(port=0, tts_service=self.service)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {"Content-Type": "application/json",
                        "X-Companion-Session": self.server.session_token,
                        "X-Companion-CSRF": self.server.csrf_token}
        self.readers = []

    def tearDown(self):
        self.provider.release.set()
        self.service.cancel()
        for reader in self.readers:
            reader.join(2)
            self.assertFalse(reader.is_alive())
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.assertFalse(self.thread.is_alive())

    def request(self, path, payload, *, authenticated=True):
        return Request(self.base + path, data=json.dumps(payload).encode(),
                       headers=self.headers if authenticated else {"Content-Type": "application/json"},
                       method="POST")

    def post(self, path, payload, **kwargs):
        with urlopen(self.request(path, payload, **kwargs), timeout=2) as response:
            return json.loads(response.read())

    def start_stream(self, request_id):
        outcome = []
        def read():
            try:
                with urlopen(self.request("/api/tts/stream", {"text": "Test.", "request_id": request_id}),
                             timeout=2) as response:
                    outcome.extend(json.loads(line) for line in response.read().splitlines())
            except Exception as exc:
                outcome.append(exc)
        reader = threading.Thread(target=read, daemon=True)
        self.readers.append(reader)
        reader.start()
        return reader, outcome

    def test_cancel_before_first_chunk_releases_actual_service_slot(self):
        reader, outcome = self.start_stream("first")
        self.assertTrue(self.provider.entered.wait(1))
        self.assertEqual(self.server.resources.state()["active"], {"speech": 1})
        started = time.monotonic()
        self.post("/api/tts/cancel", {"request_id": "first"})
        reader.join(1)
        self.assertFalse(reader.is_alive())
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(outcome, [{"type": "cancelled"}])
        self.assertEqual(self.server.resources.state()["active"], {})

    def test_cancel_can_arrive_before_stream_http_request(self):
        self.post("/api/tts/cancel", {"request_id": "early"})
        reader, outcome = self.start_stream("early")
        reader.join(1)
        self.assertFalse(reader.is_alive())
        self.assertEqual(outcome, [{"type": "cancelled"}])
        self.assertFalse(self.provider.entered.is_set())
        self.assertEqual(self.server.resources.state()["active"], {})

    def test_late_old_cancel_does_not_interrupt_replacement(self):
        old, old_outcome = self.start_stream("old")
        self.assertTrue(self.provider.entered.wait(1))
        self.post("/api/tts/cancel", {"request_id": "old"})
        old.join(1)
        self.assertEqual(old_outcome, [{"type": "cancelled"}])
        self.provider.entered.clear()
        new, new_outcome = self.start_stream("new")
        self.assertTrue(self.provider.entered.wait(1))
        new_token = self.provider.tokens[-1]
        self.post("/api/tts/cancel", {"request_id": "old"})
        self.assertFalse(new_token.is_set())
        self.assertTrue(new.is_alive())
        self.provider.release.set()
        new.join(1)
        self.assertFalse(new.is_alive())
        self.assertEqual([event["type"] for event in new_outcome], ["audio", "done"])

    def test_scoped_cancel_requires_auth_and_invalid_id_is_not_global(self):
        reader, outcome = self.start_stream("owner")
        self.assertTrue(self.provider.entered.wait(1))
        for payload, authenticated, status in (({"request_id": "owner"}, False, 403),
                                                ({"request_id": None}, True, 400),
                                                ({"request_id": ""}, True, 400)):
            with self.subTest(payload=payload, authenticated=authenticated):
                with self.assertRaises(HTTPError) as context:
                    self.post("/api/tts/cancel", payload, authenticated=authenticated)
                self.assertEqual(context.exception.code, status)
                context.exception.close()
                self.assertFalse(self.provider.tokens[-1].is_set())
        self.post("/api/tts/cancel", {})
        reader.join(1)
        self.assertEqual(outcome, [{"type": "cancelled"}])

    def test_invalid_stream_id_is_rejected_before_starting_provider(self):
        with self.assertRaises(HTTPError) as context:
            self.post("/api/tts/stream", {"text": "Test.", "request_id": None})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()
        self.assertFalse(self.provider.entered.is_set())

    def test_completed_stream_replay_is_dropped_not_regenerated(self):
        self.provider.release.set()
        first, outcome = self.start_stream("completed")
        first.join(1)
        self.assertEqual([event["type"] for event in outcome], ["audio", "done"])
        replay, replay_outcome = self.start_stream("completed")
        replay.join(1)
        self.assertFalse(replay.is_alive())
        self.assertEqual(replay_outcome, [{"type": "cancelled"}])
        self.assertEqual(len(self.provider.tokens), 1)


if __name__ == "__main__":
    unittest.main()
