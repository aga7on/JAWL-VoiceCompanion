from __future__ import annotations

import unittest

from jawl_voicecompanion.duplex_cascade import StreamPhraseSegmenter
from jawl_voicecompanion.turn_trace import (
    STAGE_AUDIO_PLAYBACK_START,
    STAGE_LLM_FIRST_SENTENCE,
    STAGE_USER_SPEECH_END,
    compute_turn_kpis,
)


class StreamPhraseSegmenterTests(unittest.TestCase):
    def test_progressive_punctuation_splitting(self):
        segmenter = StreamPhraseSegmenter(min_chars=10, min_words=3)
        tokens = ["Привет, ", "я ", "твой ", "голосовой ", "помощник. ", "Чем ", "могу ", "помочь?"]

        collected: list[str] = []
        for tok in tokens:
            phrases = segmenter.feed(tok)
            collected.extend(phrases)

        # Flush any trailing tokens
        collected.extend(segmenter.flush())

        self.assertEqual(len(collected), 2)
        self.assertEqual(collected[0], "Привет, я твой голосовой помощник.")
        self.assertEqual(collected[1], "Чем могу помочь?")

    def test_newline_boundary_triggers_split(self):
        segmenter = StreamPhraseSegmenter(min_chars=12, min_words=3)
        phrases = segmenter.feed("Вот первый пункт списки.\nВторой пункт.")
        self.assertIn("Вот первый пункт списки.", phrases)
        remaining = segmenter.flush()
        self.assertEqual(remaining, ["Второй пункт."])

    def test_question_and_exclamation_split_even_short(self):
        segmenter = StreamPhraseSegmenter(min_chars=12, min_words=3)
        phrases = segmenter.feed("Да! ")
        self.assertEqual(phrases, ["Да!"])

        phrases = segmenter.feed("Слушаю? ")
        self.assertEqual(phrases, ["Слушаю?"])

    def test_flush_returns_unpunctuated_remainder(self):
        segmenter = StreamPhraseSegmenter(min_chars=12, min_words=3)
        segmenter.feed("Это не законченное")
        segmenter.feed(" предложение")
        remainder = segmenter.flush()
        self.assertEqual(remainder, ["Это не законченное предложение"])

    def test_empty_feed_and_empty_flush(self):
        segmenter = StreamPhraseSegmenter()
        self.assertEqual(segmenter.feed(""), [])
        self.assertEqual(segmenter.flush(), [])
        segmenter.reset()
        self.assertEqual(segmenter.buffer, "")


class DualLaneTraceInteractionTests(unittest.TestCase):
    def test_fast_lane_vs_slow_lane_kpi_accounting(self):
        """When Fast Lane is active, audible latency reflects fast lane preface,
        while meaningful latency reflects the first slow lane phrase."""
        trace_records = [
            {"stage": STAGE_USER_SPEECH_END, "wall_ts": 10.0, "detail": None},
            # Fast lane preface arrives quickly
            {
                "stage": STAGE_AUDIO_PLAYBACK_START,
                "wall_ts": 10.35,
                "detail": {"lane": "fast", "is_preface": True},
            },
            # LLM finishes first sentence
            {
                "stage": STAGE_LLM_FIRST_SENTENCE,
                "wall_ts": 10.82,
                "detail": {"phrase": "Первая фраза ответа Bonsai."},
            },
            # Slow lane TTS starts playing
            {
                "stage": STAGE_AUDIO_PLAYBACK_START,
                "wall_ts": 11.05,
                "detail": {"lane": "slow"},
            },
        ]
        kpis = compute_turn_kpis(trace_records)
        self.assertEqual(kpis["audible_latency_s"], 0.35)
        self.assertEqual(kpis["meaningful_latency_s"], 1.05)
        self.assertEqual(kpis["first_sentence_latency_s"], 0.82)

    def test_stream_first_alone_when_fast_lane_disabled(self):
        """When Fast Lane is disabled (Stream-First alone), audible and meaningful latency
        are identical and both measure slow lane first chunk."""
        trace_records = [
            {"stage": STAGE_USER_SPEECH_END, "wall_ts": 20.0, "detail": None},
            {
                "stage": STAGE_LLM_FIRST_SENTENCE,
                "wall_ts": 20.75,
                "detail": {"phrase": "Готово, вот что получилось."},
            },
            {
                "stage": STAGE_AUDIO_PLAYBACK_START,
                "wall_ts": 20.95,
                "detail": {"lane": "slow"},
            },
        ]
        kpis = compute_turn_kpis(trace_records)
        self.assertEqual(kpis["audible_latency_s"], 0.95)
        self.assertEqual(kpis["meaningful_latency_s"], 0.95)
        self.assertEqual(kpis["first_sentence_latency_s"], 0.75)


if __name__ == "__main__":
    unittest.main()
