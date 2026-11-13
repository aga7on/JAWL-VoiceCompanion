"""P1 barge-in/cancel contract (deterministic, no GPU/mic/network).

Covers server-side/session invariants for full-duplex barge-in:
- LiveSpeechSession.cancel() stops synthesis path, drains queues, marks
  cancelled+done, delivers no tail audio after cancel, and best-effort calls
  TTS cancel with the session request_id.
- A cancelled/finished session can be discarded and a fresh session (new
  request_id) proceeds normally (readiness for next turn).
- SpeechRequests invariants relevant to barge-in races: cancel-before-start
  tombstone blocks new work; active id reuse is rejected; explicit cancel
  marks active token.
- WS speak_cancel handler semantics (contract mirror): cancels current live
  speech session and clears the handler reference so the next speak starts
  clean.

Gaps (honest, not faked): real desktop playback stop, distributed
draft->client->server timing, echo/loopback acoustic races, and physical mic
E2E remain UNKNOWN/BLOCKED outside this deterministic scope.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.live_speech import LiveSpeechSession  # noqa: E402
from jawl_voicecompanion.speech_requests import SpeechRequests  # noqa: E402
from jawl_voicecompanion.tts import TTSCancelled  # noqa: E402


class _BlockingThenAudioTTS:
    """Blocks first synthesis until released; records cancel(request_id)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.cancelled: list[str | None] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def synthesize(self, text: str, *, request_id: str | None = None, **_kw) -> bytes:
        self.calls.append((text, request_id))
        self.started.set()
        if "block" in text:
            self.release.wait(timeout=5.0)
            # If cancel was requested, the service would normally raise; emulate
            # the cooperative contract the session relies on.
            if request_id in self.cancelled:
                raise TTSCancelled("cancelled")
        return b"RIFF" + b"\x00" * 24

    def cancel(self, *, request_id: str | None = None, **_kw) -> None:
        self.cancelled.append(request_id)
        self.release.set()


class _GoodTTS:
    def synthesize(self, text: str, **_kw) -> bytes:
        return b"RIFF" + b"\x00" * 24

    def cancel(self, **_kw) -> None:
        return None


class LiveSpeechBargeInTests(unittest.TestCase):
    def test_cancel_drains_state_marks_done_and_calls_tts_cancel(self) -> None:
        tts = _BlockingThenAudioTTS()
        cb_audio: list[bytes] = []
        session = LiveSpeechSession(
            tts, mode="text", request_id="barge-1", on_audio=cb_audio.append
        )
        session.start()
        session.feed("block this sentence.")
        self.assertTrue(tts.started.wait(timeout=3.0), "worker did not start synthesis")

        session.cancel()

        # Contract: cancelled+done, queues drained (no tail delivered).
        state = session.state()
        self.assertTrue(state.get("cancelled"))
        self.assertTrue(session.done)
        self.assertEqual(session.poll_audio(timeout=0.1), [])
        # Best-effort TTS cancel scoped to this request.
        self.assertIn("barge-1", tts.cancelled)
        # Audio callback must not deliver chunks after cancel.
        self.assertEqual(cb_audio, [])

    def test_next_turn_session_ready_after_barge_in(self) -> None:
        tts = _BlockingThenAudioTTS()
        first = LiveSpeechSession(tts, mode="text", request_id="barge-a")
        first.start()
        first.feed("block and interrupt.")
        self.assertTrue(tts.started.wait(timeout=3.0))
        first.cancel()
        self.assertTrue(first.done)
        self.assertTrue(first.state().get("cancelled"))

        # New request/session proceeds independently (no stale tail/state leak).
        good = _GoodTTS()
        audio: list[bytes] = []
        second = LiveSpeechSession(good, mode="text", request_id="barge-b", on_audio=audio.append)
        second.start()
        second.feed("Новый ответ после перебивания.")
        second.finish("")
        out = second.drain_all(limit_seconds=5.0)
        self.assertEqual(len(out), 1)
        self.assertFalse(second.state().get("cancelled"))
        self.assertIn(b"RIFF", out[0])

    def test_tts_cancelled_exception_stops_remaining_without_leak(self) -> None:
        class _CancelMid(_GoodTTS):
            def synthesize(self, text: str, **_kw) -> bytes:
                if "stop" in text:
                    raise TTSCancelled("barge")
                return super().synthesize(text, **_kw)

        audio: list[bytes] = []
        session = LiveSpeechSession(_CancelMid(), mode="text", on_audio=audio.append)
        session.start()
        session.feed("ok one.")
        session.feed("stop now.")
        session.feed("tail must not speak.")
        session.finish("")
        session.drain_all(limit_seconds=5.0)
        self.assertEqual(len(audio), 1)
        self.assertTrue(session.state().get("cancelled"))
        self.assertTrue(session.done)
        self.assertEqual(session.poll_audio(timeout=0.0), [])


class SpeechRequestsBargeInRaceTests(unittest.TestCase):
    def test_cancel_before_start_is_tombstone(self) -> None:
        req = SpeechRequests(limit=8, ttl_seconds=60.0)
        token = req.cancel("req-pre")
        self.assertTrue(token.is_set())
        begun = req.begin("req-pre")
        # Cancel-before-start / completed replay must not become new work.
        self.assertIs(begun, token)
        self.assertTrue(begun.is_set())

    def test_active_reuse_rejected_and_cancel_marks_active(self) -> None:
        req = SpeechRequests(limit=8, ttl_seconds=60.0)
        active = req.begin("req-live")
        self.assertFalse(active.is_set())
        with self.assertRaises(ValueError):
            req.begin("req-live")
        req.cancel("req-live")
        self.assertTrue(active.is_set())

    def test_finished_id_not_reusable_during_ttl(self) -> None:
        req = SpeechRequests(limit=8, ttl_seconds=60.0)
        token = req.begin("req-done")
        req.finish(token)
        self.assertTrue(token.is_set())
        replay = req.begin("req-done")
        self.assertIs(replay, token)


class WsSpeakCancelContractTests(unittest.TestCase):
    """Mirror of web.py:_handle_live_speech speak_cancel branch (5 lines)."""

    @staticmethod
    def _speak_cancel(handler: object) -> dict:
        session = getattr(handler, "_live_speech", None)
        if session is not None:
            session.cancel()
            handler._live_speech = None  # type: ignore[attr-defined]
        return {"type": "speech_cancelled"}

    def test_speak_cancel_clears_session_and_stops_audio(self) -> None:
        tts = _BlockingThenAudioTTS()
        session = LiveSpeechSession(tts, mode="text", request_id="ws-1")
        session.start()
        session.feed("block ws barge.")
        self.assertTrue(tts.started.wait(timeout=3.0))

        handler = type("H", (), {"_live_speech": session})()
        msg = self._speak_cancel(handler)

        self.assertEqual(msg["type"], "speech_cancelled")
        self.assertIsNone(handler._live_speech)
        self.assertTrue(session.done)
        self.assertTrue(session.state().get("cancelled"))
        self.assertEqual(session.poll_audio(timeout=0.1), [])

    def test_speak_cancel_without_session_is_safe(self) -> None:
        handler = type("H", (), {"_live_speech": None})()
        msg = self._speak_cancel(handler)
        self.assertEqual(msg, {"type": "speech_cancelled"})
        self.assertIsNone(handler._live_speech)


if __name__ == "__main__":
    unittest.main()
