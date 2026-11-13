"""Companion-side sensory motivation (drives-like signal) for proactive screen initiative.

Design (docs/SENSORY_MOTIVATION_DESIGN.md, owner 2026-11-10): when image/screen
descriptions in memory contain something interesting/novel, a sensory-curiosity
motivation rises and the system may respond proactively, subject to turn-policy
(no spam). This v0 is deterministic, owned by the companion, and does NOT patch
the read-only JAWL kernel/snapshot drives implementation. If a real drive write
path is available in the owned runtime, a later adapter may mirror the signal to
`curiosity`; until then this is an explicit companion-side counter with
growth/decay/threshold semantics (no second hidden source of truth beyond this
module's state).

Scoring v0 (no LLM): novelty of a normalized description against a bounded window
of recent descriptions, using token Jaccard overlap. High novelty or meaningful
change terms raise motivation; repeated/similar descriptions decay it.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

__all__ = ["SensoryMotivation", "SensoryMotivationConfig", "MotivationSignal"]

_WORD = re.compile(r"[0-9A-Za-zА-Яа-яЁё]{3,}")
# Terms that often indicate a meaningful on-screen change worth attention.
_CHANGE_HINTS = frozenset({
    "ошибка", "error", "ошибк", "предупреж", "warning", "fail", "сбой", "crash",
    "готов", "done", "complete", "заверш", "успеш", "success",
    "сообщен", "message", "уведом", "notif", "звон", "call",
    "диалог", "dialog", "окно", "window", "запрос", "request", "разреш", "permission",
    "установ", "install", "обнов", "update", "скач", "download",
    "парол", "password", "код", "code", "подтверж", "confirm",
})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())[:4000]


def _tokens(text: str) -> set[str]:
    return {m.group(0) for m in _WORD.finditer(_normalize(text))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _change_boost(tokens: set[str]) -> float:
    if not tokens:
        return 0.0
    hits = 0
    for t in tokens:
        for h in _CHANGE_HINTS:
            if t.startswith(h) or h.startswith(t):
                hits += 1
                break
    # bounded: 0..0.35
    return min(0.35, hits * 0.12)


@dataclass
class SensoryMotivationConfig:
    window: int = 12                 # recent descriptions to compare against
    threshold: float = 0.62          # motivation level that may trigger proactive response
    interest_floor: float = 0.38     # minimum novelty/interest to consider feeding (else ignore)
    decay_per_s: float = 0.015       # motivation decay rate (per second, exponential-ish step)
    rise_gain: float = 0.55          # how strongly novelty raises motivation
    cooldown_s: float = 300.0        # min seconds between triggers
    min_tokens: int = 4              # ignore too-short/empty descriptions
    max_description_chars: int = 2000


@dataclass
class MotivationSignal:
    score: float
    novelty: float
    triggered: bool
    reason: str
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "novelty": round(self.novelty, 4),
            "triggered": self.triggered,
            "reason": self.reason,
            "at": self.at,
        }


class SensoryMotivation:
    """Deterministic novelty-driven motivation signal over screen descriptions."""

    def __init__(self, config: SensoryMotivationConfig | None = None) -> None:
        self.config = config or SensoryMotivationConfig()
        self._recent: deque[tuple[float, set[str], str]] = deque(maxlen=max(2, self.config.window))
        self._score = 0.0
        self._last_update = 0.0
        self._last_trigger = 0.0
        self._total_events = 0
        self._triggered_count = 0

    def _decay(self, now: float) -> None:
        if self._last_update <= 0:
            self._last_update = now
            return
        dt = max(0.0, now - self._last_update)
        if dt <= 0:
            return
        # exponential decay step: score *= (1-decay)^dt, approximated for stability
        factor = max(0.0, 1.0 - self.config.decay_per_s) ** min(dt, 3600.0)
        self._score *= factor
        self._last_update = now

    def observe(self, description: str, now: float | None = None) -> MotivationSignal:
        now = time.time() if now is None else float(now)
        self._decay(now)
        text = _normalize(description)[: self.config.max_description_chars]
        toks = _tokens(text)
        if len(toks) < self.config.min_tokens:
            return MotivationSignal(self._score, 0.0, False, "too_short", now)

        max_sim = 0.0
        for _, rtoks, _ in self._recent:
            max_sim = max(max_sim, _jaccard(toks, rtoks))
        novelty = max(0.0, 1.0 - max_sim)
        interest = min(1.0, novelty + _change_boost(toks))
        self._total_events += 1

        if interest < self.config.interest_floor and novelty < 0.25:
            # familiar/low-signal: gentle extra decay, no trigger
            self._score *= 0.92
            self._recent.append((now, toks, text[:240]))
            return MotivationSignal(self._score, novelty, False, "familiar", now)

        # raise motivation by novelty/interest
        self._score = min(1.0, self._score + self.config.rise_gain * interest * (0.5 + 0.5 * novelty))
        self._recent.append((now, toks, text[:240]))

        triggered = False
        reason = "below_threshold"
        if self._score >= self.config.threshold:
            if now - self._last_trigger >= self.config.cooldown_s:
                triggered = True
                reason = "triggered"
                self._last_trigger = now
                self._triggered_count += 1
                # consume part of motivation so it doesn't fire repeatedly without new novelty
                self._score *= 0.45
            else:
                reason = "cooldown"
        return MotivationSignal(self._score, novelty, triggered, reason, now)

    def state(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        self._decay(now)
        return {
            "score": round(self._score, 4),
            "threshold": self.config.threshold,
            "recent": len(self._recent),
            "total_events": self._total_events,
            "triggered_count": self._triggered_count,
            "cooldown_remaining_s": max(0.0, round(self.config.cooldown_s - (now - self._last_trigger), 1)) if self._last_trigger else 0.0,
        }
