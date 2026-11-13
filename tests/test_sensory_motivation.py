"""Focused tests for companion-side sensory motivation (P-M0). Deterministic, no LLM/GPU."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.sensory_motivation import SensoryMotivation, SensoryMotivationConfig


class TestSensoryMotivation(unittest.TestCase):
    def test_novel_descriptions_raise_score(self) -> None:
        sm = SensoryMotivation(SensoryMotivationConfig(threshold=0.95, cooldown_s=9999, decay_per_s=0.0))
        a = sm.observe("На экране открыт редактор кода с файлом main.py и функцией запуска тестов", now=1000.0)
        self.assertGreater(a.novelty, 0.5)
        b = sm.observe("Появилось окно терминала с ошибкой компиляции и красным стеком вызовов", now=1001.0)
        self.assertGreater(b.score, a.score)

    def test_familiar_description_decays_and_does_not_trigger(self) -> None:
        sm = SensoryMotivation(SensoryMotivationConfig(threshold=0.4, cooldown_s=1.0, decay_per_s=0.0))
        text = "Рабочий стол с открытым браузером и вкладкой почты, без изменений"
        sm.observe(text, now=100.0)
        # repeat nearly identical
        sig = sm.observe(text, now=101.0)
        self.assertEqual(sig.reason, "familiar")
        self.assertFalse(sig.triggered)

    def test_trigger_then_cooldown_consumes_motivation(self) -> None:
        sm = SensoryMotivation(SensoryMotivationConfig(
            threshold=0.5, cooldown_s=60.0, decay_per_s=0.0, rise_gain=0.9, interest_floor=0.2, window=6))
        texts = [
            "Открыт браузер с документацией по API и примером запроса",
            "Появилось системное уведомление об ошибке сети и предложение повторить",
            "На экране диалог установки обновления с кнопкой подтвердить",
        ]
        triggered = None
        t = 2000.0
        for txt in texts:
            sig = sm.observe(txt, now=t)
            t += 5.0
            if sig.triggered:
                triggered = sig
                break
        self.assertIsNotNone(triggered, "expected at least one trigger")
        # immediate next novel event should be in cooldown or below threshold due to consumption
        sig2 = sm.observe("Новое окно с сообщением о завершении загрузки файла", now=t)
        self.assertFalse(sig2.triggered)
        self.assertIn(sig2.reason, {"cooldown", "below_threshold", "familiar"})

    def test_change_hints_boost_interest(self) -> None:
        sm = SensoryMotivation(SensoryMotivationConfig(decay_per_s=0.0))
        # first seeds window
        sm.observe("Открыт текстовый документ с заметками о планах на день", now=1.0)
        plain = sm.observe("Открыт текстовый документ с заметками о встречах на неделю", now=2.0)
        sm2 = SensoryMotivation(SensoryMotivationConfig(decay_per_s=0.0))
        sm2.observe("Открыт текстовый документ с заметками о планах на день", now=1.0)
        boosted = sm2.observe("Открыт текстовый документ: ошибка сохранения и предупреждение о конфликте", now=2.0)
        self.assertGreaterEqual(boosted.score, plain.score)

    def test_too_short_ignored(self) -> None:
        sm = SensoryMotivation(SensoryMotivationConfig(decay_per_s=0.0))
        sig = sm.observe("ок да", now=1.0)
        self.assertEqual(sig.reason, "too_short")
        self.assertEqual(sm.state(now=1.0)["total_events"], 0)

    def test_decay_reduces_score_over_time(self) -> None:
        sm = SensoryMotivation(SensoryMotivationConfig(decay_per_s=0.2, threshold=0.99, cooldown_s=9999))
        sm.observe("На экране график метрик с резким скачком нагрузки и предупреждением", now=10.0)
        s1 = sm.state(now=10.0)["score"]
        s2 = sm.state(now=20.0)["score"]
        self.assertLess(s2, s1)


if __name__ == "__main__":
    unittest.main()
