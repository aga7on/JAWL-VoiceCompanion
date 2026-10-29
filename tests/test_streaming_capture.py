import base64
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402
from jawl_voicecompanion.voice_capture import CaptureLeaseError  # noqa: E402


class _StreamingBridge:
    """Scope-aware bridge double; requests still pass through the real HTTP server."""

    def __init__(self):
        self.states = {}
        self.feeds = []
        self.resets = []
        self.discards = []
        self.lock = threading.Lock()

    @staticmethod
    def _key(scope_id, session_id):
        return scope_id, session_id

    def feed(self, pcm16, sample_rate=16000, channels=1, *, scope_id="legacy", session_id="legacy", cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            return
        with self.lock:
            key = self._key(scope_id, session_id)
            self.feeds.append((pcm16, sample_rate, channels, scope_id, session_id))
            previous = self.states.get(key, {})
            self.states[key] = {
                "active": True, "text": previous.get("text", ""),
                "final_text": previous.get("final_text", ""),
                "silence_ms": previous.get("silence_ms", 0.0),
            }

    def snapshot(self, *, scope_id=None, session_id=None):
        with self.lock:
            if scope_id is None or session_id is None:
                return {"active": False, "text": "", "final_text": "", "silence_ms": 0.0}
            return dict(self.states.get(self._key(scope_id, session_id), {
                "active": False, "text": "", "final_text": "", "silence_ms": 0.0,
            }))

    def reset_utterance(self, *, scope_id=None, session_id=None):
        with self.lock:
            key = self._key(scope_id, session_id)
            self.resets.append(key)
            self.states[key] = {"active": False, "text": "", "final_text": "", "silence_ms": 0.0}

    def discard_scope(self, scope_id):
        with self.lock:
            self.discards.append(scope_id)
            for key in list(self.states):
                if key[0] == scope_id:
                    del self.states[key]
        return {"status": "discarded", "scope_id": scope_id}

    def close(self):
        pass

    def publish(self, scope_id, session_id, text, *, active=True, silence_ms=0.0):
        with self.lock:
            self.states[(scope_id, session_id)] = {
                "active": active, "text": text, "final_text": "", "silence_ms": silence_ms,
            }


class _VoiceMem(VoiceMemProcessClient):
    def __init__(self):
        self.feeds = []
        self.turns = []

    def feed_audio(self, pcm16, *, sample_rate, session_id):
        self.feeds.append((pcm16, sample_rate, session_id))
        return []

    def end_audio(self, *, session_id):
        self.turns.append(session_id)
        return []

    def close(self):
        pass


class _CanonicalASR:
    def __init__(self):
        self.feeds = []
        self.discards = []
        self.finish_started = None
        self.finish_continue = None

    def feed_audio(self, pcm16, *, sample_rate, channels, session_id, scope_id, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            raise ValueError("ASR capture is cancelled")
        if not pcm16 or len(pcm16) % 2 or sample_rate <= 0 or channels <= 0:
            raise ValueError("invalid canonical PCM")
        self.feeds.append((pcm16, sample_rate, channels, session_id, scope_id))
        return {"status": "buffered", "bytes": len(pcm16)}

    def finish(self, session_id, *, scope_id):
        if self.finish_started is not None:
            self.finish_started.set()
            self.finish_continue.wait(3)
        return {"status": "transcribed", "text": "a valid spoken request"}

    def discard_scope(self, scope_id):
        self.discards.append(scope_id)
        return {"status": "discarded", "scope_id": scope_id}

    def close(self):
        pass


class StreamingCaptureHttpTests(unittest.TestCase):
    def setUp(self):
        self.streaming = _StreamingBridge()
        self.voice_mem = _VoiceMem()
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            voice_mem=self.voice_mem,
            streaming_asr=self.streaming,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, payload, *, expect_error=False):
        req = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            if not expect_error:
                raise
            response = exc
        with response:
            return response.status, json.loads(response.read().decode("utf-8"))

    @staticmethod
    def audio(**extra):
        return {
            "pcm16_base64": base64.b64encode(b"\x00\x00" * 160).decode("ascii"),
            "sample_rate": 16000,
            "channels": 1,
            "session_id": "session-a",
            **extra,
        }

    def acquire(self, capture_id, owner="desktop"):
        return self.request("/api/voice/capture", {
            "action": "acquire", "owner": owner, "capture_id": capture_id,
        })

    def test_active_capture_mismatch_is_rejected_before_any_asr_feed(self):
        self.server.asr = _CanonicalASR()
        self.acquire("current")
        status, body = self.request("/api/voice/audio", self.audio(capture_id="other"), expect_error=True)
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "capture_busy")
        self.assertEqual(self.server.asr.feeds, [])
        self.assertEqual(self.streaming.feeds, [])

    def test_correct_capture_feeds_scoped_session_and_draft_is_filtered(self):
        self.server.asr = _CanonicalASR()
        self.acquire("capture-a")
        self.streaming.publish("capture:capture-a", "session-a", "hello from this capture")
        self.streaming.publish("capture:old", "session-a", "stale transcript")
        status, _ = self.request("/api/voice/audio", self.audio(capture_id="capture-a"))
        self.assertEqual(status, 200)
        self.assertEqual(self.streaming.feeds[-1][3:], ("capture:capture-a", "session-a"))
        _, draft = self.request("/api/voice/draft", {"capture_id": "capture-a", "session_id": "session-a"})
        self.assertEqual(draft["draft"], "hello from this capture")
        _, other = self.request("/api/voice/draft", {"capture_id": "capture-a", "session_id": "another-session"})
        self.assertEqual(other["draft"], "")
        self.assertNotIn("stale transcript", json.dumps(draft))

    def test_draft_reports_barge_in_actions_while_assistant_speaks(self):
        self.server.asr = _CanonicalASR()
        self.acquire("capture-a")
        self.streaming.publish("capture:capture-a", "session-a", "Стой, подожди")
        _, stop = self.request("/api/voice/draft", {
            "capture_id": "capture-a", "session_id": "session-a", "assistant_speaking": True,
        })
        self.assertEqual(stop["duplex_action"], "cancel_tts")
        self.streaming.publish("capture:capture-a", "session-a", "угу")
        _, nod = self.request("/api/voice/draft", {
            "capture_id": "capture-a", "session_id": "session-a", "assistant_speaking": True,
        })
        self.assertEqual(nod["duplex_action"], "ignore_backchannel")
        self.assertEqual(nod["avatar_gesture"], "nod")
        self.assertGreaterEqual(nod["required_ms"], 380)

    def test_draft_and_preface_authorize_capture_without_creating_turns(self):
        self.acquire("owned")
        for path in ("/api/voice/draft", "/api/voice/preface"):
            status, body = self.request(path, {
                "capture_id": "wrong", "session_id": "session-a",
            }, expect_error=True)
            self.assertEqual(status, 409)
            self.assertEqual(body["error"], "capture_busy")
        self.assertEqual(self.voice_mem.turns, [])

    def test_release_discards_only_its_streaming_scope(self):
        self.server.asr = _CanonicalASR()
        self.acquire("release-me")
        self.streaming.publish("capture:release-me", "session-a", "owned")
        self.streaming.publish("capture:ambient-peer", "session-a", "keep")
        _, result = self.request("/api/voice/capture", {
            "action": "release", "owner": "desktop", "capture_id": "release-me",
        })
        self.assertEqual(result["streaming_asr"]["scope_id"], "capture:release-me")
        self.assertEqual(self.streaming.discards, ["capture:release-me"])
        self.assertEqual(self.streaming.snapshot(scope_id="capture:ambient-peer", session_id="session-a")["text"], "keep")

    def test_late_cancelled_chunk_never_reaches_streaming_bridge(self):
        canonical = _CanonicalASR()
        self.server.asr = canonical
        self.acquire("late")
        entered, resume = threading.Event(), threading.Event()
        original = canonical.feed_audio

        def delayed(*args, **kwargs):
            entered.set()
            resume.wait(2)
            return original(*args, **kwargs)

        canonical.feed_audio = delayed
        results = []
        worker = threading.Thread(target=lambda: results.append(self.request(
            "/api/voice/audio", self.audio(capture_id="late"), expect_error=True,
        )))
        worker.start()
        self.assertTrue(entered.wait(1))
        self.request("/api/voice/capture", {"action": "release", "owner": "desktop", "capture_id": "late"})
        resume.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0][0], 400)
        self.assertEqual(self.streaming.feeds, [])

    def test_invalid_pcm_is_rejected_before_streaming_feed(self):
        self.server.asr = _CanonicalASR()
        bad = self.audio()
        bad["pcm16_base64"] = base64.b64encode(b"\x00").decode("ascii")
        status, _ = self.request("/api/voice/audio", bad, expect_error=True)
        self.assertEqual(status, 400)
        self.assertEqual(self.streaming.feeds, [])

    def test_old_final_and_reset_cannot_clear_replacement_capture(self):
        canonical = _CanonicalASR()
        self.server.asr = canonical
        self.acquire("old")
        canonical.finish_started, canonical.finish_continue = threading.Event(), threading.Event()
        self.streaming.publish("capture:old", "session-a", "old partial")
        self.streaming.publish("capture:new", "session-a", "replacement partial")
        results = []
        old_final = threading.Thread(target=lambda: results.append(self.request(
            "/api/voice/end", {"capture_id": "old", "session_id": "session-a"}, expect_error=True,
        )))
        old_final.start()
        self.assertTrue(canonical.finish_started.wait(1))
        self.request("/api/voice/capture", {"action": "release", "owner": "desktop", "capture_id": "old"})
        self.acquire("new")
        canonical.finish_continue.set()
        old_final.join(2)
        self.assertFalse(old_final.is_alive())
        self.assertEqual(results[0][1]["status"], "cancelled")
        self.assertEqual(self.streaming.snapshot(scope_id="capture:new", session_id="session-a")["text"], "replacement partial")
        self.assertNotIn(("capture:new", "session-a"), self.streaming.resets)

        class Connection:
            def send_text(self, _text):
                pass

        # A stale reset is rejected by capture authorization and cannot reach the replacement scope.
        with self.assertRaises(CaptureLeaseError):
            handler = self._handler()
            handler.server = self.server
            handler._handle_ws_action(Connection(), {"action": "voice_reset", "capture_id": "old", "session_id": "session-a"})
        self.assertEqual(self.streaming.snapshot(scope_id="capture:new", session_id="session-a")["text"], "replacement partial")

    def _handler(self):
        from jawl_voicecompanion.web import CompanionRequestHandler

        return CompanionRequestHandler.__new__(CompanionRequestHandler)

    def test_legacy_unclaimed_audio_keeps_default_scope(self):
        self.server.asr = _CanonicalASR()
        status, _ = self.request("/api/voice/audio", self.audio())
        self.assertEqual(status, 200)
        self.assertEqual(self.streaming.feeds[-1][3:], ("voice:legacy", "session-a"))

    def test_canonical_backchannel_is_consumed_without_dispatch_or_memory_write(self):
        from jawl_voicecompanion.web import CompanionRequestHandler

        self.server.asr = _CanonicalASR()
        self.server.asr.finish = Mock(return_value={"status": "transcribed", "text": "Угу, понятно."})
        self.acquire("owned")
        self.streaming.publish("capture:owned", "session-a", "provisional")
        self.streaming.publish("capture:peer", "session-a", "keep")
        with patch.object(CompanionRequestHandler, "_external_asr_events") as dispatch:
            status, result = self.request("/api/voice/end", {
                "capture_id": "owned", "session_id": "session-a", "suppress_backchannel": True,
            })
        self.assertEqual(status, 200)
        self.assertEqual(result["filtered"], "user_backchannel")
        self.assertEqual(result["responses"], [])
        self.assertEqual(result["transcript"], "")
        dispatch.assert_not_called()
        self.server.asr.finish.assert_called_once_with("session-a", scope_id="capture:owned")
        self.assertIn(("capture:owned", "session-a"), self.streaming.resets)
        self.assertEqual(self.streaming.snapshot(scope_id="capture:peer", session_id="session-a")["text"], "keep")
        self.assertEqual(self.voice_mem.turns, [])

    def test_backchannel_filter_requires_explicit_overlap_and_canonical_acknowledgement(self):
        from jawl_voicecompanion.web import CompanionRequestHandler

        self.server.asr = _CanonicalASR()
        self.server.voice_mem_async = None
        self.acquire("owned")
        for text, suppress in (("Стоп", True), ("Открой браузер", True), ("Да?", True), ("Ага", False), ("Ага", "true")):
            with self.subTest(text=text, suppress=suppress):
                self.server.asr.finish = Mock(return_value={"status": "transcribed", "text": text})
                with patch.object(CompanionRequestHandler, "_external_asr_events", return_value=[]) as dispatch:
                    _, result = self.request("/api/voice/end", {
                        "capture_id": "owned", "session_id": "session-a", "suppress_backchannel": suppress,
                    })
                self.assertEqual(result["transcript"], text)
                self.assertNotIn("filtered", result)
                dispatch.assert_called_once()

    def test_release_during_snapshot_drops_inflight_draft_and_preface(self):
        for path, field in (("/api/voice/draft", "draft"), ("/api/voice/preface", "text")):
            with self.subTest(path=path):
                identity = "during-snapshot-" + field
                self.acquire(identity)
                self.streaming.publish("capture:" + identity, "session-a", "Что сейчас на экране?")
                snapshot = self.streaming.snapshot
                def releasing_snapshot(**kwargs):
                    result = snapshot(**kwargs)
                    self.server.voice_capture.release("desktop", identity)
                    return result
                self.streaming.snapshot = releasing_snapshot
                try:
                    status, result = self.request(path, {"capture_id":identity, "session_id":"session-a"})
                    self.assertEqual(status, 200)
                    self.assertEqual(result[field], "")
                    self.assertEqual(result["status"], "cancelled")
                    self.assertEqual(self.voice_mem.turns, [])
                finally:
                    self.streaming.snapshot = snapshot


if __name__ == "__main__":
    unittest.main()
