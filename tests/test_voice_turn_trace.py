from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jawl_voicecompanion.turn_trace import (
    ALL_STAGES,
    STAGE_AUDIO_ENQUEUED,
    STAGE_AUDIO_PLAYBACK_END,
    STAGE_AUDIO_PLAYBACK_START,
    STAGE_AUDIO_STOPPED,
    STAGE_ASR_FINAL,
    STAGE_BARGE_IN_DETECTED,
    STAGE_LLM_FIRST_SENTENCE,
    STAGE_LLM_FIRST_TOKEN,
    STAGE_LLM_REQUEST,
    STAGE_TTS_FIRST_PCM,
    STAGE_TTS_REQUEST,
    STAGE_USER_SPEECH_END,
    STAGE_VAD_ENDPOINT,
    TurnTracer,
    compute_turn_kpis,
)


class TurnTraceConstantsTests(unittest.TestCase):
    def test_all_canonical_stages_defined(self):
        expected_stages = [
            STAGE_USER_SPEECH_END,
            STAGE_VAD_ENDPOINT,
            STAGE_ASR_FINAL,
            STAGE_LLM_REQUEST,
            STAGE_LLM_FIRST_TOKEN,
            STAGE_LLM_FIRST_SENTENCE,
            STAGE_TTS_REQUEST,
            STAGE_TTS_FIRST_PCM,
            STAGE_AUDIO_ENQUEUED,
            STAGE_AUDIO_PLAYBACK_START,
            STAGE_AUDIO_PLAYBACK_END,
            STAGE_BARGE_IN_DETECTED,
            STAGE_AUDIO_STOPPED,
        ]
        for stage in expected_stages:
            self.assertTrue(stage.startswith("t_"), f"{stage} must start with 't_'")
            self.assertIn(stage, ALL_STAGES)


class ComputeTurnKpisTests(unittest.TestCase):
    def test_empty_records_return_none(self):
        kpis = compute_turn_kpis([])
        self.assertIsNone(kpis["audible_latency_s"])
        self.assertIsNone(kpis["meaningful_latency_s"])
        self.assertIsNone(kpis["barge_in_stop_duration_s"])
        self.assertIsNone(kpis["first_sentence_latency_s"])

    def test_dual_lane_kpis_distinguishes_audible_and_meaningful(self):
        records = [
            {"stage": STAGE_USER_SPEECH_END, "wall_ts": 100.0, "detail": None},
            {"stage": STAGE_LLM_REQUEST, "wall_ts": 100.1, "detail": None},
            {"stage": STAGE_AUDIO_PLAYBACK_START, "wall_ts": 100.4, "detail": {"lane": "fast", "is_preface": True}},
            {"stage": STAGE_LLM_FIRST_TOKEN, "wall_ts": 100.5, "detail": None},
            {"stage": STAGE_LLM_FIRST_SENTENCE, "wall_ts": 100.85, "detail": {"phrase": "Первая фраза."}},
            {"stage": STAGE_TTS_REQUEST, "wall_ts": 100.86, "detail": None},
            {"stage": STAGE_TTS_FIRST_PCM, "wall_ts": 101.1, "detail": None},
            {"stage": STAGE_AUDIO_PLAYBACK_START, "wall_ts": 101.2, "detail": {"lane": "slow"}},
        ]
        kpis = compute_turn_kpis(records)
        self.assertEqual(kpis["audible_latency_s"], 0.4)
        self.assertEqual(kpis["meaningful_latency_s"], 1.2)
        self.assertEqual(kpis["first_sentence_latency_s"], 0.85)

    def test_fallback_to_vad_endpoint_if_user_speech_end_missing(self):
        records = [
            {"stage": STAGE_VAD_ENDPOINT, "wall_ts": 50.0, "detail": None},
            {"stage": STAGE_AUDIO_PLAYBACK_START, "wall_ts": 51.15, "detail": None},
        ]
        kpis = compute_turn_kpis(records)
        self.assertEqual(kpis["audible_latency_s"], 1.15)
        self.assertEqual(kpis["meaningful_latency_s"], 1.15)

    def test_barge_in_stop_duration_calculation(self):
        records = [
            {"stage": STAGE_USER_SPEECH_END, "wall_ts": 10.0, "detail": None},
            {"stage": STAGE_AUDIO_PLAYBACK_START, "wall_ts": 10.8, "detail": None},
            {"stage": STAGE_BARGE_IN_DETECTED, "wall_ts": 11.2, "detail": {"reason": "user_barge_in"}},
            {"stage": STAGE_AUDIO_STOPPED, "wall_ts": 11.38, "detail": {"muted": True}},
        ]
        kpis = compute_turn_kpis(records)
        self.assertEqual(kpis["barge_in_stop_duration_s"], 0.18)
        self.assertLessEqual(kpis["barge_in_stop_duration_s"], 0.3)


class TurnTracerLifecycleTests(unittest.TestCase):
    def test_tracer_write_read_summary_and_kpis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = TurnTracer(Path(tmpdir), max_traces=10)
            trace_id = "trace-test-123"

            tracer.mark(trace_id, STAGE_USER_SPEECH_END, wall_ts=10.0)
            tracer.mark(trace_id, STAGE_LLM_REQUEST, wall_ts=10.1)
            tracer.mark(trace_id, STAGE_LLM_FIRST_SENTENCE, wall_ts=10.7)
            tracer.mark(trace_id, STAGE_AUDIO_PLAYBACK_START, wall_ts=10.9)
            tracer.mark(trace_id, STAGE_BARGE_IN_DETECTED, wall_ts=11.5)
            tracer.mark(trace_id, STAGE_AUDIO_STOPPED, wall_ts=11.65)

            records = tracer.read(trace_id)
            self.assertEqual(len(records), 6)
            self.assertEqual(records[0]["stage"], STAGE_USER_SPEECH_END)

            summary = tracer.summary(trace_id)
            self.assertEqual(summary["trace_id"], trace_id)
            self.assertEqual(summary["marks"], 6)
            self.assertEqual(len(summary["gaps"]), 5)

            self.assertEqual(tracer.audible_latency(trace_id), 0.9)
            self.assertEqual(tracer.meaningful_latency(trace_id), 0.9)
            self.assertEqual(tracer.barge_in_stop_duration(trace_id), 0.15)

            tracer.close()

    def test_tracer_max_traces_rotation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracer = TurnTracer(Path(tmpdir), max_traces=4)
            for i in range(8):
                tracer.mark(f"trace-{i}", STAGE_USER_SPEECH_END, wall_ts=10.0 + i)

            # Files beyond max_traces should be purged
            files = list(Path(tmpdir).glob("*.jsonl"))
            self.assertLessEqual(len(files), 4)
            tracer.close()
