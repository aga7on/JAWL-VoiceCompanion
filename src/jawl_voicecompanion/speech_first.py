"""Compatibility shim: speech-first extraction lives in the kernel (ADR-049).

The pure gate moved to ``src.l3_agent.llm.speech_first``; this re-export keeps
existing ``jawl_voicecompanion.speech_first`` imports working.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
if str(_SNAPSHOT) not in sys.path:
    sys.path.insert(0, str(_SNAPSHOT))

from src.l3_agent.llm.speech_first import (  # noqa: E402
    TERMINAL_TOOL_NAMES,
    SpeechChunk,
    SpeechFirstGate,
    extract_speech_text,
    first_speakable_chunk,
    looks_like_reply_action,
)

__all__ = [
    "TERMINAL_TOOL_NAMES",
    "SpeechChunk",
    "SpeechFirstGate",
    "extract_speech_text",
    "first_speakable_chunk",
    "looks_like_reply_action",
]
