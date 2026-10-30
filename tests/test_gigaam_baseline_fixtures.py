from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gigaam_baseline_fixtures import word_error_rate  # noqa: E402


def test_wer_ignores_case_and_punctuation() -> None:
    assert word_error_rate(
        "Какой сегодня статус моего проекта?",
        "КАКОЙ сегодня статус моего проекта.",
    ) == 0.0


def test_wer_detects_omitted_repeated_phrase() -> None:
    reference = "Какой сегодня статус моего проекта? Какой сегодня статус моего проекта?"
    hypothesis = "Какой сегодня статус моего проекта?"
    assert word_error_rate(reference, hypothesis) == 0.5


def test_wer_rejects_empty_reference() -> None:
    try:
        word_error_rate("!!!", "текст")
    except ValueError as exc:
        assert "at least one word" in str(exc)
    else:
        raise AssertionError("empty WER reference should fail closed")
