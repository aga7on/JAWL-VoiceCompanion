"""Deterministic echo guard for full-duplex conversational voice.

In full-duplex interaction, acoustic echo from speakers or system loopback
can feed the assistant's own speech back into the microphone/ASR pipeline.
Without echo suppression:
1. Streaming ASR transcribes the assistant's own words.
2. The turn policy / arbiter interprets multi-word speech during playback as
   a user interruption (``cancel_tts``), causing the assistant to cut itself off.
3. The echoed text is committed as a user turn, causing the brain to respond to itself.

This module provides:
- ``is_self_tts_echo``: deterministic text-domain check comparing candidate
  transcripts against active or recent assistant speech.
- ``EchoGuard``: lifecycle and telemetry coordinator for active reference text,
  loopback suppression, and draft/turn filtering.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

# Fast token matcher for Russian and ASCII words
_WORD_RE = re.compile(r"[а-яёa-z0-9]+(?:-[а-яёa-z0-9]+)*", re.IGNORECASE)

# Explicit interruption keywords that MUST NEVER be suppressed as echo
_INTERRUPT_KEYWORDS = frozenset({
    "стоп", "стой", "подожди", "погоди", "хватит", "тихо", "замолчи",
    "слушай", "послушай", "нет", "не надо", "остановись", "перестань",
    "лучше", "давай", "вопрос", "скажи", "расскажи", "почему", "зачем", "как",
})


def _normalize_words(text: str) -> list[str]:
    cleaned = str(text or "").lower().replace("ё", "е")
    return [w.strip("-") for w in _WORD_RE.findall(cleaned) if w.strip("-")]


def is_self_tts_echo(
    candidate: str,
    reference: str,
    *,
    min_match_ratio: float = 0.65,
    min_words: int = 2,
) -> bool:
    """Return True if candidate transcript is an acoustic echo of reference speech.

    Guarantees:
    - Never suppresses if candidate contains an explicit interruption keyword
      ("стоп", "стой", "нет", etc.) or ends with a question mark.
    - Requires at least ``min_words`` candidate words (short backchannels
      are handled by the backchannel policy, not echo guard).
    - Requires at least ``min_match_ratio`` of candidate words to be present in
      the reference text.
    - Requires at least one sequential 2-word bigram match if candidate length >= 3.
    """
    raw_candidate = str(candidate or "").strip()
    raw_ref = str(reference or "").strip()
    if not raw_candidate or not raw_ref:
        return False

    # A trailing question mark indicates an active user question, not playback echo
    if raw_candidate.endswith(("?", "？")):
        return False

    candidate_words = _normalize_words(raw_candidate)
    if len(candidate_words) < min_words:
        return False

    # Explicit interruptions take precedence over any echo match
    if any(w in _INTERRUPT_KEYWORDS for w in candidate_words):
        return False

    ref_words = _normalize_words(raw_ref)
    if not ref_words:
        return False

    ref_word_set = set(ref_words)
    matched_count = sum(1 for w in candidate_words if w in ref_word_set)
    ratio = matched_count / len(candidate_words)
    if ratio < min_match_ratio:
        return False

    # For 3+ words, enforce sequential consistency: at least one bigram must match
    if len(candidate_words) >= 3:
        ref_joined = " " + " ".join(ref_words) + " "
        has_bigram = False
        for i in range(len(candidate_words) - 1):
            bigram = f" {candidate_words[i]} {candidate_words[i + 1]} "
            if bigram in ref_joined:
                has_bigram = True
                break
        if not has_bigram:
            return False

    return True


class EchoGuard:
    """Tracks active/recent assistant speech and coordinates echo suppression."""

    def __init__(self, ttl_seconds: float = 20.0) -> None:
        self._lock = threading.RLock()
        self._current_text = ""
        self._last_text = ""
        self._updated_at = 0.0
        self._ttl_seconds = max(0.05, min(float(ttl_seconds), 120.0))
        self._suppressed_drafts = 0
        self._suppressed_turns = 0
        self._suppressed_loopback_chunks = 0

    def set_speaking_text(self, text: str) -> None:
        with self._lock:
            cleaned = str(text or "").strip()
            self._current_text = cleaned
            if cleaned:
                self._last_text = cleaned
            self._updated_at = time.monotonic()

    def clear(self) -> None:
        with self._lock:
            self._current_text = ""
            self._last_text = ""

    def get_reference_text(self) -> str:
        with self._lock:
            now = time.monotonic()
            if now - self._updated_at >= self._ttl_seconds:
                return ""
            if self._current_text:
                return self._current_text
            if self._last_text:
                return self._last_text
            return ""

    def is_echo(self, candidate_text: str) -> bool:
        ref = self.get_reference_text()
        if not ref:
            return False
        return is_self_tts_echo(candidate_text, ref)

    def record_suppressed_draft(self) -> None:
        with self._lock:
            self._suppressed_drafts += 1

    def record_suppressed_turn(self) -> None:
        with self._lock:
            self._suppressed_turns += 1

    def record_suppressed_loopback(self) -> None:
        with self._lock:
            self._suppressed_loopback_chunks += 1

    def state(self) -> dict[str, Any]:
        with self._lock:
            ref = self.get_reference_text()
            return {
                "active": bool(ref),
                "reference_preview": ref[:80] if ref else "",
                "suppressed_drafts": self._suppressed_drafts,
                "suppressed_turns": self._suppressed_turns,
                "suppressed_loopback_chunks": self._suppressed_loopback_chunks,
            }


__all__ = [
    "is_self_tts_echo",
    "EchoGuard",
]
