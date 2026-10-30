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
    make_packet,
    read_owned_packet,
    render_packet,
    save_packet,
    split_packet,
    strip_appendix,
)

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
