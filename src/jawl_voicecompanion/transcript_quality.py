"""Deterministic guard for obvious ASR noise artifacts in speech paths."""

from __future__ import annotations

import re


# Pure interjections that GigaAM hallucinates in runs on silence or music.
# Deliberately narrow: real answer words ("да", "нет", "ок", "ладно", "ясно",
# "угу" as a single ack) must always pass — this set only names tokens whose
# mechanical repetition is not human speech.
_FILLER_TOKENS = frozenset({
    "ага", "угу", "угм", "мгм", "хм", "хмм", "мм", "ммм", "эм", "эмм", "ээ",
    "аа", "ааа", "оо", "ооо", "э", "эээ", "хех", "ха",
})

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

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


def _is_repeated_filler_noise(text: str) -> bool:
    """True when the transcript is mechanical filler repetition, not speech.

    Two narrow patterns only: one filler token repeated three or more times
    ("ага ага ага"), or a longer run built exclusively from fillers ("ага
    угу ага угу"). Anything else — real words, questions, mixed sentences —
    passes untouched.
    """
    tokens = _TOKEN.findall(str(text or "").casefold())
    if len(tokens) < 3:
        return False
    if len(set(tokens)) == 1:
        return tokens[0] in _FILLER_TOKENS
    return len(tokens) >= 4 and set(tokens) <= _FILLER_TOKENS


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
    if len(set(cleaned.casefold())) <= 1:
        return False
    return not _is_repeated_filler_noise(text)


__all__ = ["is_meaningful_transcript"]
