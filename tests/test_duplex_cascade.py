"""Unit tests for DuplexCascade micro-turn arbiter and EmbeddingGemma 2 scorer."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.duplex_cascade import (
    DuplexCascadeArbiter,
    TOKEN_NO_VOICE,
    TOKEN_USER_BACKCHANNEL,
    TOKEN_USER_FINISH,
    TOKEN_USER_INTERRUPTION,
    TOKEN_USER_TALKING,
    TOKEN_USER_THINKING,
)

ROOT = Path(__file__).resolve().parents[1]
EG2_ROOT = ROOT / "runtime" / "models" / "embeddinggemma-2-onnx"


class DuplexCascadeArbiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.arbiter = DuplexCascadeArbiter(
            eg2_model_root=EG2_ROOT if (EG2_ROOT / "onnx" / "model_q4.onnx").is_file() else None,
            fast_finish_silence_ms=380,
            normal_silence_ms=850,
            thinking_silence_ms=2200,
        )

    def test_silence_returns_no_voice(self) -> None:
        decision = self.arbiter.evaluate_micro_turn("", assistant_speaking=False, rms_peak=0.002)
        self.assertEqual(decision.token, TOKEN_NO_VOICE)
        self.assertEqual(decision.action, "continue")

    def test_short_acknowledgement_during_assistant_speech_is_backchannel(self) -> None:
        for phrase in ("Угу.", "Ага", "Понял", "Ого!", "Круто"):
            with self.subTest(phrase=phrase):
                decision = self.arbiter.evaluate_micro_turn(
                    phrase,
                    assistant_speaking=True,
                    speech_duration_ms=280,
                    rms_peak=0.08,
                )
                self.assertEqual(decision.token, TOKEN_USER_BACKCHANNEL)
                self.assertEqual(decision.action, "ignore_backchannel")
                self.assertEqual(decision.avatar_gesture, "nod")

    def test_explicit_stop_or_substantive_speech_during_assistant_speech_is_interruption(self) -> None:
        for phrase in (
            "Стой, подожди секунду",
            "Стоп",
            "Нет, давай лучше посмотрим аниме",
            "Слушай, у меня другой вопрос к тебе",
        ):
            with self.subTest(phrase=phrase):
                decision = self.arbiter.evaluate_micro_turn(
                    phrase,
                    assistant_speaking=True,
                    speech_duration_ms=650,
                    rms_peak=0.12,
                )
                self.assertEqual(decision.token, TOKEN_USER_INTERRUPTION)
                self.assertEqual(decision.action, "cancel_tts")

    def test_trailing_conjunction_or_hesitation_holds_turn_as_thinking(self) -> None:
        for phrase in (
            "Слушай, я сегодня хотел...",
            "Итак, э-э",
            "Давай напишем мод, который",
            "Ну как бы",
        ):
            with self.subTest(phrase=phrase):
                decision = self.arbiter.evaluate_micro_turn(
                    phrase,
                    assistant_speaking=False,
                    silence_elapsed_ms=650,
                    speech_duration_ms=1100,
                    rms_peak=0.10,
                )
                self.assertEqual(decision.token, TOKEN_USER_THINKING)
                self.assertEqual(decision.action, "hold_turn")
                self.assertEqual(decision.recommended_silence_ms, 2200)

    def test_complete_question_commits_fast_without_waiting_full_vad_timeout(self) -> None:
        decision = self.arbiter.evaluate_micro_turn(
            "И что теперь?",
            assistant_speaking=False,
            silence_elapsed_ms=400,
            speech_duration_ms=900,
            rms_peak=0.15,
        )
        self.assertEqual(decision.token, TOKEN_USER_FINISH)
        self.assertEqual(decision.action, "commit_turn")
        self.assertEqual(decision.recommended_silence_ms, 380)

    def test_active_mid_stream_speech_returns_user_talking(self) -> None:
        decision = self.arbiter.evaluate_micro_turn(
            "Привет как твои",
            assistant_speaking=False,
            silence_elapsed_ms=80,
            speech_duration_ms=500,
            rms_peak=0.14,
        )
        self.assertEqual(decision.token, TOKEN_USER_TALKING)
        self.assertEqual(decision.action, "hold_turn")


if __name__ == "__main__":
    unittest.main()
