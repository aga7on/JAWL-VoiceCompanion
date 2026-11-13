"""Regression: one failed sentence must not silence the rest of the reply.

Owner symptom (2026-11-09): TTS played only the first sentence up to the dot.
``LiveSpeechSession._run`` broke the worker loop on any synthesis error, so a
transient TTS failure after sentence 1 dropped every remaining sentence
without any surfaced error.  The gate side is also frozen here: a streamed
envelope emits every sentence, not just the first.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.live_speech import LiveSpeechSession  # noqa: E402
from jawl_voicecompanion.speech_first import SpeechFirstGate  # noqa: E402
from jawl_voicecompanion.tts import TTSCancelled  # noqa: E402

ENVELOPE = {
    "observation": "Пользователь попросил объяснить.",
    "reasoning": "Отвечу тремя предложениями.",
    "actions": [
        {
            "tool_name": "HostTerminalMessages.send_message_to_terminal",
            "parameters": {
                "text": "Первое предложение готово. Второе предложение в пути! Третье предложение также здесь?"
            },
        }
    ],
}
REPLY = ENVELOPE["actions"][0]["parameters"]["text"]


class _FailingAfterFirstTTS:
    """Synthesizes normally except one transient failure on sentence 2."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, **_kwargs: object) -> bytes:
        self.calls.append(text)
        if "Второе" in text:
            raise RuntimeError("omnivoice transient 500")
        return b"RIFF" + b"\x00" * 8


class _GoodTTS:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, **_kwargs: object) -> bytes:
        self.calls.append(text)
        return b"RIFF" + b"\x00" * 8


class SpeechGateContinuityTests(unittest.TestCase):
    """The tee source emits every sentence from the streamed envelope."""

    def test_streamed_envelope_emits_all_sentences(self) -> None:
        gate = SpeechFirstGate()
        emitted: list[str] = []
        # Drip the envelope byte-wise, like llama-server chunks do.
        blob = json.dumps(ENVELOPE, ensure_ascii=False)
        step = 7
        for i in range(0, len(blob), step):
            piece = gate.feed(blob[i : i + step])
            if piece:
                emitted.append(piece)
        emitted.append(gate.flush())
        spoken = "".join(emitted).replace(" ", " ")
        self.assertIn("Первое", spoken)
        self.assertIn("Второе", spoken)
        self.assertIn("Третье", spoken)
        self.assertGreaterEqual(len([e for e in emitted if e.strip()]), 3)
        self.assertEqual(gate.pending_text, "")


class LiveSpeechResilienceTests(unittest.TestCase):
    def _run_session(self, tts: object, sentences: list[str]) -> tuple[list[bytes], dict[str, object]]:
        audio: list[bytes] = []
        session = LiveSpeechSession(tts, mode="text", on_audio=audio.append)
        session.start()
        for sentence in sentences:
            session.feed(sentence)
        session.finish("")
        session.drain_all(limit_seconds=5.0)
        return audio, session.state()

    def test_failed_sentence_does_not_drop_following_sentences(self) -> None:
        tts = _FailingAfterFirstTTS()
        audio, state = self._run_session(
            tts,
            ["Первое предложение готово.", "Второе предложение в пути!", "Третье предложение также здесь?"],
        )
        self.assertEqual(
            len(audio),
            2,
            "sentences after a failed synthesis must still be spoken",
        )
        self.assertTrue(str(state.get("error") or "").strip())
        self.assertEqual(len(tts.calls), 3)

    def test_guard_cancellation_still_stops_remaining_sentences(self) -> None:
        class CancellingTTS(_GoodTTS):
            def synthesize(self, text: str, **kwargs: object) -> bytes:
                if "Второе" in text:
                    raise TTSCancelled("cancelled")
                return super().synthesize(text, **kwargs)

        audio, state = self._run_session(
            CancellingTTS(),
            ["Первое предложение готово.", "Второе предложение в пути!", "Третье предложение также здесь?"],
        )
        self.assertEqual(len(audio), 1)
        self.assertTrue(state.get("cancelled"))

    def test_all_sentences_pass_through_when_tts_is_healthy(self) -> None:
        tts = _GoodTTS()
        audio, _state = self._run_session(
            tts,
            ["Первое предложение готово.", "Второе предложение в пути!", "Третье предложение также здесь?"],
        )
        self.assertEqual(len(audio), 3)
        self.assertEqual(len(tts.calls), 3)


if __name__ == "__main__":
    unittest.main()
