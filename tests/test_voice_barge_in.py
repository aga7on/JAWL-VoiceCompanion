from __future__ import annotations

import unittest
from pathlib import Path

from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority
from jawl_voicecompanion.duplex_cascade import (
    DuplexCascadeArbiter,
    TOKEN_USER_BACKCHANNEL,
    TOKEN_USER_INTERRUPTION,
)
from jawl_voicecompanion.turn_trace import (
    STAGE_AUDIO_PLAYBACK_START,
    STAGE_AUDIO_STOPPED,
    STAGE_BARGE_IN_DETECTED,
    STAGE_USER_SPEECH_END,
    compute_turn_kpis,
)


class ArbiterEpochTests(unittest.TestCase):
    def test_epoch_starts_at_zero(self):
        arbiter = TurnArbiter()
        self.assertEqual(arbiter.generation_epoch, 0)

    def test_next_epoch_increments_monotonically(self):
        arbiter = TurnArbiter()
        self.assertEqual(arbiter.next_epoch(), 1)
        self.assertEqual(arbiter.next_epoch(), 2)
        self.assertEqual(arbiter.generation_epoch, 2)

    def test_reset_epoch(self):
        arbiter = TurnArbiter()
        arbiter.next_epoch()
        arbiter.next_epoch()
        self.assertEqual(arbiter.reset_epoch(0), 0)
        self.assertEqual(arbiter.generation_epoch, 0)

    def test_cancel_all_advances_epoch_and_cancels_active(self):
        arbiter = TurnArbiter()
        turn1 = arbiter.begin(TurnPriority.USER_FINAL, "turn-1")
        self.assertTrue(arbiter.is_current(turn1))
        initial_epoch = arbiter.generation_epoch

        arbiter.cancel_all("user_barge_in")

        self.assertFalse(arbiter.is_current(turn1))
        self.assertTrue(turn1.cancelled)
        self.assertEqual(arbiter.generation_epoch, initial_epoch + 1)

    def test_playback_fencing_drops_stale_chunks(self):
        """Simulates incoming TTS audio chunks tagged with an epoch."""
        arbiter = TurnArbiter()
        current_epoch = arbiter.generation_epoch
        chunks_received = []

        def handle_chunk(chunk_id: int, epoch: int):
            if epoch < arbiter.generation_epoch:
                # Fenced off: stale chunk from previous cancelled turn
                return False
            chunks_received.append(chunk_id)
            return True

        # Turn 0 chunks
        self.assertTrue(handle_chunk(1, current_epoch))
        self.assertTrue(handle_chunk(2, current_epoch))

        # Barge-in happens: epoch increments
        arbiter.cancel_all("barge_in")

        # In-flight chunks from Turn 0 arrive late
        self.assertFalse(handle_chunk(3, current_epoch))
        self.assertFalse(handle_chunk(4, current_epoch))

        # Turn 1 chunks arrive with fresh epoch
        new_epoch = arbiter.generation_epoch
        self.assertTrue(handle_chunk(5, new_epoch))

        self.assertEqual(chunks_received, [1, 2, 5])


class DuplexCascadeBargeInTests(unittest.TestCase):
    def setUp(self):
        self.duplex = DuplexCascadeArbiter()

    def test_backchannel_does_not_cancel_tts(self):
        """Short listener nods like 'угу' or 'ага' do not stop playback."""
        decision = self.duplex.evaluate_micro_turn(
            "угу",
            assistant_speaking=True,
            silence_elapsed_ms=100.0,
            rms_peak=0.03,
        )
        self.assertEqual(decision.token, TOKEN_USER_BACKCHANNEL)
        self.assertEqual(decision.action, "ignore_backchannel")

    def test_explicit_stop_cancels_tts(self):
        """Explicit stop word cancels ongoing TTS immediately."""
        for word in ("стой", "подожди", "хватит", "стоп"):
            decision = self.duplex.evaluate_micro_turn(
                word,
                assistant_speaking=True,
                silence_elapsed_ms=100.0,
                rms_peak=0.08,
            )
            self.assertEqual(decision.token, TOKEN_USER_INTERRUPTION, f"Failed for {word}")
            self.assertEqual(decision.action, "cancel_tts")

    def test_substantive_speech_during_assistant_turn_cancels_tts(self):
        """User speaking a full new thought or correction interrupts assistant."""
        decision = self.duplex.evaluate_micro_turn(
            "нет погоди давай сначала откроем браузер",
            assistant_speaking=True,
            silence_elapsed_ms=100.0,
            rms_peak=0.09,
        )
        self.assertEqual(decision.token, TOKEN_USER_INTERRUPTION)
        self.assertEqual(decision.action, "cancel_tts")


class BargeInLatencyKpiTests(unittest.TestCase):
    def test_barge_in_stop_under_300ms_passes_kpi(self):
        """Specification requires barge-in stop latency <= 300 ms."""
        records = [
            {"stage": STAGE_USER_SPEECH_END, "wall_ts": 100.0, "detail": None},
            {"stage": STAGE_AUDIO_PLAYBACK_START, "wall_ts": 100.9, "detail": None},
            {"stage": STAGE_BARGE_IN_DETECTED, "wall_ts": 102.1, "detail": {"reason": "barge_in"}},
            {"stage": STAGE_AUDIO_STOPPED, "wall_ts": 102.24, "detail": {"muted": True}},
        ]
        kpis = compute_turn_kpis(records)
        duration = kpis["barge_in_stop_duration_s"]
        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration, 0.14, places=2)
        self.assertLessEqual(duration, 0.300, "Barge-in stop duration must be <= 300 ms")

    def test_unrelated_audio_stopped_before_barge_in_ignored(self):
        """If audio stopped event occurred before barge in detected, duration is None."""
        records = [
            {"stage": STAGE_USER_SPEECH_END, "wall_ts": 10.0, "detail": None},
            {"stage": STAGE_AUDIO_STOPPED, "wall_ts": 10.5, "detail": None},
            {"stage": STAGE_BARGE_IN_DETECTED, "wall_ts": 11.0, "detail": None},
        ]
        kpis = compute_turn_kpis(records)
        self.assertIsNone(kpis["barge_in_stop_duration_s"])


if __name__ == "__main__":
    unittest.main()
