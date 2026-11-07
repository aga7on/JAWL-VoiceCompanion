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

import src.l3_agent.llm.speech_first as _upstream_speech_first

# Canonical terminal reply tool names and aliases recognized across JAWL
EXTENDED_TERMINAL_TOOL_NAMES: tuple[str, ...] = (
    "HostTerminalMessages.send_message_to_terminal",
    "HostOSTerminal.send_message_to_terminal",
    "HostOSJournalMessages.send_message_to_terminal",
    "send_message_to_terminal",
)
_upstream_speech_first.TERMINAL_TOOL_NAMES = EXTENDED_TERMINAL_TOOL_NAMES

from src.l3_agent.llm.speech_first import (  # noqa: E402
    SpeechChunk,
    SpeechFirstGate,
    extract_speech_text,
    first_speakable_chunk,
    looks_like_reply_action,
)

TERMINAL_TOOL_NAMES = EXTENDED_TERMINAL_TOOL_NAMES

__all__ = [
    "TERMINAL_TOOL_NAMES",
    "SpeechChunk",
    "SpeechFirstGate",
    "extract_speech_text",
    "first_speakable_chunk",
    "looks_like_reply_action",
]
