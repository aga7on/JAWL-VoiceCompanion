"""In-memory, one-shot approval queue for policy-sensitive HostOS actions."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .hostos_tools import HostOSExecutor
from .models import ToolRequest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


@dataclass
class _Approval:
    approval_id: str
    request_fingerprint: str
    policy_fingerprint: str
    session_id: str
    tool: str
    risk: str
    created_at: datetime
    expires_at: datetime
    status: str = "pending"


class ApprovalStore:
    """Keep exact, expiring approvals without persisting request arguments."""

    def __init__(self, executor: HostOSExecutor, ttl_seconds: int = 300):
        self.executor = executor
        self.ttl_seconds = max(10, min(int(ttl_seconds), 3600))
        self._records: dict[str, _Approval] = {}

    def request(self, request: ToolRequest, session_id: str) -> dict[str, Any]:
        canonical = self.executor.canonicalize(request)
        decision = self.executor.policy.authorize(canonical, has_approval=False)
        self.executor.policy.record_tool_decision(canonical, decision)
        if decision.status != "approval_required":
            return {
                "status": decision.status,
                "reason": decision.reason,
                "effective_level": int(decision.effective_level),
            }
        created = _now()
        approval = _Approval(
            approval_id=secrets.token_urlsafe(10),
            request_fingerprint=self._request_fingerprint(canonical),
            policy_fingerprint=self._policy_fingerprint(),
            session_id=session_id,
            tool=canonical.tool,
            risk=canonical.risk.value,
            created_at=created,
            expires_at=created + timedelta(seconds=self.ttl_seconds),
        )
        self._records[approval.approval_id] = approval
        self.executor.policy.record_approval_event("APPROVAL_REQUESTED", approval.approval_id, approval.tool)
        return {"status": "approval_required", "approval_id": approval.approval_id, "expires_at": _iso(approval.expires_at)}

    def list(self, session_id: str) -> list[dict[str, Any]]:
        self._expire()
        return [
            {
                "approval_id": item.approval_id,
                "status": item.status,
                "tool": item.tool,
                "risk": item.risk,
                "created_at": _iso(item.created_at),
                "expires_at": _iso(item.expires_at),
                "summary": f"{item.tool} ({item.risk})",
            }
            for item in self._records.values()
            if item.session_id == session_id
        ]

    def decide(self, approval_id: str, session_id: str, approved: bool) -> dict[str, Any]:
        self._expire()
        item = self._records.get(approval_id)
        if item is None or item.session_id != session_id:
            return {"status": "not_found"}
        if item.status != "pending":
            return {"status": item.status, "approval_id": item.approval_id}
        item.status = "approved" if approved else "denied"
        self.executor.policy.record_approval_event(
            "APPROVAL_APPROVED" if approved else "APPROVAL_DENIED",
            item.approval_id,
            item.tool,
        )
        return {"status": item.status, "approval_id": item.approval_id}

    def consume(self, approval_id: str | None, request: ToolRequest, session_id: str) -> dict[str, Any]:
        self._expire()
        if not approval_id:
            return {"approved": False, "reason": "approval_id_required"}
        item = self._records.get(approval_id)
        if item is None or item.session_id != session_id:
            return {"approved": False, "reason": "approval_not_found"}
        canonical = self.executor.canonicalize(request)
        if item.status != "approved":
            return {"approved": False, "reason": f"approval_{item.status}"}
        if item.policy_fingerprint != self._policy_fingerprint():
            item.status = "stale"
            return {"approved": False, "reason": "policy_changed_after_approval"}
        if item.request_fingerprint != self._request_fingerprint(canonical):
            return {"approved": False, "reason": "request_changed_after_approval"}
        decision = self.executor.policy.authorize(canonical, has_approval=True)
        if not decision.allowed:
            return {"approved": False, "reason": decision.reason}
        item.status = "consumed"
        self.executor.policy.record_approval_event("APPROVAL_CONSUMED", item.approval_id, item.tool)
        return {"approved": True, "reason": "exact_one_shot_approval"}

    def _expire(self) -> None:
        now = _now()
        for item in self._records.values():
            if item.status == "pending" and item.expires_at <= now:
                item.status = "expired"

    def _policy_fingerprint(self) -> str:
        payload = json.dumps(
            self.executor.policy.snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _request_fingerprint(request: ToolRequest) -> str:
        payload = {
            "tool": request.tool,
            "risk": request.risk.value,
            "arguments": request.arguments,
            "target": request.target,
            "requested_access_level": request.requested_access_level,
            "idempotency_key": request.idempotency_key,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

