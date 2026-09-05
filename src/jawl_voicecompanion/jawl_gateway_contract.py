"""Strict client-side boundary for the future native JAWL Companion Gateway.

The current JAWL web console still exposes an untyped POST+SSE compatibility
surface.  This module deliberately only validates the target event contract;
it does not manufacture correlation from legacy broadcasts and it does not
execute tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import re

from .gateway import validate_response_envelope


_EVENT_FIELDS = frozenset({"schema_version", "event_seq", "turn_id", "type", "payload"})
_EVENT_TYPES = frozenset({
    "turn.started",
    "assistant.delta",
    "tool.requested",
    "tool.started",
    "tool.completed",
    "assistant.final",
    "turn.cancelled",
    "turn.error",
})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_PAYLOAD_KEYS = 32
_MAX_TEXT = 16_000
_MAX_SUMMARY = 4_000


def _text(value: Any, field: str, *, allow_empty: bool = False, limit: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if "\x00" in value or len(value) > limit or (not allow_empty and not value.strip()):
        raise ValueError(f"{field} is empty or exceeds its limit")
    return value


def _safe_id(value: Any, field: str) -> str:
    value = _text(value, field)
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


@dataclass(frozen=True, slots=True)
class JawlGatewayEvent:
    """One validated, correlated event from native JAWL."""

    schema_version: int
    event_seq: int
    turn_id: str
    type: str
    payload: dict[str, Any]

    @classmethod
    def from_mapping(cls, event: Mapping[str, Any]) -> "JawlGatewayEvent":
        if not isinstance(event, Mapping):
            raise ValueError("JAWL gateway event must be an object")
        unknown = sorted(set(event) - _EVENT_FIELDS)
        missing = sorted(_EVENT_FIELDS - set(event))
        if missing:
            raise ValueError(f"JAWL gateway event is missing fields: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"JAWL gateway event contains unknown fields: {', '.join(unknown)}")
        version = event["schema_version"]
        if isinstance(version, bool) or version != 1:
            raise ValueError("unsupported JAWL gateway event schema")
        sequence = event["event_seq"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("event_seq must be a non-negative integer")
        turn_id = _safe_id(event["turn_id"], "turn_id")
        event_type = _text(event["type"], "type")
        if event_type not in _EVENT_TYPES:
            raise ValueError("unsupported JAWL gateway event type")
        payload = event["payload"]
        if not isinstance(payload, Mapping) or len(payload) > _MAX_PAYLOAD_KEYS:
            raise ValueError("event payload must be a bounded object")
        payload_copy = dict(payload)
        cls._validate_payload(event_type, payload_copy, turn_id)
        return cls(1, sequence, turn_id, event_type, payload_copy)

    @staticmethod
    def _validate_payload(event_type: str, payload: dict[str, Any], turn_id: str) -> None:
        if event_type == "assistant.delta":
            _text(payload.get("text"), "payload.text", allow_empty=True, limit=_MAX_TEXT)
            return
        if event_type == "assistant.final":
            response = payload.get("response")
            if not isinstance(response, dict):
                raise ValueError("assistant.final payload.response must be an object")
            validate_response_envelope(response)
            if response["turn_id"] != turn_id:
                raise ValueError("assistant.final response turn_id does not match event turn_id")
            return
        if event_type in {"turn.cancelled", "turn.error"}:
            _text(payload.get("reason"), "payload.reason", limit=_MAX_SUMMARY)
            return
        if event_type.startswith("tool."):
            forbidden = {"arguments", "raw_arguments", "credentials", "reasoning"}
            leaked = sorted(forbidden & set(payload))
            if leaked:
                raise ValueError(
                    "tool event contains fields that must stay inside JAWL: "
                    + ", ".join(leaked)
                )
            for field in ("action_id", "tool", "status"):
                if field in payload:
                    _safe_id(payload[field], f"payload.{field}")
            for field in ("summary", "result_summary", "error"):
                if field in payload:
                    _text(payload[field], f"payload.{field}", allow_empty=True, limit=_MAX_SUMMARY)
            return
        for field in ("source", "mode", "summary"):
            if field in payload:
                _text(payload[field], f"payload.{field}", allow_empty=True, limit=_MAX_SUMMARY)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_seq": self.event_seq,
            "turn_id": self.turn_id,
            "type": self.type,
            "payload": dict(self.payload),
        }
