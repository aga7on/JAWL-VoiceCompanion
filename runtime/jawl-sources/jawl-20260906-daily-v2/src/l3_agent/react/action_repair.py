"""Repair a top-level action object emitted by local 27B models.

On long native prompts the local model sometimes emits a structurally valid
JSON object whose ``tool_name``/``parameters`` keys sit at the top level
instead of inside the ``actions`` array, and spell the terminal-message
argument ``message`` instead of ``text``. The native parser's heuristic
fallback only repairs action *lists*, so these replies collapse into empty
actions and the correlated Companion turn ends without a delivery.

``parse_with_repair`` is invoked natively by ``ReactLoop._parse_response``
and only pre-normalizes the raw answer when the native shape is present
verbatim: the top-level action object is wrapped into ``{"actions": [ ... ]}``
and the single terminal-message argument alias is mapped to ``text``.
Native parsing, policy, discovery and validation remain untouched; a
repaired payload still passes the full native schema path.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from src.l3_agent.context import companion

_TERMINAL_SKILL = "HostTerminalMessages.send_message_to_terminal"
_MAX_REPAIRED_CHARS = 60_000
_PERCEIVED_TYPES: dict[type, type] = {}


def _with_perception(parsed):
    # Resolve through sys.modules so an owning profile can observe the
    # perception seam without monkeypatching this module's import.
    context = sys.modules.get("src.l3_agent.context.companion") or companion
    getter = getattr(context, "current_perception", None)
    perception = getter() if callable(getter) else ""
    if parsed is None or not perception or not hasattr(parsed, "model_dump"):
        return parsed
    base = type(parsed)
    response_type = _PERCEIVED_TYPES.get(base)
    if response_type is None:
        class PerceivedResponse(base):
            perception: str = ""

            @property
            def thoughts(self):
                return f"\n[Perception]: {self.perception}\n" + super().thoughts
        response_type = _PERCEIVED_TYPES[base] = PerceivedResponse
    return response_type.model_validate({**parsed.model_dump(), "perception": perception})


def _top_level_action_object(raw: str) -> dict | None:
    """Return the single top-level action object, or None."""
    clean = str(raw or "").strip()
    if not clean.startswith("{") or not clean.endswith("}") or len(clean) > _MAX_REPAIRED_CHARS:
        return None
    if '"actions"' in clean or '"observation"' in clean or '"reasoning"' in clean:
        return None
    try:
        data = json.loads(clean, strict=False)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if "tool_name" not in data or not isinstance(data.get("tool_name"), str):
        return None
    if "parameters" not in data or not isinstance(data.get("parameters"), dict):
        return None
    extra = {key for key in data if key not in {"tool_name", "parameters"}}
    allowed = {"action_id", "depends_on", "parallel_group", "resources", "name", "arguments"}
    if not extra.issubset(allowed):
        return None
    return data


def _normalize_action(action: dict) -> dict:
    normalized = {
        "tool_name": str(action["tool_name"]),
        "parameters": dict(action["parameters"]),
    }
    if isinstance(action.get("action_id"), str):
        normalized["action_id"] = action["action_id"]
    parameters = normalized["parameters"]
    if (
        normalized["tool_name"] == _TERMINAL_SKILL
        and "text" not in parameters
        and isinstance(parameters.get("message"), str)
    ):
        parameters["text"] = parameters.pop("message")
    return normalized


def repair_raw_answer(raw_answer: str) -> str:
    """Wrap a top-level action object into the canonical envelope shape."""
    action = _top_level_action_object(raw_answer)
    if action is None:
        return str(raw_answer or "")
    envelope = {"actions": [_normalize_action(action)]}
    return json.dumps(envelope, ensure_ascii=False)


def parse_with_repair(loop: Any, raw_answer: str, native_parse: Any):
    """Parse with the top-level action repair fallback; perception is attached."""
    try:
        repaired = repair_raw_answer(raw_answer)
    except Exception:  # noqa: BLE001 - repair must never break native parsing
        repaired = str(raw_answer or "")
    if repaired == raw_answer:
        parsed, error = native_parse(loop, raw_answer)
        return _with_perception(parsed), error
    parsed, error = native_parse(loop, repaired)
    if parsed is not None and getattr(parsed, "actions", None):
        return _with_perception(parsed), error
    # The repair did not help: keep the native result untouched.
    parsed, error = native_parse(loop, raw_answer)
    return _with_perception(parsed), error
