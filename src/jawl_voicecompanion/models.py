"""Small, dependency-free models shared by the first vertical slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Mapping
from uuid import uuid4


class AccessLevel(IntEnum):
    """HostOS permission levels, matching the local JAWL model."""

    SANDBOX = 0
    OBSERVER = 1
    OPERATOR = 2
    ROOT = 3

    @classmethod
    def from_value(cls, value: Any) -> "AccessLevel":
        if isinstance(value, bool):
            raise ValueError("access level must be an integer from 0 to 3")
        try:
            return cls(int(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("access level must be an integer from 0 to 3") from exc


class RiskClass(str, Enum):
    OBSERVE = "observe"
    WORKSPACE_WRITE = "workspace_write"
    PROCESS = "process"
    INTERACTIVE = "interactive"
    EXTERNAL_EFFECT = "external_effect"
    DESTRUCTIVE = "destructive"
    SHELL = "shell"

    @classmethod
    def from_value(cls, value: Any) -> "RiskClass":
        try:
            return cls(str(value))
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(f"unknown risk class; expected one of: {allowed}") from exc


@dataclass(frozen=True)
class ToolRequest:
    """A side-effect request. The requested level is never trusted."""

    tool: str
    risk: RiskClass
    arguments: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = "local"
    turn_id: str | None = None
    target: Mapping[str, Any] | None = None
    requested_access_level: int | None = None
    idempotency_key: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ToolRequest":
        if not isinstance(payload.get("tool"), str) or not payload["tool"].strip():
            raise ValueError("tool must be a non-empty string")
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be an object")
        requested = payload.get("requested_access_level")
        if requested is not None:
            requested = int(AccessLevel.from_value(requested))
        return cls(
            tool=payload["tool"].strip(),
            risk=RiskClass.from_value(payload.get("risk", RiskClass.OBSERVE.value)),
            arguments=dict(arguments),
            request_id=str(payload.get("request_id") or uuid4()),
            session_id=str(payload.get("session_id") or "local"),
            turn_id=str(payload["turn_id"]) if payload.get("turn_id") else None,
            target=dict(payload["target"]) if isinstance(payload.get("target"), Mapping) else None,
            requested_access_level=requested,
            idempotency_key=(str(payload["idempotency_key"]) if payload.get("idempotency_key") else None),
        )


@dataclass(frozen=True)
class ToolDecision:
    """The policy result returned before any executor is invoked."""

    status: str
    allowed: bool
    reason: str
    effective_level: AccessLevel
    approval_required: bool = False

