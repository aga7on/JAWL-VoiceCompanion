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
from .duplex_cascade import (
    TOKEN_NO_VOICE,
    TOKEN_USER_BACKCHANNEL,
    TOKEN_USER_FINISH,
    TOKEN_USER_INTERRUPTION,
    TOKEN_USER_TALKING,
    TOKEN_USER_THINKING,
    DuplexCascadeArbiter,
)

BASE_SILENCE_MS = 800
EXTENDED_SILENCE_MS = 2000

_DEFAULT_ARBITER = DuplexCascadeArbiter(
    eg2_model_root=None,
    fast_finish_silence_ms=BASE_SILENCE_MS,
    normal_silence_ms=BASE_SILENCE_MS,
    thinking_silence_ms=EXTENDED_SILENCE_MS,
)

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

def decide(
    text: str,
    silence_ms: float,
    extended_used: bool = False,
    *,
    assistant_speaking: bool = False,
) -> dict:
    """Return the endpoint decision for the open utterance.

    ``extended_used`` is True when this utterance already received one
    extension; only one extension is granted per utterance so a monologue
    cannot hold the turn forever.
    """
    micro = _DEFAULT_ARBITER.evaluate_micro_turn(
        text,
        assistant_speaking=assistant_speaking,
        silence_elapsed_ms=silence_ms,
        rms_peak=0.05 if str(text or "").strip() else 0.0,
    )
    hold = looks_incomplete(text)
    if hold and not extended_used:
        action = "hold" if silence_ms < EXTENDED_SILENCE_MS else "end"
        return {
            "action": action,
            "hold": True,
            "required_ms": EXTENDED_SILENCE_MS,
            "duplex_token": TOKEN_USER_THINKING if action == "hold" else TOKEN_USER_FINISH,
            "duplex_action": micro.action,
            "avatar_gesture": micro.avatar_gesture,
        }
    required = BASE_SILENCE_MS if not hold else EXTENDED_SILENCE_MS
    action = "end" if silence_ms >= required else "listen"
    token = (
        micro.token
        if assistant_speaking
        else (TOKEN_USER_FINISH if action == "end" else TOKEN_USER_TALKING)
    )
    return {
        "action": action,
        "hold": hold,
        "required_ms": required,
        "duplex_token": token,
        "duplex_action": micro.action,
        "avatar_gesture": micro.avatar_gesture,
    }


__all__ = [
    "BASE_SILENCE_MS",
    "EXTENDED_SILENCE_MS",
    "CONTINUATION_TAIL",
    "looks_incomplete",
    "decide",
]
