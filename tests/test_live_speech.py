"""Tests for the live (speech-first) TTS session."""
from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.live_speech import LiveSpeechSession  # noqa: E402

REPLY = "Привет! Как у тебя дела? Я рядом и слушаю."
ENVELOPE = json.dumps(
    {
        "observation": "пользователь поздоровался",
        "reasoning": "отвечу коротко",
        "actions": [
            {
                "tool_name": "HostTerminalMessages.send_message_to_terminal",
                "parameters": {"text": REPLY},
            }
        ],
    },
    ensure_ascii=False,
)


class _FakeTTS:
    """Minimal TTS double: returns a WAV-shaped blob per sentence."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self.call_event = threading.Event()

    def synthesize(self, text, *, voice=None, speed=1.0, emotion=None, request_id=None):
        with self._lock:
            self.calls.append(text)
            self.call_event.set()
        if self.delay:
            time.sleep(self.delay)
        return b"RIFF" + text.encode("utf-8")


class LiveSpeechTextModeTests(unittest.TestCase):
    def test_first_sentence_is_synthesized_before_the_rest_arrives(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts).start()
        try:
            session.feed("Привет! Как у тебя дела")
            self.assertTrue(
                tts.call_event.wait(2.0), "first sentence was not synthesized early"
            )
            with tts._lock:
                self.assertEqual(tts.calls[0], "Привет!")
            session.feed("? Я рядом и слушаю.")
            session.finish()
            audio = list(session.audio())
        finally:
            session.cancel()
        self.assertTrue(audio)
        self.assertEqual(tts.calls[0], "Привет!")

    def test_all_sentences_are_spoken_in_order(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts).start()
        try:
            for index in range(0, len(REPLY), 5):
                session.feed(REPLY[index : index + 5])
            # Spoken plus pending reconstructs the reply byte for byte.
            self.assertEqual(session.spoken_text + session.pending_text, REPLY)
            session.finish()
            list(session.audio())
        finally:
            session.cancel()
        with tts._lock:
            calls = list(tts.calls)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], "Привет!")
        self.assertTrue(calls[-1].endswith("слушаю."))
        self.assertEqual(session.spoken_text, REPLY)

    def test_finish_flushes_the_tail_without_a_boundary(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts).start()
        try:
            session.feed("Готов начать")
            ready = session.finish()
            self.assertEqual(ready, ["Готов начать"])
            list(session.audio())
        finally:
            session.cancel()
        with tts._lock:
            self.assertEqual(tts.calls, ["Готов начать"])

    def test_cancel_stops_the_session(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts).start()
        session.feed("Привет!")
        session.cancel()
        state = session.state()
        self.assertTrue(state["cancelled"])
        self.assertFalse(state["finished"])

    def test_cancel_aborts_the_in_flight_tts_request(self):
        class _BlockingTTS(_FakeTTS):
            def __init__(self):
                super().__init__()
                self.started = threading.Event()
                self.release = threading.Event()
                self.cancelled: list[str | None] = []

            def synthesize(self, text, *, voice=None, speed=1.0, emotion=None, request_id=None):
                self.started.set()
                self.release.wait(2.0)
                return b"RIFFlate"

            def cancel(self, *, request_id=None):
                self.cancelled.append(request_id)
                self.release.set()

        tts = _BlockingTTS()
        emitted: list[bytes] = []
        session = LiveSpeechSession(tts, request_id="turn-42", on_audio=emitted.append).start()
        session.feed("Привет!")
        self.assertTrue(tts.started.wait(2.0))
        session.cancel()
        self.assertTrue(tts.release.wait(2.0))
        time.sleep(0.1)
        state = session.state()
        self.assertEqual(tts.cancelled, ["turn-42"])
        self.assertEqual(emitted, [])
        self.assertEqual(state["audio_chunks"], 0)
        self.assertTrue(state["cancelled"])
        self.assertEqual(state["error"], "")

    def test_generated_request_id_is_used_when_the_caller_has_none(self):
        class _CapturingTTS(_FakeTTS):
            def __init__(self):
                super().__init__()
                self.request_ids: list[str | None] = []
                self.cancelled: list[str | None] = []

            def synthesize(self, text, *, voice=None, speed=1.0, emotion=None, request_id=None):
                self.request_ids.append(request_id)
                return super().synthesize(text, voice=voice, speed=speed, emotion=emotion,
                                           request_id=request_id)

            def cancel(self, *, request_id=None):
                self.cancelled.append(request_id)

        tts = _CapturingTTS()
        session = LiveSpeechSession(tts).start()
        try:
            session.feed("Привет!")
            session.finish("Привет!")
            list(session.audio())
        finally:
            session.cancel()
        self.assertTrue(tts.request_ids[0].startswith("live-"))
        self.assertEqual(tts.cancelled, tts.request_ids[:1])


class LiveSpeechEnvelopeModeTests(unittest.TestCase):
    def test_envelope_stream_speaks_only_the_reply(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts, mode="envelope").start()
        try:
            for index in range(0, len(ENVELOPE), 7):
                session.feed(ENVELOPE[index : index + 7])
            session.finish(REPLY)
            list(session.audio())
        finally:
            session.cancel()
        with tts._lock:
            calls = list(tts.calls)
        joined = "".join(calls)
        self.assertIn("Привет!", joined)
        self.assertNotIn("пользователь поздоровался", joined)
        self.assertNotIn("отвечу коротко", joined)

    def test_envelope_mode_speaks_before_the_json_closes(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts, mode="envelope").start()
        try:
            partial = ENVELOPE[: ENVELOPE.index("Я рядом") + 4]
            session.feed(partial)
            self.assertTrue(
                tts.call_event.wait(2.0), "reply was not spoken before the JSON closed"
            )
            with tts._lock:
                self.assertEqual(tts.calls[0], "Привет!")
        finally:
            session.cancel()


class LiveSpeechStateTests(unittest.TestCase):
    def test_state_reports_bounded_counters(self):
        tts = _FakeTTS()
        session = LiveSpeechSession(tts).start()
        try:
            session.feed("Привет! Как дела?")
            session.finish()
            list(session.audio())
            state = session.state()
        finally:
            session.cancel()
        self.assertEqual(state["mode"], "text")
        self.assertGreaterEqual(state["sentences"], 1)
        self.assertTrue(state["finished"])
        self.assertEqual(state["error"], "")

    def test_session_requires_tts(self):
        with self.assertRaises(ValueError):
            LiveSpeechSession(None)

    def test_session_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            LiveSpeechSession(_FakeTTS(), mode="psychic")


if __name__ == "__main__":
    unittest.main()
