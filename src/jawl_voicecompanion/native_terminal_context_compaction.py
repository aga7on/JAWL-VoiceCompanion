"""Compact old native terminal turns before they consume the prompt budget.

This owned adapter reads the existing terminal history file, preserves recent
turns verbatim, and represents older turns as bounded chronological excerpts.
It does not call a model during prompt construction, so it adds no generation
latency and cannot invent a semantic summary.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable


_INSTALL_ATTR = "__jawl_terminal_context_compaction_installation__"
_PERCEPTION_BLOCK = re.compile(r"\n\n\[ФОН ВОСПРИЯТИЯ[^\]]{0,1200}\]", re.S | re.I)
_WHITESPACE = re.compile(r"\s+")
_DEFAULT_KEEP_RECENT = 12
_DEFAULT_TARGET_CHARS = 18000
_DEFAULT_EXCERPT_CHARS = 140


def _without_sensors(text: str) -> str:
    name = "_owned_perception_packet"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("perception_packet.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module.strip_appendix(text)


def _message_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    value = item.get("text")
    return _without_sensors(value).strip() if isinstance(value, str) else ""


def _compact_excerpt(text: str, limit: int) -> str:
    clean = _PERCEPTION_BLOCK.sub("", text)
    clean = _WHITESPACE.sub(" ", clean).strip()
    if len(clean) <= limit:
        return clean
    if limit <= 3:
        return clean[:limit]
    head = max(1, limit * 2 // 3)
    tail = max(1, limit - head - 3)
    return clean[:head].rstrip() + " … " + clean[-tail:].lstrip()


def compact_terminal_history(
    history: list[Any],
    *,
    keep_recent: int = _DEFAULT_KEEP_RECENT,
    target_chars: int = _DEFAULT_TARGET_CHARS,
    excerpt_chars: int = _DEFAULT_EXCERPT_CHARS,
) -> tuple[str, dict[str, int | bool]]:
    """Format durable history with a compact older section and exact recent turns."""
    if keep_recent < 2 or target_chars < 1000:
        raise ValueError("invalid terminal history compaction limits")
    valid = [item for item in history if isinstance(item, dict) and _message_text(item)]
    rendered = []
    source_chars = sum(len(_message_text(item)) for item in valid)
    if source_chars <= target_chars:
        rendered = [
            f"[{str(item.get('time') or '').strip()}] [{str(item.get('sender') or 'Unknown')}]: {_message_text(item)}"
            for item in valid
        ]
        return "\n".join(rendered), {
            "compacted": False, "messages": len(valid), "source_chars": sum(map(len, rendered)),
            "output_chars": sum(map(len, rendered)), "summarized_messages": 0,
        }

    split = max(0, len(valid) - keep_recent)
    older = valid[:split]
    recent = valid[split:]
    first_time = str(older[0].get("time") or "")[:32] if older else ""
    last_time = str(older[-1].get("time") or "")[:32] if older else ""
    lines = [
        "Earlier conversation (all messages retained as short chronological excerpts; "
        f"{first_time} to {last_time}; perception snapshots omitted):"
    ]
    selected_older = older
    for item in selected_older:
        sender_value = str(item.get("sender") or "Unknown").lower()
        sender = "U" if sender_value in {"user", "human"} else "A" if sender_value in {"assistant", "agent"} else "O"
        excerpt = _compact_excerpt(_message_text(item), excerpt_chars)
        if excerpt:
            lines.append(f"{sender}: {excerpt}")
    lines.append("Recent conversation (verbatim):")
    for item in recent:
        sender = str(item.get("sender") or "Unknown")[:32]
        timestamp = str(item.get("time") or "")[:32]
        lines.append(f"[{timestamp}] [{sender}]: {_message_text(item)}")

    result = "\n".join(lines)
    # The native provider budget for the active 65K profile is 20K chars.
    # This safety valve keeps additional room for the rest of JAWL context.
    if len(result) > target_chars:
        compact_lines = [lines[0]]
        for item in selected_older:
            sender_value = str(item.get("sender") or "Unknown").lower()
            sender = "U" if sender_value in {"user", "human"} else "A" if sender_value in {"assistant", "agent"} else "O"
            excerpt = _compact_excerpt(_message_text(item), 48)
            if excerpt:
                compact_lines.append(f"{sender}: {excerpt}")
        compact_lines.append("Recent conversation (verbatim, sensory appendices removed):")
        for item in recent:
            sender = str(item.get("sender") or "Unknown")[:32]
            text = _compact_excerpt(_message_text(item), 280)
            compact_lines.append(f"[{sender}]: {text}")
        result = "\n".join(compact_lines)

    return result, {
        "compacted": True, "messages": len(valid), "source_chars": source_chars,
        "output_chars": len(result), "summarized_messages": len(older),
    }


@dataclass(frozen=True)
class TerminalContextCompactionInstallation:
    client_class: type
    original_get_context_block: Callable[..., Any]
    wrapped_get_context_block: Callable[..., Any]
    target_chars: int = _DEFAULT_TARGET_CHARS


def install_native_terminal_context_compaction(
    client_class: type | None = None,
    *,
    keep_recent: int = _DEFAULT_KEEP_RECENT,
    target_chars: int = _DEFAULT_TARGET_CHARS,
) -> TerminalContextCompactionInstallation:
    """Wrap the native terminal provider without modifying the imported JAWL tree."""
    if client_class is None:
        client_class = importlib.import_module(
            "src.l2_interfaces.host.terminal.client"
        ).HostTerminalClient
    if not isinstance(client_class, type):
        raise TypeError("terminal context compaction requires a client class")
    existing = vars(client_class).get(_INSTALL_ATTR)
    if isinstance(existing, TerminalContextCompactionInstallation):
        return existing
    original = getattr(client_class, "get_context_block", None)
    if not callable(original):
        raise TypeError("native terminal client does not expose get_context_block")
    try:
        window = int(os.environ.get("JAWL_CONTEXT_WINDOW_TOKENS", "0"))
    except ValueError:
        window = 0
    if 65536 <= window <= 1048576:
        target_chars = max(target_chars, window * 3 // 2)

    async def wrapped(client: Any, **kwargs: Any) -> str:
        block = await original(client, **kwargs)
        if "Recent messages:\n" not in block:
            return block
        reader = getattr(client, "_read_history_file", None)
        if not callable(reader):
            return block
        history = reader()
        if not isinstance(history, list):
            return block
        compacted, stats = compact_terminal_history(
            history,
            keep_recent=keep_recent,
            target_chars=target_chars,
        )
        return block.split("Recent messages:\n", 1)[0] + "Recent messages:\n" + compacted

    installation = TerminalContextCompactionInstallation(client_class, original, wrapped, target_chars)
    original_record = getattr(client_class, "_record_message", None)
    if callable(original_record):
        def record(client, sender, text, time_str=""):
            return original_record(client, sender, _without_sensors(text) if sender == "User" else text, time_str)
        setattr(client_class, "_record_message", record)
    setattr(client_class, "get_context_block", wrapped)
    setattr(client_class, _INSTALL_ATTR, installation)
    return installation


__all__ = [
    "TerminalContextCompactionInstallation",
    "compact_terminal_history",
    "install_native_terminal_context_compaction",
]
