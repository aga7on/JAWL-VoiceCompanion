"""Bounded Windows pointer control for custom and canvas-based applications.

UI Automation remains preferred for native controls. This adapter is the
small fallback for a VLM target that exists only as pixels, and never treats
an input dispatch as proof that the application accepted the click.
"""

from __future__ import annotations

import ctypes
import math
import os
from ctypes import wintypes
from typing import Any, Callable, Mapping

from .screen_adapter import verify_observation_token


_OPERATIONS = {"move", "click", "double_click", "right_click", "middle_click"}
_MOUSE_FLAGS = {
    "click": (0x0002, 0x0004),
    "double_click": (0x0002, 0x0004),
    "right_click": (0x0008, 0x0010),
    "middle_click": (0x0020, 0x0040),
}


def _bounds(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        return None
    left, top, right, bottom = (int(item) for item in value)
    return (left, top, right, bottom) if right > left and bottom > top else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    result = int(round(float(value)))
    return result if abs(result) <= 100_000 else None


class _Win32Foreground:
    def __call__(self) -> dict[str, Any]:
        if os.name != "nt":
            return {"status": "degraded", "reason": "pointer_requires_windows"}
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindowVisible(hwnd):
            return {"status": "degraded", "reason": "foreground_window_unavailable"}
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return {"status": "degraded", "reason": "foreground_window_bounds_unavailable"}
        class_name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        bounds = [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)]
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            return {"status": "degraded", "reason": "foreground_window_has_no_bounds"}
        return {"status": "verified", "hwnd": int(hwnd), "class_name": class_name.value[:120], "bounds": bounds}


class _Win32Pointer:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("pointer control requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def perform(self, operation: str, x: int, y: int) -> None:
        if not self.user32.SetCursorPos(x, y):
            raise OSError(ctypes.get_last_error(), "SetCursorPos failed")
        flags = _MOUSE_FLAGS.get(operation)
        if flags is None:
            return
        down, up = flags
        self.user32.mouse_event(down, 0, 0, 0, 0)
        self.user32.mouse_event(up, 0, 0, 0, 0)
        if operation == "double_click":
            self.user32.mouse_event(down, 0, 0, 0, 0)
            self.user32.mouse_event(up, 0, 0, 0, 0)

    def position(self) -> tuple[int, int] | None:
        point = wintypes.POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)


class WindowsPointerAdapter:
    """Map a fresh observation target to one bounded Windows pointer action."""

    def __init__(
        self,
        *,
        foreground_provider: Callable[[], Mapping[str, Any]] | None = None,
        pointer_backend: Any | None = None,
        require_fresh_token: bool = False,
    ) -> None:
        self._foreground = foreground_provider or _Win32Foreground()
        self._pointer = pointer_backend
        self.require_fresh_token = bool(require_fresh_token)
        if self._pointer is None and os.name == "nt":
            self._pointer = _Win32Pointer()

    def act(self, operation: str, target: Mapping[str, Any], value: str | None = None) -> dict[str, Any]:
        del value
        operation = str(operation or "").strip().casefold()
        if operation not in _OPERATIONS:
            return {"status": "denied", "reason": "unsupported_pointer_operation"}
        if not isinstance(target, Mapping):
            return {"status": "denied", "reason": "pointer_target_required"}

        current = dict(self._foreground())
        if current.get("status") != "verified":
            return {"status": "degraded", "reason": str(current.get("reason") or "foreground_window_unavailable")[:160]}
        if self._pointer is None:
            return {"status": "degraded", "reason": "pointer_requires_windows"}
        current_bounds = _bounds(current.get("bounds"))
        if current_bounds is None:
            return {"status": "degraded", "reason": "foreground_window_has_no_bounds"}

        token = target.get("observation_token")
        if self.require_fresh_token and not isinstance(token, str):
            return {"status": "stale_target", "reason": "fresh_observation_token_required"}
        if token is not None:
            claims = verify_observation_token(token)
            if claims is None:
                return {"status": "stale_target", "reason": "invalid_or_expired_observation_token"}
            if claims["class_name"] != str(current.get("class_name") or "") or claims["bounds"] != list(current_bounds):
                return {"status": "stale_target", "reason": "observation_window_changed"}
            current_hwnd = current.get("hwnd")
            if current_hwnd is not None and int(current_hwnd) != claims["hwnd"]:
                return {"status": "stale_target", "reason": "observation_window_identity_changed"}
            expected_digest = target.get("observation_digest")
            if expected_digest is not None and str(expected_digest).casefold() != claims["digest"]:
                return {"status": "stale_target", "reason": "observation_digest_changed"}

        expected_class = target.get("window_class", target.get("class_name"))
        if expected_class is not None:
            if not isinstance(expected_class, str) or len(expected_class) > 120:
                return {"status": "denied", "reason": "invalid_window_class"}
            if expected_class and expected_class != str(current.get("class_name") or ""):
                return {"status": "stale_target", "reason": "foreground_window_class_changed"}
        expected_bounds = target.get("window_bounds", target.get("bounds"))
        if expected_bounds is not None:
            expected = _bounds(expected_bounds)
            if expected is None:
                return {"status": "denied", "reason": "invalid_window_bounds"}
            if expected != current_bounds:
                return {"status": "stale_target", "reason": "foreground_window_bounds_changed"}

        coordinate_space = str(target.get("coordinate_space") or "screen").strip().casefold()
        if coordinate_space == "image":
            point = self._image_point(target, current_bounds, expected_bounds)
        elif coordinate_space == "screen":
            point = self._screen_point(target)
        else:
            return {"status": "denied", "reason": "unsupported_coordinate_space"}
        if point is None:
            return {"status": "denied", "reason": "invalid_pointer_coordinates"}
        x, y = point
        try:
            self._pointer.perform(operation, x, y)
            actual = self._pointer.position()
        except (OSError, RuntimeError) as exc:
            return {"status": "failed", "reason": str(exc)[:200]}
        cursor_verified = actual == (x, y)
        return {
            "status": "dispatched",
            "operation": operation,
            "coordinate_space": coordinate_space,
            "screen_x": x,
            "screen_y": y,
            "postcondition": {"name": "cursor_at_target", "verified": cursor_verified},
            "verified": False,
        }

    @staticmethod
    def _screen_point(target: Mapping[str, Any]) -> tuple[int, int] | None:
        x = _integer(target.get("x"))
        y = _integer(target.get("y"))
        return (x, y) if x is not None and y is not None else None

    @staticmethod
    def _image_point(
        target: Mapping[str, Any],
        window_bounds: tuple[int, int, int, int],
        expected_bounds: Any,
    ) -> tuple[int, int] | None:
        expected = _bounds(expected_bounds)
        width = _integer(target.get("image_width"))
        height = _integer(target.get("image_height"))
        image_x = _integer(target.get("x"))
        image_y = _integer(target.get("y"))
        if expected is None or expected != window_bounds or width is None or height is None:
            return None
        if width <= 0 or height <= 0 or image_x is None or image_y is None:
            return None
        if image_x < 0 or image_y < 0 or image_x >= width or image_y >= height:
            return None
        left, top, right, bottom = window_bounds
        screen_x = left + min(right - left - 1, int((image_x + 0.5) * (right - left) / width))
        screen_y = top + min(bottom - top - 1, int((image_y + 0.5) * (bottom - top) / height))
        return screen_x, screen_y


__all__ = ["WindowsPointerAdapter"]
