"""Opt-in focused-window capture for the HostOS observation boundary.

This adapter intentionally implements an explicit snapshot only. It does not
start a background capture loop, write image files or retain frames after the
request returns. A later vision bridge can consume the bounded JPEG payload.
"""

from __future__ import annotations

import base64
import io
import os
from datetime import datetime, timezone
from typing import Any, Iterable


_DEFAULT_BLOCKED_TITLE_TERMS = (
    "password",
    "парол",
    "credential",
    "secret",
    "token",
    "private",
    "приват",
    "bank",
    "банк",
    "2fa",
    "one-time code",
    "jawl avatar",
    "voicecompanion",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScreenCaptureAdapter:
    """Capture one bounded focused window when explicitly enabled."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_width: int = 1920,
        max_height: int = 1200,
        max_bytes: int = 1_500_000,
        blocked_title_terms: Iterable[str] = _DEFAULT_BLOCKED_TITLE_TERMS,
    ) -> None:
        self.enabled = bool(enabled)
        self.max_width = max(320, min(int(max_width), 3840))
        self.max_height = max(240, min(int(max_height), 2160))
        self.max_bytes = max(64_000, min(int(max_bytes), 5_000_000))
        self.blocked_title_terms = tuple(
            str(term).casefold() for term in blocked_title_terms if str(term).strip()
        )

    def observe(self, *, include_image: bool = True) -> dict[str, Any]:
        """Return one focused-window observation without persisting the frame."""
        if not include_image:
            return {
                "status": "degraded",
                "reason": "metadata_only_screen_observation_not_implemented",
                "persisted": False,
            }
        if not self.enabled:
            return {
                "status": "degraded",
                "reason": "screen_observation_disabled",
                "persisted": False,
            }
        if os.name != "nt":
            return {
                "status": "degraded",
                "reason": "focused_window_capture_requires_windows",
                "persisted": False,
            }

        try:
            from PIL import ImageGrab
            import win32gui
        except ImportError:
            return {
                "status": "degraded",
                "reason": "screen_capture_dependencies_unavailable",
                "persisted": False,
            }

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return {"status": "degraded", "reason": "focused_window_unavailable", "persisted": False}

        title = str(win32gui.GetWindowText(hwnd) or "")[:240]
        class_name = str(win32gui.GetClassName(hwnd) or "")[:120]
        if self._is_blocked_window(title, class_name):
            return {
                "status": "denied",
                "reason": "sensitive_or_companion_window_blocked",
                "persisted": False,
            }

        left, top, right, bottom = (int(value) for value in win32gui.GetWindowRect(hwnd))
        if right <= left or bottom <= top:
            return {"status": "degraded", "reason": "focused_window_has_no_bounds", "persisted": False}

        try:
            image = ImageGrab.grab(
                bbox=(left, top, right, bottom),
                all_screens=True,
                include_layered_windows=False,
            ).convert("RGB")
            encoded = self._encode_jpeg(image)
        except (OSError, TypeError, ValueError) as exc:
            return {
                "status": "degraded",
                "reason": "screen_capture_failed",
                "detail": str(exc)[:200],
                "persisted": False,
            }

        # Window title is deliberately not returned: it can contain document
        # names, account identifiers or other user data unrelated to vision.
        return {
            "status": "verified",
            "captured_at": _now(),
            "source": "focused_window",
            "window": {"class_name": class_name, "bounds": [left, top, right, bottom]},
            "image": encoded,
            "persisted": False,
        }

    def _is_blocked_window(self, title: str, class_name: str) -> bool:
        haystack = f"{title} {class_name}".casefold()
        return any(term in haystack for term in self.blocked_title_terms)

    def _encode_jpeg(self, image: Any) -> dict[str, Any]:
        image.thumbnail((self.max_width, self.max_height))
        quality = 72
        encoded_bytes = b""
        while quality >= 40:
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            encoded_bytes = output.getvalue()
            if len(encoded_bytes) <= self.max_bytes:
                break
            quality -= 8
        if len(encoded_bytes) > self.max_bytes:
            raise ValueError("encoded screen image exceeds bounded size")
        return {
            "media_type": "image/jpeg",
            "data_base64": base64.b64encode(encoded_bytes).decode("ascii"),
            "width": int(image.width),
            "height": int(image.height),
            "bytes": len(encoded_bytes),
        }
