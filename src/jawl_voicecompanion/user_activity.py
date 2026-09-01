"""Low-privacy Windows user-activity signal for proactive attention."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


class _Win32ActivityBackend:
    """Read idle time and a window class without keyboard or title capture."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows user activity is unavailable")
        import ctypes
        from ctypes import wintypes

        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self._ctypes = ctypes
        self._last_input_type = LastInputInfo
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
        self._user32.GetLastInputInfo.restype = wintypes.BOOL
        self._kernel32.GetTickCount.restype = wintypes.DWORD
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetClassNameW.restype = ctypes.c_int

    def idle_seconds(self) -> float:
        info = self._last_input_type()
        info.cbSize = self._ctypes.sizeof(info)
        if not self._user32.GetLastInputInfo(self._ctypes.byref(info)):
            raise OSError("GetLastInputInfo failed")
        elapsed_ms = (int(self._kernel32.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed_ms / 1000.0

    def foreground_class(self) -> str:
        handle = self._user32.GetForegroundWindow()
        if not handle:
            return ""
        buffer = self._ctypes.create_unicode_buffer(128)
        length = self._user32.GetClassNameW(handle, buffer, len(buffer))
        return buffer.value[:120] if length else ""


@dataclass
class WindowsUserActivity:
    """Expose bounded activity metadata suitable for an Attention provider."""

    idle_threshold_seconds: float = 60.0
    backend: Any | None = None
    _load_error: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.idle_threshold_seconds = max(1.0, min(float(self.idle_threshold_seconds), 3600.0))

    def sample(self) -> dict[str, Any]:
        if self.backend is None and self._load_error is None:
            try:
                self.backend = _Win32ActivityBackend()
            except Exception:
                self._load_error = "windows_activity_unavailable"
        if self.backend is None:
            return {"status": "degraded", "reason": self._load_error or "activity_backend_unavailable"}
        try:
            idle = max(0.0, min(float(self.backend.idle_seconds()), 30 * 24 * 3600.0))
            foreground = str(self.backend.foreground_class() or "")[:120]
        except Exception:
            return {"status": "degraded", "reason": "windows_activity_failed"}
        return {
            "status": "verified",
            "idle_seconds": round(idle, 1),
            "threshold_seconds": self.idle_threshold_seconds,
            "user_active": idle < self.idle_threshold_seconds,
            "foreground_class": foreground,
        }


__all__ = ["WindowsUserActivity"]
