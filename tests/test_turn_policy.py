import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.duplex_cascade import (  # noqa: E402
    TOKEN_USER_BACKCHANNEL,
    TOKEN_USER_INTERRUPTION,
)
from jawl_voicecompanion.turn_policy import (  # noqa: E402
    BASE_SILENCE_MS,
    EXTENDED_SILENCE_MS,
    decide,
    looks_incomplete,
)


class TurnPolicyTests(unittest.TestCase):
    def test_finished_sentence_is_complete(self):
        self.assertFalse(looks_incomplete("Готово, файл создан."))
        self.assertFalse(looks_incomplete("Ну как тебе такой результат?!"))

    def test_continuation_tail_holds(self):
        self.assertTrue(looks_incomplete("Я думаю, что"))
        self.assertTrue(looks_incomplete("Потом мы пошли в"))
        self.assertTrue(looks_incomplete("Это работает, но"))
        self.assertTrue(looks_incomplete("э"))

    def test_cut_word_holds(self):
        self.assertTrue(looks_incomplete("Проверяю сей-"))

    def test_short_draft_holds(self):
        self.assertTrue(looks_incomplete("Привет"))

    def test_decide_holds_until_extended(self):
        first = decide("Я думаю, что", silence_ms=900)
        self.assertEqual(first["action"], "hold")
        self.assertEqual(first["required_ms"], EXTENDED_SILENCE_MS)
        after = decide("Я думаю, что", silence_ms=900, extended_used=True)
        self.assertEqual(after["action"], "listen")
        self.assertEqual(after["required_ms"], EXTENDED_SILENCE_MS)

    def test_decide_ends_finished_after_base(self):
        decision = decide("Готово.", silence_ms=BASE_SILENCE_MS)
        self.assertEqual(decision["action"], "end")
        self.assertEqual(decision["required_ms"], BASE_SILENCE_MS)

    def test_decide_listens_before_base(self):
        decision = decide("Готово.", silence_ms=200)
        self.assertEqual(decision["action"], "listen")

    def test_assistant_speaking_substantive_speech_cancels_tts(self):
        decision = decide("Стой, подожди", silence_ms=120, assistant_speaking=True)
        self.assertEqual(decision["duplex_action"], "cancel_tts")
        self.assertEqual(decision["duplex_token"], TOKEN_USER_INTERRUPTION)

    def test_assistant_speaking_backchannel_keeps_tts(self):
        decision = decide("угу", silence_ms=120, assistant_speaking=True)
        self.assertEqual(decision["duplex_action"], "ignore_backchannel")
        self.assertEqual(decision["duplex_token"], TOKEN_USER_BACKCHANNEL)
        self.assertEqual(decision["avatar_gesture"], "nod")

    def test_extended_used_limits_one_extension(self):
        first = decide("Я думаю, что", silence_ms=100)
        self.assertEqual(first["action"], "hold")
        second = decide("Я думаю, что", silence_ms=100, extended_used=True)
        self.assertEqual(second["action"], "listen")
        self.assertTrue(second["hold"])


if __name__ == "__main__":
    unittest.main()
