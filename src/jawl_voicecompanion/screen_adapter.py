"""Opt-in focused-window capture for the HostOS observation boundary.

This adapter intentionally implements an explicit snapshot only. It does not
start a background capture loop, write image files or retain frames after the
request returns. A later vision bridge can consume the bounded JPEG payload.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import time
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

_DEFAULT_REDACTION_TERMS = (
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
    "api key",
    "ключ",
)

_OBSERVATION_SECRET = secrets.token_bytes(32)


def issue_observation_token(hwnd: int, class_name: str, bounds: list[int], digest: str, ttl_seconds: float = 5.0) -> str:
    """Issue a short-lived signed token bound to one window and frame digest."""
    payload = {
        "v": 1,
        "exp": time.time() + max(1.0, min(float(ttl_seconds), 30.0)),
        "hwnd": int(hwnd),
        "class_name": str(class_name)[:120],
        "bounds": [int(value) for value in bounds],
        "digest": str(digest).casefold(),
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(_OBSERVATION_SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_observation_token(token: str) -> dict[str, Any] | None:
    """Verify signature and expiry without trusting model-supplied window data."""
    if not isinstance(token, str) or len(token) > 1024 or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(_OBSERVATION_SECRET, body.encode("ascii", errors="ignore"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(decoded.decode("utf-8"))
        if payload.get("v") != 1 or float(payload["exp"]) <= time.time():
            return None
        bounds = payload.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            return None
        return {
            "hwnd": int(payload["hwnd"]),
            "class_name": str(payload["class_name"])[:120],
            "bounds": [int(value) for value in bounds],
            "digest": str(payload["digest"]).casefold()[:64],
        }
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScreenCaptureAdapter:
    """Capture one bounded focused window when explicitly enabled."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_width: int = 960,
        max_height: int = 720,
        max_bytes: int = 1_000_000,
        blocked_title_terms: Iterable[str] = _DEFAULT_BLOCKED_TITLE_TERMS,
        ocr_enabled: bool = False,
        ocr_provider: Any | None = None,
        redaction_rects: Iterable[Iterable[int]] = (),
        redaction_terms: Iterable[str] = _DEFAULT_REDACTION_TERMS,
    ) -> None:
        self.enabled = bool(enabled)
        self.max_width = max(320, min(int(max_width), 3840))
        self.max_height = max(240, min(int(max_height), 2160))
        self.max_bytes = max(64_000, min(int(max_bytes), 5_000_000))
        self.blocked_title_terms = tuple(
            str(term).casefold() for term in blocked_title_terms if str(term).strip()
        )
        self.ocr_enabled = bool(ocr_enabled)
        self.ocr_provider = ocr_provider
        self.redaction_rects = tuple(
            rect
            for rect in (self._coerce_rect(value) for value in redaction_rects)
            if rect is not None
        )[:64]
        self.redaction_terms = tuple(
            str(term).casefold() for term in redaction_terms if str(term).strip()
        )

    def profile(self) -> dict[str, Any]:
        """Return the bounded capture profile without exposing local paths."""
        return {
            "max_width": self.max_width,
            "max_height": self.max_height,
            "max_bytes": self.max_bytes,
            "ocr_enabled": self.ocr_enabled,
            "configured_redaction_rects": len(self.redaction_rects),
        }

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
            ocr_items = self._run_ocr(image) if self.ocr_enabled else []
            redaction_rects = list(self.redaction_rects)
            for item in ocr_items:
                text = str(item.get("text") or "").casefold()
                if text and any(term in text for term in self.redaction_terms):
                    rect = self._coerce_rect(item.get("bbox"))
                    if rect is not None:
                        redaction_rects.append(rect)
            self._redact_pixels(image, redaction_rects)
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
        encoded["coordinate_scale"] = {
            "x": round(max(1.0, (right - left) / max(1, encoded["width"])), 4),
            "y": round(max(1.0, (bottom - top) / max(1, encoded["height"])), 4),
        }
        digest = hashlib.sha256(encoded["data_base64"].encode("ascii")).hexdigest()
        result = {
            "status": "verified",
            "captured_at": _now(),
            "source": "focused_window",
            "window": {"class_name": class_name, "bounds": [left, top, right, bottom]},
            "observation_digest": digest,
            "observation_token": issue_observation_token(
                int(hwnd), class_name, [left, top, right, bottom], digest
            ),
            "image": encoded,
            "persisted": False,
        }
        safe_ocr = [
            item
            for item in ocr_items
            if not self._ocr_item_is_redacted(item, redaction_rects)
        ]
        if safe_ocr:
            result["ocr"] = safe_ocr[:64]
        redacted_count = len(redaction_rects)
        if redacted_count:
            result["redacted_regions"] = min(redacted_count, 64)
        return result

    def _is_blocked_window(self, title: str, class_name: str) -> bool:
        haystack = f"{title} {class_name}".casefold()
        return any(term in haystack for term in self.blocked_title_terms)

    @staticmethod
    def _coerce_rect(value: Any) -> tuple[int, int, int, int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
            return None
        left, top, right, bottom = (int(item) for item in value)
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    @classmethod
    def _ocr_item_is_redacted(
        cls, item: dict[str, Any], redaction_rects: Iterable[Iterable[int]]
    ) -> bool:
        item_rect = cls._coerce_rect(item.get("bbox"))
        if item_rect is None:
            return True
        left, top, right, bottom = item_rect
        for raw_rect in redaction_rects:
            rect = cls._coerce_rect(raw_rect)
            if rect is None:
                continue
            r_left, r_top, r_right, r_bottom = rect
            if left < r_right and right > r_left and top < r_bottom and bottom > r_top:
                return True
        return False

    def _run_ocr(self, image: Any) -> list[dict[str, Any]]:
        """Run an optional bounded OCR provider without making it a dependency."""
        provider = self.ocr_provider
        if provider is None:
            try:
                import pytesseract
                from pytesseract import Output
                data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
            except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                return []
            items: list[dict[str, Any]] = []
            texts = data.get("text", [])
            for index, raw_text in enumerate(texts[:128]):
                text = str(raw_text or "").strip()[:240]
                if not text:
                    continue
                try:
                    bbox = (
                        int(data["left"][index]),
                        int(data["top"][index]),
                        int(data["left"][index]) + int(data["width"][index]),
                        int(data["top"][index]) + int(data["height"][index]),
                    )
                    confidence = float(data.get("conf", [0])[index])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if self._coerce_rect(bbox) is not None:
                    items.append({"text": text, "bbox": list(bbox), "confidence": round(max(0.0, confidence), 2)})
            return items[:64]
        try:
            raw_items = provider(image)
        except (OSError, RuntimeError, TypeError, ValueError):
            return []
        if not isinstance(raw_items, (list, tuple)):
            return []
        items = []
        for raw in raw_items[:128]:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()[:240]
            bbox = self._coerce_rect(raw.get("bbox", raw.get("box")))
            if not text or bbox is None:
                continue
            confidence = raw.get("confidence", 0.0)
            try:
                confidence = round(max(0.0, min(100.0, float(confidence))), 2)
            except (TypeError, ValueError):
                confidence = 0.0
            items.append({"text": text, "bbox": list(bbox), "confidence": confidence})
        return items[:64]

    @classmethod
    def _redact_pixels(cls, image: Any, rects: Iterable[Iterable[int]]) -> None:
        """Opaque-redact transient pixels before compression or model upload."""
        width, height = int(image.width), int(image.height)
        try:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
        except ImportError:
            return
        for raw_rect in rects:
            rect = cls._coerce_rect(raw_rect)
            if rect is None:
                continue
            left, top, right, bottom = rect
            left = max(0, min(width, left))
            top = max(0, min(height, top))
            right = max(0, min(width, right))
            bottom = max(0, min(height, bottom))
            if right > left and bottom > top:
                draw.rectangle((left, top, right - 1, bottom - 1), fill=(0, 0, 0))

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
