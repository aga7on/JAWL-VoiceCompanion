"""Tests for the speech-first (D2-01) incremental reply extractor."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.speech_first import (  # noqa: E402
    SpeechFirstGate,
    extract_speech_text,
    first_speakable_chunk,
    looks_like_reply_action,
)

ENVELOPE = {
    "observation": "Пользователь поздоровался.",
    "reasoning": "Отвечу коротко и по-русски.",
    "actions": [
        {
            "tool_name": "HostTerminalMessages.send_message_to_terminal",
            "parameters": {"text": "Привет! Как у тебя дела? Я рядом."},
        }
    ],
}
REPLY = ENVELOPE["actions"][0]["parameters"]["text"]
SERIALIZED = json.dumps(ENVELOPE, ensure_ascii=False)


class ExtractSpeechTextTests(unittest.TestCase):
    def test_extracts_reply_from_full_envelope(self):
        text, complete, is_reply = extract_speech_text(SERIALIZED)
        self.assertTrue(is_reply)
        self.assertTrue(complete)
        self.assertEqual(text, REPLY)

    def test_never_reads_private_observation_or_reasoning(self):
        buffer = '{"observation":"секретное наблюдение","reasoning":"скрытая мысль","actions":['
        text, _complete, is_reply = extract_speech_text(buffer)
        self.assertFalse(is_reply)
        self.assertEqual(text, "")

    def test_detects_reply_action(self):
        self.assertTrue(looks_like_reply_action(SERIALIZED))
        self.assertFalse(looks_like_reply_action('{"actions":[]}'))

    def test_truncated_escape_is_dropped(self):
        buffer = '{"actions":[{"tool_name":"HostTerminalMessages.send_message_to_terminal","parameters":{"text":"Привет \\u0'
        text, complete, is_reply = extract_speech_text(buffer)
        self.assertTrue(is_reply)
        self.assertFalse(complete)
        self.assertEqual(text, "Привет ")

    def test_escaped_quotes_and_newlines(self):
        raw = '{"actions":[{"tool_name":"HostTerminalMessages.send_message_to_terminal","parameters":{"text":"Он сказал: \\"привет\\"\\nвторая строка."}}]}'
        text, complete, is_reply = extract_speech_text(raw)
        self.assertTrue(is_reply)
        self.assertTrue(complete)
        self.assertEqual(text, 'Он сказал: "привет"\nвторая строка.')


class FirstSpeakableChunkTests(unittest.TestCase):
    def test_returns_first_sentence(self):
        chunk = first_speakable_chunk("Привет! Как у тебя дела? Я рядом.")
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.text, "Привет!")

    def test_waits_for_sentence_boundary(self):
        self.assertIsNone(first_speakable_chunk("Привет, как у тебя"))

    def test_abbreviation_is_not_a_boundary(self):
        chunk = first_speakable_chunk("Всё т.е. нормально и работает.")
        self.assertIsNotNone(chunk)
        self.assertTrue(chunk.text.endswith("работает."))

    def test_long_clause_is_spoken_before_the_ending(self):
        text = "Это очень длинная фраза без знаков конца которая продолжается и продолжается дальше"
        chunk = first_speakable_chunk(text, long_clause_chars=40)
        self.assertIsNotNone(chunk)
        self.assertFalse(chunk.complete)

    def test_short_complete_sentence_is_spoken(self):
        chunk = first_speakable_chunk("Да.")
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.text, "Да.")

    def test_word_without_ending_is_not_spoken(self):
        self.assertIsNone(first_speakable_chunk("Да"))


class SpeechFirstGateTests(unittest.TestCase):
    def test_gate_speaks_first_sentence_before_json_is_closed(self):
        gate = SpeechFirstGate()
        spoken: list[str] = []
        for index in range(0, len(SERIALIZED), 7):
            chunk = gate.feed(SERIALIZED[index : index + 7])
            if chunk:
                spoken.append(chunk)
        self.assertTrue(spoken, "gate produced no speech")
        self.assertEqual(spoken[0], "Привет!")
        self.assertTrue(
            "".join(spoken).startswith("Привет!"),
            "spoken text is not a prefix of the reply",
        )

    def test_gate_never_speaks_before_reply_is_identified(self):
        gate = SpeechFirstGate()
        self.assertIsNone(gate.feed('{"observation":"секрет","reasoning":"мысль"'))
        self.assertIsNone(gate.feed('"actions":[{"tool_name":"HostTerminalMessages'))

    def test_finalize_returns_only_unspoken_tail(self):
        gate = SpeechFirstGate()
        for index in range(0, len(SERIALIZED), 7):
            gate.feed(SERIALIZED[index : index + 7])
        tail, mismatch = gate.finalize(REPLY)
        self.assertFalse(mismatch)
        self.assertFalse(tail.startswith("Привет!"))
        self.assertEqual(REPLY[: gate.spoken_chars] + tail, REPLY)

    def test_finalize_without_speech_returns_everything(self):
        gate = SpeechFirstGate()
        tail, mismatch = gate.finalize(REPLY)
        self.assertFalse(mismatch)
        self.assertEqual(tail, REPLY)

    def test_diverged_stream_is_reported(self):
        gate = SpeechFirstGate()
        gate.feed('{"actions":[{"tool_name":"HostTerminalMessages.send_message_to_terminal","parameters":{"text":"Привет!"}}]}')
        tail, mismatch = gate.finalize("Совсем другой ответ.")
        self.assertTrue(mismatch)
        self.assertEqual(tail, "Совсем другой ответ.")

    def test_byte_by_byte_stream_never_loses_or_duplicates_text(self):
        gate = SpeechFirstGate()
        spoken = "".join(filter(None, (gate.feed(char) for char in SERIALIZED)))
        tail, mismatch = gate.finalize(REPLY)
        self.assertFalse(mismatch)
        self.assertEqual(spoken + tail, REPLY)

    def test_state_is_bounded_and_informative(self):
        gate = SpeechFirstGate()
        gate.feed(SERIALIZED)
        state = gate.state()
        self.assertTrue(state["reply_detected"])
        self.assertGreaterEqual(state["extracted_chars"], 0)
        self.assertGreaterEqual(state["buffered_chars"], 0)


if __name__ == "__main__":
    unittest.main()
