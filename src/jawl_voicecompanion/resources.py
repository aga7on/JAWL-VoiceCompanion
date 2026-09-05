"""Tiny priority-aware resource governor for local companion workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any


_PROFILES = {
    "low": {"speech": 1, "vision": 1, "ambient": 0},
    "standard": {"speech": 1, "vision": 1, "ambient": 1},
    "high": {"speech": 1, "vision": 2, "ambient": 2},
}


@dataclass
class ResourceGovernor:
    """Bound concurrency without adding a heavyweight scheduler dependency."""

    profile: str = "standard"
    gaming_mode: bool = False
    _active: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            self.profile = "standard"

    def configure(self, *, profile: str | None = None, gaming_mode: bool | None = None) -> dict[str, Any]:
        with self._lock:
            if profile is not None:
                profile = str(profile).strip().casefold()
                if profile not in _PROFILES:
                    raise ValueError("resource profile must be low, standard or high")
                self.profile = profile
            if gaming_mode is not None:
                if not isinstance(gaming_mode, bool):
                    raise ValueError("gaming_mode must be boolean")
                self.gaming_mode = gaming_mode
            return self.state()

    def try_acquire(self, kind: str, *, background: bool = False) -> bool:
        kind = str(kind).strip().casefold()
        with self._lock:
            if background and self.gaming_mode:
                return False
            limit = _PROFILES[self.profile].get(kind, 1)
            if limit <= 0 or self._active.get(kind, 0) >= limit:
                return False
            self._active[kind] = self._active.get(kind, 0) + 1
            return True

    def release(self, kind: str) -> None:
        with self._lock:
            current = self._active.get(str(kind).strip().casefold(), 0)
            if current <= 1:
                self._active.pop(str(kind).strip().casefold(), None)
            else:
                self._active[str(kind).strip().casefold()] = current - 1

    def state(self) -> dict[str, Any]:
        with self._lock:
            limits = dict(_PROFILES[self.profile])
            return {
                "profile": self.profile,
                "gaming_mode": self.gaming_mode,
                "limits": limits,
                "active": dict(self._active),
                "background_workers": "paused" if self.gaming_mode else "allowed",
            }


__all__ = ["ResourceGovernor"]
