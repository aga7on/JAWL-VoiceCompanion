"""Optional Windows UI Automation adapter.

The module imports ``uiautomation`` lazily so the rest of the project remains
usable on machines where the optional Windows package is absent.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any


_SENSITIVE_WORDS = (
    "password",
    "пароль",
    "credential",
    "authenticator",
    "bank",
    "битбанк",
    "1password",
)


def control_fingerprint(control: Any) -> str:
    """Create a semantic fingerprint from bounded UIA properties."""
    identity = {
        "name": str(getattr(control, "Name", "") or "")[:240],
        "class_name": str(getattr(control, "ClassName", "") or "")[:120],
        "control_type": str(getattr(control, "ControlTypeName", "") or "")[:120],
        "automation_id": str(getattr(control, "AutomationId", "") or "")[:160],
        "window_handle": int(getattr(control, "NativeWindowHandle", 0) or 0),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _properties(control: Any, max_text_chars: int) -> dict[str, Any]:
    return {
        "name": str(getattr(control, "Name", "") or "")[:max_text_chars],
        "class_name": str(getattr(control, "ClassName", "") or "")[:max_text_chars],
        "control_type": str(getattr(control, "ControlTypeName", "") or "")[:max_text_chars],
        "automation_id": str(getattr(control, "AutomationId", "") or "")[:max_text_chars],
        "window_handle": int(getattr(control, "NativeWindowHandle", 0) or 0),
    }


def _is_sensitive(properties: dict[str, Any]) -> bool:
    text = " ".join(str(value).casefold() for value in properties.values())
    return any(word in text for word in _SENSITIVE_WORDS)


@dataclass
class _ElementReference:
    control: Any
    fingerprint: str
    properties: dict[str, Any]


class WindowsUIAutomationAdapter:
    """Bounded semantic observation and control for the current foreground UI."""

    def __init__(self, max_elements: int = 100, max_text_chars: int = 240):
        self.max_elements = max(1, min(max_elements, 500))
        self.max_text_chars = max(32, min(max_text_chars, 1000))
        self._references: dict[str, _ElementReference] = {}

    def observe(self) -> dict[str, Any]:
        try:
            import uiautomation as automation
            root = automation.GetForegroundControl()
        except ImportError:
            return {"status": "degraded", "reason": "uiautomation_not_installed"}
        except Exception as exc:  # UIA can fail when the desktop is unavailable.
            return {"status": "degraded", "reason": "uia_observation_failed", "detail": str(exc)[:200]}

        if root is None:
            return {"status": "degraded", "reason": "foreground_window_unavailable"}

        self._references.clear()
        queue: list[tuple[Any, int]] = [(root, 0)]
        elements: list[dict[str, Any]] = []
        redacted = False
        while queue and len(elements) < self.max_elements:
            control, depth = queue.pop(0)
            props = _properties(control, self.max_text_chars)
            if _is_sensitive(props):
                redacted = True
                continue
            ref = secrets.token_urlsafe(9)
            fingerprint = control_fingerprint(control)
            self._references[ref] = _ElementReference(control, fingerprint, props)
            elements.append({
                "element_ref": ref,
                "element_sha256": fingerprint,
                "depth": depth,
                **props,
            })
            if depth >= 3:
                continue
            try:
                children = control.GetChildren()
            except Exception:
                children = []
            queue.extend((child, depth + 1) for child in children[: self.max_elements])

        return {
            "status": "verified",
            "window": elements[0] if elements else None,
            "elements": elements,
            "truncated": bool(queue),
            "redacted_sensitive": redacted,
        }

    def act(self, operation: str, target: dict[str, Any], value: str | None = None) -> dict[str, Any]:
        ref = target.get("element_ref")
        expected = target.get("element_sha256")
        if not isinstance(ref, str) or not isinstance(expected, str):
            return {"status": "stale_target", "reason": "element_ref_and_fingerprint_required"}
        record = self._references.get(ref)
        if record is None:
            return {"status": "stale_target", "reason": "unknown_or_expired_element_ref"}
        if expected != record.fingerprint:
            return {"status": "stale_target", "reason": "fingerprint_mismatch"}
        try:
            if hasattr(record.control, "Exists") and not record.control.Exists(0.2, printIfNotExist=False):
                return {"status": "stale_target", "reason": "element_no_longer_exists"}
            current = control_fingerprint(record.control)
        except Exception:
            return {"status": "stale_target", "reason": "element_revalidation_failed"}
        if current != expected:
            return {"status": "stale_target", "reason": "element_changed_before_action"}
        if operation == "click":
            record.control.Click()
            return {"status": "dispatched", "verified": False, "operation": operation}
        if operation == "focus":
            record.control.SetFocus()
            return {"status": "dispatched", "verified": False, "operation": operation}
        if operation == "set_value":
            if not isinstance(value, str) or len(value) > 5000:
                return {"status": "denied", "reason": "bounded_text_value_required"}
            import uiautomation as automation
            pattern = record.control.GetPattern(automation.PatternId.ValuePattern)
            if pattern is None:
                return {"status": "degraded", "reason": "value_pattern_unavailable"}
            verified = bool(pattern.SetValue(value))
            return {"status": "verified" if verified else "dispatched", "verified": verified, "operation": operation}
        return {"status": "denied", "reason": "unsupported_ui_operation"}

