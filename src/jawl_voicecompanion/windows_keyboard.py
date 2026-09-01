"""Bounded foreground-keyboard control for custom Windows applications."""

from __future__ import annotations

import ctypes
import os
from typing import Any, Callable, Mapping

from .windows_pointer import _Win32Foreground, _bounds


_SPECIAL_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "win": 0x5B,
    "meta": 0x5B,
}


def _virtual_key(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    key = value.strip().casefold().replace(" ", "")
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    return None


class _Win32Keyboard:
    KEYUP = 0x0002
    UNICODE = 0x0004

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("keyboard control requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def type_text(self, text: str) -> None:
        raw = text.encode("utf-16-le", errors="surrogatepass")
        for offset in range(0, len(raw), 2):
            scan_code = int.from_bytes(raw[offset : offset + 2], "little")
            self.user32.keybd_event(0, scan_code, self.UNICODE, 0)
            self.user32.keybd_event(0, scan_code, self.UNICODE | self.KEYUP, 0)

    def hotkey(self, keys: list[int]) -> None:
        for key in keys:
            self.user32.keybd_event(key, 0, 0, 0)
        for key in reversed(keys):
            self.user32.keybd_event(key, 0, self.KEYUP, 0)


class WindowsKeyboardAdapter:
    """Send bounded text or hotkeys to the current foreground application."""

    def __init__(
        self,
        *,
        foreground_provider: Callable[[], Mapping[str, Any]] | None = None,
        keyboard_backend: Any | None = None,
    ) -> None:
        self._foreground = foreground_provider or _Win32Foreground()
        self._keyboard = keyboard_backend
        if self._keyboard is None and os.name == "nt":
            self._keyboard = _Win32Keyboard()

    def act(self, operation: str, target: Mapping[str, Any], value: str | None = None) -> dict[str, Any]:
        operation = str(operation or "").strip().casefold()
        if operation not in {"type", "hotkey"}:
            return {"status": "denied", "reason": "unsupported_keyboard_operation"}
        if not isinstance(target, Mapping):
            return {"status": "denied", "reason": "keyboard_target_required"}
        current = self._snapshot()
        if current is None:
            return {"status": "degraded", "reason": "foreground_window_unavailable"}
        if self._keyboard is None:
            return {"status": "degraded", "reason": "keyboard_requires_windows"}
        if not self._matches_expected_window(current, target):
            return {"status": "stale_target", "reason": "foreground_window_changed"}

        if operation == "type":
            text = value if isinstance(value, str) else target.get("text")
            if not isinstance(text, str) or not text or len(text) > 4000:
                return {"status": "denied", "reason": "bounded_keyboard_text_required"}
            action = lambda: self._keyboard.type_text(text)
        else:
            raw_keys = target.get("keys")
            if not isinstance(raw_keys, (list, tuple)) or not 1 <= len(raw_keys) <= 4:
                return {"status": "denied", "reason": "hotkey_requires_one_to_four_keys"}
            keys = [_virtual_key(item) for item in raw_keys]
            if any(key is None for key in keys):
                return {"status": "denied", "reason": "unsupported_hotkey_key"}
            action = lambda: self._keyboard.hotkey([key for key in keys if key is not None])

        try:
            action()
            after = self._snapshot()
        except (OSError, RuntimeError) as exc:
            return {"status": "failed", "reason": str(exc)[:200]}
        unchanged = after == current if after is not None else False
        return {
            "status": "dispatched",
            "operation": operation,
            "postcondition": {"name": "foreground_window_unchanged", "verified": unchanged},
            "verified": False,
        }

    def _snapshot(self) -> tuple[str, tuple[int, int, int, int]] | None:
        try:
            value = dict(self._foreground())
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        if value.get("status") != "verified":
            return None
        bounds = _bounds(value.get("bounds"))
        class_name = value.get("class_name")
        if bounds is None or not isinstance(class_name, str):
            return None
        return class_name[:120], bounds

    @staticmethod
    def _matches_expected_window(current: tuple[str, tuple[int, int, int, int]], target: Mapping[str, Any]) -> bool:
        expected_class = target.get("window_class", target.get("class_name"))
        if expected_class is not None and (not isinstance(expected_class, str) or len(expected_class) > 120):
            return False
        if isinstance(expected_class, str) and expected_class and expected_class != current[0]:
            return False
        expected_bounds = target.get("window_bounds", target.get("bounds"))
        if expected_bounds is not None and _bounds(expected_bounds) != current[1]:
            return False
        return True


__all__ = ["WindowsKeyboardAdapter"]
