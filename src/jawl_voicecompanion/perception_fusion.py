"""Sliding-window fusion of perception channels into one observation.

The companion senses the world through independent asynchronous lanes (VLM
screen captions, active-window titles, music state, speech). The brain should
receive ONE combined observation instead of a stream of per-sensor fragments:
this bounded assembler keeps the freshest text per channel (with per-channel
TTL) and renders it as a single Russian summary for the attention gate and
the JAWL event bridge. No LLM here: deterministic composition keeps the
transport cheap; an LLM composer can replace the renderer later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

_TTL_SECONDS = {
    "screen": 90.0,
    "window": 120.0,
    "music": 240.0,
    "speech": 300.0,
}
_LABELS = {
    "window": "Окно",
    "music": "Звук",
    "speech": "Слышно",
}


@dataclass
class PerceptionFusion:
    """Bounded latest-value store with TTLs and one combined renderer."""

    _items: dict[str, tuple[str, float]] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def note(self, kind: str, text: str, *, now: float | None = None) -> None:
        clean = str(text or "").replace("\x00", "").strip()[:600]
        if not clean:
            return
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            self._items[str(kind)[:20]] = (clean, moment)

    def compose(self, screen_summary: str = "", *, now: float | None = None) -> str:
        """Render the freshest channels plus the current screen caption.

        When no explicit caption is supplied, the last VLM caption stored via
        :meth:`observe_screen` is rendered instead (while fresh).
        """
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
        parts: list[str] = []
        screen = str(screen_summary or "").strip()[:600]
        if not screen:
            stored = items.get("screen")
            if stored and moment - stored[1] <= _TTL_SECONDS.get("screen", 90.0):
                screen = stored[0]
        if screen:
            parts.append(f"Экран: {screen}")
        for kind in ("window", "music", "speech"):
            entry = items.get(kind)
            if not entry:
                continue
            text, stamp = entry
            if moment - stamp > _TTL_SECONDS.get(kind, 120.0):
                continue
            parts.append(f"{_LABELS.get(kind, kind)}: {text}")
        return ". ".join(parts)[:1200]

    def observe_screen(self, caption: str) -> str:
        """Store the latest VLM caption and return the fused observation."""
        self.note("screen", caption)
        return self.compose()

    def state(self, *, now: float | None = None) -> dict[str, Any]:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
        fresh = {
            kind: {"text": text, "age_s": round(moment - stamp, 1)}
            for kind, (text, stamp) in items.items()
            if moment - stamp <= _TTL_SECONDS.get(kind, 120.0)
        }
        return {"fresh": fresh}
