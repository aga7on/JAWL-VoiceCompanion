"""Deterministic guard for obvious ASR noise artifacts in speech paths."""

from __future__ import annotations

import re

_FOREIGN_SCRIPT_RANGES = (
    (0x2E80, 0x2EFF),  # CJK Radicals Supplement
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x31F0, 0x31FF),  # Katakana Phonetic Extensions
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFF00, 0xFF5F),  # Fullwidth Forms
    (0xAC00, 0xD7AF),  # Hangul Syllables
)


def is_meaningful_transcript(text: str) -> bool:
    """Reject empty, single-character, repeated-character and CJK/Hangul noise.

    This is a narrow artifact filter, not a speech detector or transcript
    correctness check. Normal Russian and English words pass through.
    """
    cleaned = re.sub(r"[\W_]+", "", str(text or ""), flags=re.UNICODE)
    if len(cleaned) < 2:
        return False
    if any(start <= ord(char) <= end for char in cleaned for start, end in _FOREIGN_SCRIPT_RANGES):
        return False
    return len(set(cleaned.casefold())) > 1


__all__ = ["is_meaningful_transcript"]
