"""Compatibility shim: the AV evidence packet codec lives in the kernel (ADR-049).

Moved to ``src.l3_agent.context.perception_packet``; this re-export keeps
existing ``jawl_voicecompanion.perception_packet`` imports working.
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

from src.l3_agent.context.perception_packet import (  # noqa: E402
    CLOSE,
    OPEN,
    attach_packet,
    make_packet as _kernel_make_packet,
    read_owned_packet,
    render_packet,
    save_packet,
    split_packet,
    strip_appendix,
)


def make_packet(snapshot: dict[str, Any], *, fallback: str = "", history: str = "") -> dict[str, Any]:
    """Build the perception packet, ensuring unverified hypotheses are marked."""
    packet = _kernel_make_packet(snapshot, fallback=fallback, history=history)
    channels = snapshot.get("channels")
    if isinstance(channels, dict) and isinstance(packet.get("channels"), dict):
        for kind, source in channels.items():
            if isinstance(source, dict) and kind in packet["channels"]:
                if source.get("hypothesis") is True:
                    packet["channels"][kind]["hypothesis"] = True
    return packet

__all__ = [
    "CLOSE",
    "OPEN",
    "attach_packet",
    "make_packet",
    "read_owned_packet",
    "render_packet",
    "save_packet",
    "split_packet",
    "strip_appendix",
]
