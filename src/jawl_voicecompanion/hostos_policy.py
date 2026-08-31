"""HostOS policy gate and dry-run execution boundary.

This module deliberately performs no operating-system action. It is the first
testable seam that real UI Automation, process and filesystem adapters will
implement later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import AccessLevel, RiskClass, ToolDecision, ToolRequest


_RISK_MIN_LEVEL: dict[RiskClass, AccessLevel] = {
    RiskClass.OBSERVE: AccessLevel.OBSERVER,
    RiskClass.WORKSPACE_WRITE: AccessLevel.OPERATOR,
    RiskClass.PROCESS: AccessLevel.OPERATOR,
    RiskClass.INTERACTIVE: AccessLevel.OPERATOR,
    RiskClass.EXTERNAL_EFFECT: AccessLevel.OPERATOR,
    RiskClass.DESTRUCTIVE: AccessLevel.ROOT,
    RiskClass.SHELL: AccessLevel.ROOT,
}

_TOOL_MIN_LEVEL: dict[str, AccessLevel] = {
    "sandbox.read": AccessLevel.SANDBOX,
    "sandbox.write": AccessLevel.SANDBOX,
    "desktop.observe": AccessLevel.OBSERVER,
    "screen.observe": AccessLevel.OBSERVER,
    "desktop.act": AccessLevel.OPERATOR,
    "browser.act": AccessLevel.OPERATOR,
    "process.managed": AccessLevel.OPERATOR,
    "filesystem.write": AccessLevel.OPERATOR,
    "filesystem.delete": AccessLevel.ROOT,
    "shell.exec": AccessLevel.ROOT,
}

_DEFAULT_APPROVALS: dict[RiskClass, bool] = {
    RiskClass.OBSERVE: False,
    RiskClass.WORKSPACE_WRITE: False,
    RiskClass.PROCESS: True,
    RiskClass.INTERACTIVE: True,
    RiskClass.EXTERNAL_EFFECT: True,
    RiskClass.DESTRUCTIVE: True,
    RiskClass.SHELL: True,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HostOSPolicy:
    """Mutable policy state owned by the backend, defaulting to SANDBOX."""

    active_level: AccessLevel = AccessLevel.SANDBOX
    emergency_stop: bool = False
    approvals_required: dict[RiskClass, bool] = field(
        default_factory=lambda: dict(_DEFAULT_APPROVALS)
    )
    _audit: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def set_access_level(self, level: AccessLevel | int, actor: str = "user") -> dict[str, Any]:
        new_level = AccessLevel.from_value(level)
        old_level = self.active_level
        self.active_level = new_level
        self._record(
            "ACCESS_LEVEL_CHANGED",
            {"from": int(old_level), "to": int(new_level), "actor": actor},
        )
        return self.snapshot()

    def set_emergency_stop(self, enabled: bool = True, actor: str = "user") -> dict[str, Any]:
        self.emergency_stop = bool(enabled)
        self._record("EMERGENCY_STOP_CHANGED", {"enabled": self.emergency_stop, "actor": actor})
        return self.snapshot()

    def authorize(self, request: ToolRequest, has_approval: bool = False) -> ToolDecision:
        if self.emergency_stop:
            return ToolDecision(
                status="denied",
                allowed=False,
                reason="emergency_stop_active",
                effective_level=self.active_level,
            )

        # A model can report the level it thinks it needs, but cannot elevate itself.
        required = _TOOL_MIN_LEVEL.get(request.tool, _RISK_MIN_LEVEL[request.risk])
        if self.active_level < required:
            return ToolDecision(
                status="denied",
                allowed=False,
                reason=f"requires_access_level_{int(required)}",
                effective_level=self.active_level,
            )

        needs_approval = self.approvals_required.get(request.risk, True)
        if needs_approval and not has_approval:
            return ToolDecision(
                status="approval_required",
                allowed=False,
                reason="operator_approval_required",
                effective_level=self.active_level,
                approval_required=True,
            )

        return ToolDecision(
            status="allowed",
            allowed=True,
            reason="policy_allowed",
            effective_level=self.active_level,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_level": int(self.active_level),
            "active_name": self.active_level.name,
            "emergency_stop": self.emergency_stop,
            "approvals_required": {key.value: value for key, value in self.approvals_required.items()},
        }

    def audit(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._audit[-limit:])

    def record_tool_decision(self, request: ToolRequest, decision: ToolDecision) -> None:
        """Record metadata only; never persist tool arguments or secrets."""
        self._record(
            "TOOL_AUTHORIZATION",
            {
                "request_id": request.request_id,
                "tool": request.tool,
                "risk": request.risk.value,
                "status": decision.status,
                "effective_level": int(decision.effective_level),
            },
        )

    def _record(self, event_type: str, payload: dict[str, Any]) -> None:
        self._audit.append({"created_at": _now(), "type": event_type, "payload": payload})
        del self._audit[:-100]


class DryRunHostOS:
    """A safe executor used by Phase 1 tests and demos."""

    def __init__(self, policy: HostOSPolicy):
        self.policy = policy

    def execute(self, request: ToolRequest, has_approval: bool = False) -> dict[str, Any]:
        decision = self.policy.authorize(request, has_approval=has_approval)
        self.policy.record_tool_decision(request, decision)
        if not decision.allowed:
            return {
                "schema_version": 1,
                "request_id": request.request_id,
                "status": decision.status,
                "tool": request.tool,
                "reason": decision.reason,
                "effective_level": int(decision.effective_level),
            }
        return {
            "schema_version": 1,
            "request_id": request.request_id,
            "status": "degraded",
            "tool": request.tool,
            "reason": "dry_run_executor_no_os_side_effects",
            "effective_level": int(decision.effective_level),
            "result": {"summary": "Запрос проверен; реальное действие отключено в Phase 1."},
        }
