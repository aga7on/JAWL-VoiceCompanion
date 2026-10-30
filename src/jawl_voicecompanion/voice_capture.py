"""Bounded, process-local ownership lease for microphone capture."""

from __future__ import annotations

import math
import numbers
import threading
import time
from dataclasses import dataclass
from typing import Any


LEASE_TTL_MS = 15_000
CAPTURE_CONFIG_FIELDS = {
    "gate_open": ("interfaces:voice.capture.gate_open", "voice.capture.gate_open"),
    "gate_close": ("interfaces:voice.capture.gate_close", "voice.capture.gate_close"),
    "silence_ms": ("interfaces:voice.capture.silence_ms", "voice.capture.silence_ms"),
    "pre_roll_ms": ("interfaces:voice.capture.pre_roll_ms", "voice.capture.pre_roll_ms"),
}


@dataclass(frozen=True)
class VoiceCaptureSettings:
    gate_open: float = 0.02
    gate_close: float = 0.012
    silence_ms: int = 1_200
    pre_roll_ms: int = 120

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None = None) -> "VoiceCaptureSettings":
        """Validate persisted values; malformed config must remain visible."""
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise ValueError("voice capture config must be an object")
        unknown = set(values) - set(CAPTURE_CONFIG_FIELDS)
        if unknown:
            raise ValueError("unknown voice capture config keys: " + ", ".join(sorted(unknown)))
        merged = cls().as_settings_dict()
        merged.update(values)
        return cls._validated(merged)

    @classmethod
    def from_request(
        cls, values: Any, current: "VoiceCaptureSettings | None" = None,
    ) -> "VoiceCaptureSettings":
        if not isinstance(values, dict):
            raise ValueError("settings must be an object")
        unknown = set(values) - set(CAPTURE_CONFIG_FIELDS)
        if unknown:
            raise ValueError("unknown voice capture settings: " + ", ".join(sorted(unknown)))
        merged = (current or cls()).as_settings_dict()
        merged.update(values)
        return cls._validated(merged)

    @classmethod
    def _validated(cls, merged: dict[str, Any]) -> "VoiceCaptureSettings":
        for key, value in merged.items():
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ValueError(f"{key} must be a finite number")
            try:
                finite = math.isfinite(float(value))
            except (OverflowError, TypeError, ValueError):
                finite = False
            if not finite:
                raise ValueError(f"{key} must be a finite number")
        gate_open = float(merged["gate_open"])
        gate_close = float(merged["gate_close"])
        silence = merged["silence_ms"]
        pre_roll = merged["pre_roll_ms"]
        if not 0.001 <= gate_open <= 0.25:
            raise ValueError("gate_open must be between 0.001 and 0.25")
        if not 0.0005 <= gate_close < gate_open:
            raise ValueError("gate_close must be at least 0.0005 and less than gate_open")
        if not isinstance(silence, int) or not 300 <= silence <= 5_000:
            raise ValueError("silence_ms must be an integer between 300 and 5000")
        if not isinstance(pre_roll, int) or not 0 <= pre_roll <= 500:
            raise ValueError("pre_roll_ms must be an integer between 0 and 500")
        return cls(gate_open, gate_close, silence, pre_roll)

    def as_settings_dict(self) -> dict[str, int | float]:
        return {
            "gate_open": self.gate_open,
            "gate_close": self.gate_close,
            "silence_ms": self.silence_ms,
            "pre_roll_ms": self.pre_roll_ms,
        }

    def as_dict(self) -> dict[str, int | float]:
        return {
            **self.as_settings_dict(),
            "lease_ttl_ms": LEASE_TTL_MS,
        }


def read_config_hub_settings(config_hub: Any) -> VoiceCaptureSettings:
    if config_hub is None:
        raise RuntimeError("config hub is not configured")
    values = config_hub.read_voice_capture()["settings"]
    return VoiceCaptureSettings.from_mapping(values)


def capture_config_error(exc: Exception) -> str:
    """Expose only fixed validation hints, never YAML contents or I/O paths."""
    safe_hints = {
        "gate_open must be between 0.001 and 0.25",
        "gate_close must be at least 0.0005 and less than gate_open",
        "silence_ms must be an integer between 300 and 5000",
        "pre_roll_ms must be an integer between 0 and 500",
        *(f"{field} must be a finite number" for field in CAPTURE_CONFIG_FIELDS),
    }
    hint = str(exc) if isinstance(exc, ValueError) and str(exc) in safe_hints else "check interfaces.yaml voice.capture"
    return f"voice capture config unavailable: {hint}"


class CaptureLeaseError(RuntimeError):
    def __init__(self, code: str, owner: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.owner = owner


class _CaptureCancellation(threading.Event):
    """Cancellation remains deadline-aware even when the UI stops renewing."""

    def __init__(self, expires_at: float) -> None:
        super().__init__()
        self.expires_at = expires_at

    def is_set(self) -> bool:
        if time.monotonic() >= self.expires_at:
            self.set()
        return super().is_set()


class VoiceCaptureLease:
    """Atomic desktop/native lease; monotonic deadlines never persist."""

    OWNERS = frozenset({"desktop", "native"})

    def __init__(self, settings: VoiceCaptureSettings | None = None) -> None:
        self.settings = settings or VoiceCaptureSettings()
        self._lock = threading.Lock()
        self._owner: str | None = None
        self._capture_id: str | None = None
        self._expires_at = 0.0
        self._cancel: _CaptureCancellation | None = None

    def set_settings(self, settings: VoiceCaptureSettings) -> None:
        if not isinstance(settings, VoiceCaptureSettings):
            raise TypeError("settings must be VoiceCaptureSettings")
        with self._lock:
            self.settings = settings

    def _expire(self, now: float) -> None:
        if self._owner is not None and now >= self._expires_at:
            if self._cancel is not None:
                self._cancel.set()
            self._owner = None
            self._capture_id = None
            self._expires_at = 0.0

    @staticmethod
    def _identity(owner: Any, capture_id: Any) -> tuple[str, str]:
        if not isinstance(owner, str) or owner not in VoiceCaptureLease.OWNERS:
            raise ValueError("owner must be desktop or native")
        if not isinstance(capture_id, str) or not capture_id or len(capture_id) > 128:
            raise ValueError("capture_id must be a non-empty string of at most 128 characters")
        return owner, capture_id

    def acquire(self, owner: Any, capture_id: Any) -> dict[str, Any]:
        owner, capture_id = self._identity(owner, capture_id)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            if self._owner is not None and (self._owner, self._capture_id) != (owner, capture_id):
                raise CaptureLeaseError("capture_busy", self._owner)
            was_unclaimed = self._owner is None
            self._owner, self._capture_id = owner, capture_id
            self._expires_at = now + LEASE_TTL_MS / 1000
            if was_unclaimed:
                self._cancel = _CaptureCancellation(self._expires_at)
            else:
                self._cancel.expires_at = self._expires_at
            return self._state_locked(now)

    def renew(self, owner: Any, capture_id: Any) -> dict[str, Any]:
        owner, capture_id = self._identity(owner, capture_id)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            if (self._owner, self._capture_id) != (owner, capture_id):
                raise CaptureLeaseError("capture_lease_lost", self._owner)
            self._expires_at = now + LEASE_TTL_MS / 1000
            self._cancel.expires_at = self._expires_at
            return self._state_locked(now)

    def release(self, owner: Any, capture_id: Any) -> dict[str, Any]:
        owner, capture_id = self._identity(owner, capture_id)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            if (self._owner, self._capture_id) != (owner, capture_id):
                raise CaptureLeaseError("capture_lease_lost", self._owner)
            if self._cancel is not None:
                self._cancel.set()
            self._owner = self._capture_id = None
            self._expires_at = 0.0
            return self._state_locked(now)

    def authorize_stream(self, payload: dict[str, Any]) -> threading.Event | None:
        claimed_id = payload.get("capture_id")
        claimed_owner = payload.get("owner")
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            if self._owner is None:
                if claimed_id is not None:
                    raise CaptureLeaseError("capture_lease_lost")
                return  # legacy fake-HTTP callers work only while unclaimed
            if claimed_id is None:
                raise CaptureLeaseError("capture_lease_lost", self._owner)
            if not isinstance(claimed_id, str) or claimed_id != self._capture_id:
                raise CaptureLeaseError("capture_busy", self._owner)
            if claimed_owner is not None and claimed_owner != self._owner:
                raise CaptureLeaseError("capture_busy", self._owner)
            return self._cancel

    def state(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            return self._state_locked(now)

    def _state_locked(self, now: float) -> dict[str, Any]:
        return {
            "ok": True,
            "owner": self._owner,
            "capture_id": self._capture_id,
            "expires_in_ms": max(0, int((self._expires_at - now) * 1000)) if self._owner else 0,
            **self.settings.as_dict(),
        }
