"""Adaptive turn-taking policy: semantic end-of-turn beyond binary VAD.

Silence is not an end-of-turn: "Я думаю, что…" with a 700 ms pause must hold
the turn longer than a finished sentence. This module implements the bounded
heuristic policy used by the voice lane (see docs/FULLDUPLEX adoption):

- ``looks_incomplete``: RU continuation cues + cut-word heuristics;
- ``decide``: returns the current action (hold/listen/end) and the silence
  requirement for the open utterance.

The policy is deliberately cheap and deterministic; a learned classifier can
replace it later behind the same interface.
"""

from __future__ import annotations

import re

BASE_SILENCE_MS = 800
EXTENDED_SILENCE_MS = 2000

_TERMINAL = (".", "!", "?", "…")
_WORD = re.compile(r"[а-яёa-z0-9]+(?:-[а-яёa-z0-9]+)*", re.IGNORECASE)

# Tokens that strongly suggest the sentence continues (RU).
CONTINUATION_TAIL = {
    "и", "а", "но", "или", "да", "же", "ли", "бы",
    "что", "чтобы", "потому", "поэтому", "если", "когда", "пока",
    "который", "которая", "которое", "которые", "которого", "которой",
    "как", "так", "это", "то", "такой", "такая", "такие",
    "ну", "вот", "значит", "короче", "типа", "вроде", "просто",
    "ещё", "еще", "уже", "тоже", "также", "например", "кстати",
    "э", "ээ", "эм", "мм", "ммм", "по-моему", "наверное", "кажется",
    "давай", "давайте", "хочу", "надо", "можно", "нужно",
    # trailing prepositions: "пошли в", "положил на", "вышел из"
    "в", "во", "на", "с", "со", "к", "ко", "от", "ото", "до", "по",
    "за", "из", "у", "об", "обо", "под", "над", "при", "про", "для",
    "без", "через", "между", "перед", "около", "возле", "после",
}

# Pure hesitation tails: the speaker is mid-thought, hold even harder.
HESITATION_TAIL = {"э", "ээ", "эм", "мм", "ммм", "ну", "это", "как"}


def looks_incomplete(text: str) -> bool:
    """True when the draft text reads like an unfinished utterance."""
    value = str(text or "").strip()
    if not value:
        return False
    stripped = value.rstrip()
    if stripped.endswith(_TERMINAL):
        return False
    if stripped.endswith("-") or stripped.endswith("—"):
        return True
    tokens = _WORD.findall(value.casefold())
    if not tokens:
        return False
    last = tokens[-1]
    if last in CONTINUATION_TAIL or last in HESITATION_TAIL:
        return True
    # Very short drafts are mid-thought by construction.
    if len(tokens) <= 1:
        return True
    return False

def decide(text: str, silence_ms: float, extended_used: bool = False) -> dict:
    """Return the endpoint decision for the open utterance.

    ``extended_used`` is True when this utterance already received one
    extension; only one extension is granted per utterance so a monologue
    cannot hold the turn forever.
    """
    hold = looks_incomplete(text)
    if hold and not extended_used:
        action = "hold" if silence_ms < EXTENDED_SILENCE_MS else "end"
        return {"action": action, "hold": True, "required_ms": EXTENDED_SILENCE_MS}
    required = BASE_SILENCE_MS if not hold else EXTENDED_SILENCE_MS
    action = "end" if silence_ms >= required else "listen"
    return {"action": action, "hold": hold, "required_ms": required}


__all__ = [
    "BASE_SILENCE_MS",
    "EXTENDED_SILENCE_MS",
    "CONTINUATION_TAIL",
    "looks_incomplete",
    "decide",
]
