import sys
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.streaming_asr import StreamingASRBridge  # noqa: E402
from jawl_voicecompanion.voice_capture import VoiceCaptureLease  # noqa: E402


class StreamingASRBridgeTests(unittest.TestCase):
    def _bridge(self):
        return StreamingASRBridge("missing-crispasr.exe", "missing-model.gguf")

    def test_disabled_when_executable_missing(self):
        bridge = self._bridge()
        self.assertFalse(bridge._ensure_started())
        self.assertTrue(bridge.disabled)
        # feed() must stay a silent no-op once failed
        bridge.feed(b"\x00\x00" * 160)

    def test_partial_and_silence_state(self):
        bridge = self._bridge()
        bridge.fed_seconds = 3.0
        bridge._apply_event({"type": "partial", "text": "Привет, я думаю", "t1": 2.0})
        snap = bridge.snapshot()
        self.assertEqual(snap["text"], "Привет, я думаю")
        self.assertGreaterEqual(snap["silence_ms"], 900.0)
        bridge._apply_event({"type": "silence"})
        self.assertGreaterEqual(bridge.snapshot()["silence_ms"], 900.0)

    def test_reset_clears_partial(self):
        bridge = self._bridge()
        bridge.fed_seconds = 2.0
        bridge._apply_event({"type": "partial", "text": "тест", "t1": 1.0})
        bridge.reset_utterance()
        snap = bridge.snapshot()
        self.assertEqual(snap["text"], "")
        self.assertEqual(snap["silence_ms"], 0.0)

    def test_downmix_and_resample(self):
        import numpy as np
        stereo_48k = np.zeros(4800 * 2, dtype="<i2")
        stereo_48k[::2] = 1000
        out = StreamingASRBridge._to_mono16k(stereo_48k.tobytes(), 48000, 2)
        mono = np.frombuffer(out, dtype="<i2")
        self.assertEqual(len(mono), 1600)
        self.assertTrue((mono == 500).all())


class StreamingASRChildTests(unittest.TestCase):
    """Actual cheap children/pipes; no model, microphone or external runtime."""

    def setUp(self):
        self.children = []
        self.bridge = StreamingASRBridge("fixture-crispasr", "fixture-model")
        from jawl_voicecompanion.owned_pipe import spawn_owned_pipe
        original = spawn_owned_pipe
        self.mode = "echo"
        def spawn(_command, **kwargs):
            if self.children:
                self.assertIsNotNone(self.children[-1].poll(), "handoff overlapped native children")
            code = {
                "echo": "import sys,json\nwhile sys.stdin.buffer.read(320):\n print(json.dumps({'type':'partial','text':'fixture speech','t1':0}),flush=True)\n",
                "blocked": "import time; time.sleep(30)",
                "oversize": "import sys,time; sys.stdout.buffer.write(b'x'*65537); sys.stdout.buffer.flush(); time.sleep(30)",
            }[self.mode]
            child = original([sys.executable, "-u", "-c", code], **kwargs)
            self.children.append(child)
            return child
        self.patcher = patch("jawl_voicecompanion.streaming_asr.spawn_owned_pipe", side_effect=spawn)
        self.patcher.start()

    def tearDown(self):
        self.bridge.close()
        self.patcher.stop()
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
        self.assertIsNone(self.bridge._process)

    def until(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("bounded child condition did not become true")
            threading.Event().wait(0.005)

    def feed(self, scope="capture:A", session="A:0", cancel=None):
        return self.bridge.feed(b"\x01\x00" * 160, scope_id=scope, session_id=session, cancel_event=cancel)

    def test_capture_handoff_reaps_child_and_ignores_old_reader_events(self):
        self.assertTrue(self.feed())
        self.until(lambda: bool(self.bridge.snapshot()["text"]))
        old = self.bridge._run
        self.assertTrue(self.feed("capture:B", "B:0"))
        self.assertIsNotNone(old.process.poll())
        current = self.bridge._run
        self.bridge._apply_event({"type": "partial", "text": "late old speech"}, old)
        self.assertNotEqual(self.bridge.snapshot()["text"], "late old speech")
        self.assertFalse(self.bridge.snapshot(scope_id="capture:A", session_id="A:0")["active"])
        self.assertEqual(self.bridge.snapshot(scope_id="capture:A", session_id="A:0")["text"], "")
        self.bridge.discard_scope("capture:A")
        self.bridge.reset_utterance(scope_id="capture:B", session_id="B:older")
        self.assertIs(self.bridge._run, current)
        self.assertIsNone(current.process.poll())
        self.assertFalse(self.bridge.disabled)

    def test_new_utterance_of_same_capture_cannot_receive_previous_context(self):
        self.feed()
        old = self.bridge._run
        self.feed(session="A:1")
        self.assertIsNotNone(old.process.poll())
        self.assertEqual(self.bridge.snapshot()["session_id"], "A:1")
        self.assertGreater(self.bridge._run.generation, old.generation)

    def test_cancel_event_reaps_child_and_clears_partial_without_ui_poll(self):
        cancel = threading.Event()
        self.feed(cancel=cancel)
        self.until(lambda: bool(self.bridge.snapshot()["text"]))
        child = self.bridge._process
        cancel.set()
        self.until(lambda: self.bridge._process is None)
        self.assertIsNotNone(child.poll())
        self.assertEqual(self.bridge.snapshot()["text"], "")
        self.assertFalse(self.feed(cancel=cancel))
        self.assertEqual(len(self.children), 1)

    def test_capture_deadline_reaps_without_another_request(self):
        lease = VoiceCaptureLease()
        lease.acquire("desktop", "A")
        cancel = lease.authorize_stream({"owner": "desktop", "capture_id": "A"})
        self.feed(cancel=cancel)
        child = self.bridge._process
        cancel.expires_at = time.monotonic() + 0.05
        self.until(lambda: self.bridge._process is None)
        self.assertTrue(cancel.is_set())
        self.assertIsNotNone(child.poll())

    def test_full_pipe_does_not_block_http_feed_and_overflow_is_fail_closed(self):
        self.mode = "blocked"
        payload = b"\x00\x00" * (24 * 1024)
        self.assertTrue(self.bridge.feed(payload))
        self.until(lambda: self.bridge._run.audio.empty())  # Writer is blocked in its owned pipe.
        started = time.monotonic()
        for _ in range(10):
            if not self.bridge.feed(payload):
                break
        else:
            self.fail("bounded queue failed to reject overload")
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(self.bridge.disabled)
        self.assertIsNotNone(self.children[0].poll())
        self.assertEqual(self.bridge.snapshot()["text"], "")

    def test_oversized_stdout_line_terminates_only_owned_child(self):
        self.mode = "oversize"
        self.feed()
        self.until(lambda: self.bridge.disabled and self.bridge._process is None)
        self.assertIsNotNone(self.children[0].poll())
        self.assertEqual(self.bridge.snapshot()["text"], "")

    def test_idle_reap_is_not_a_permanent_failure_and_close_is_terminal(self):
        self.feed()
        self.bridge.idle_seconds = 0.05  # Shorten timer only in this fixture.
        self.until(lambda: self.bridge._process is None)
        self.assertFalse(self.bridge.disabled)
        self.bridge.idle_seconds = 45
        self.assertTrue(self.feed(session="A:1"))
        self.bridge.close()
        self.bridge.close()
        self.assertFalse(self.feed(session="A:2"))
        self.assertEqual(len(self.children), 2)

    def test_invalid_audio_and_precancelled_identity_never_spawn(self):
        for payload, rate, channels in ((b"",16000,1),(b"x",16000,1),(b"xx",0,1),
                                        (b"xx",True,1),(b"xx",16000,3),(b"xx"*25000,16000,1)):
            with self.assertRaises(ValueError):
                self.bridge.feed(payload, rate, channels)
        event = threading.Event()
        event.set()
        self.assertFalse(self.feed(cancel=event))
        self.assertEqual(self.children, [])

    def test_bad_event_shape_numbers_and_text_do_not_poison_snapshot(self):
        self.feed()
        self.until(lambda: bool(self.bridge.snapshot()["text"]))
        run = self.bridge._run
        for event in ([], None, {"type":"partial","text":"x"*4001},
                      {"type":"partial","text":{}}, {"type":"partial","text":"bad","t1":float("nan")},
                      {"type":"partial","text":"bad","t1":10**400},
                      {"type":"final","text":"bad","utterance_id":True}):
            self.bridge._apply_event(event, run)
        self.assertEqual(self.bridge.snapshot()["text"], "fixture speech")

    def test_spawn_failure_is_resettable_but_does_not_create_retry_loop(self):
        with patch("jawl_voicecompanion.streaming_asr.spawn_owned_pipe", side_effect=OSError("fixture")) as spawn:
            self.assertFalse(self.feed())
            self.assertFalse(self.feed())
            self.assertEqual(spawn.call_count, 1)
        self.bridge.reset_utterance()
        self.assertTrue(self.feed())

    def test_reap_failure_retains_owned_child_and_rejects_replacement(self):
        self.feed()
        child, run = self.bridge._process, self.bridge._run
        with patch.object(child, "terminate"), patch.object(child, "kill"), patch.object(
                child, "wait", side_effect=subprocess.TimeoutExpired("fixture", 0.5)):
            self.bridge.reset_utterance(scope_id="capture:A")
            self.assertIs(self.bridge._process, child)
            self.assertIs(self.bridge._run, run)
            self.assertTrue(self.bridge.disabled)
            self.assertFalse(self.feed("capture:B", "B:0"))
            self.assertEqual(len(self.children), 1)
        self.bridge.close()
        self.assertIsNotNone(child.poll())

    def test_thread_start_failure_reaps_the_just_created_child(self):
        with patch("jawl_voicecompanion.streaming_asr.threading.Thread.start",
                   side_effect=RuntimeError("fixture thread creation failed")):
            self.assertFalse(self.feed())
        self.assertTrue(self.bridge.disabled)
        self.assertIsNone(self.bridge._process)
        self.assertIsNotNone(self.children[0].poll())

    def test_actual_http_buffer_bridge_and_child_preserve_capture_boundary(self):
        import base64
        import json
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        from jawl_voicecompanion.asr import UtteranceBuffer
        from jawl_voicecompanion.gateway import TextGateway
        from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient
        from jawl_voicecompanion.web import create_server

        class VoiceMemFixture(VoiceMemProcessClient):
            def __init__(inner): pass
            def close(inner): pass
        server = create_server(port=0, gateway=TextGateway(),
                               frontend_dir=Path(__file__).parents[1] / "frontend",
                               voice_mem=VoiceMemFixture(),
                               streaming_asr=self.bridge)
        server.asr = UtteranceBuffer()
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        serving.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def request(path, payload):
            req = Request(base + path, json.dumps(payload).encode(), {
                "Content-Type":"application/json", "X-Companion-Session":server.session_token,
                "X-Companion-CSRF":server.csrf_token,
            })
            try:
                response = urlopen(req, timeout=2)
            except HTTPError as exc:
                response = exc
            with response:
                return response.status, json.loads(response.read())
        def capture(action, identity):
            return request("/api/voice/capture", {"action":action,"owner":"desktop","capture_id":identity})
        def audio(identity):
            return {"owner":"desktop","capture_id":identity,"session_id":identity+":0",
                    "pcm16_base64":base64.b64encode(b"\x01\x00"*160).decode()}
        try:
            self.assertEqual(capture("acquire", "A")[0], 200)
            self.assertEqual(request("/api/voice/audio", audio("A"))[0], 200)
            self.until(lambda: request("/api/voice/draft",audio("A"))[1]["draft"] == "fixture speech")
            old = self.bridge._run
            self.assertEqual(request("/api/voice/draft",audio("B"))[0], 409)
            self.assertEqual(capture("release", "A")[0], 200)
            self.assertIsNotNone(old.process.poll())
            self.assertEqual(capture("acquire", "B")[0], 200)
            self.assertEqual(request("/api/voice/draft",audio("B"))[1]["draft"], "")
            self.assertEqual(request("/api/voice/audio",audio("B"))[0], 200)
            self.until(lambda: request("/api/voice/draft",audio("B"))[1]["draft"] == "fixture speech")
            current = self.bridge._run
            self.assertEqual(request("/api/voice/end",audio("A"))[0], 409)
            self.bridge._apply_event({"type":"partial","text":"old leaked speech"}, old)
            self.assertIs(self.bridge._run, current)
            self.assertEqual(request("/api/voice/draft",audio("B"))[1]["draft"], "fixture speech")
            self.assertEqual(capture("release", "B")[0], 200)
            self.assertIsNotNone(current.process.poll())
        finally:
            server.shutdown()
            serving.join(2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
