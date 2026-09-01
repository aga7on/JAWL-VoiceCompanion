"""In-memory, one-shot approval queue for policy-sensitive HostOS actions."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .hostos_tools import HostOSExecutor
from .models import ToolRequest


_SENSITIVE_KEY = re.compile(r"(?:pass(?:word)?|secret|token|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
_SENSITIVE_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|"
    r"(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+|"
    r"(?:password|secret|token)[_-][A-Za-z0-9._-]{3,})",
    re.I,
)
_MAX_REVIEW_STRING = 240


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
    request: ToolRequest | None = None
    review: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


class ApprovalStore:
    """Keep exact, expiring approvals without persisting request arguments."""

    def __init__(self, executor: HostOSExecutor, ttl_seconds: int = 300):
        self.executor = executor
        self.ttl_seconds = max(10, min(int(ttl_seconds), 3600))
        self._records: dict[str, _Approval] = {}
        self._lock = threading.RLock()

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
            request=canonical,
            review=self._review(canonical),
        )
        with self._lock:
            self._records[approval.approval_id] = approval
        self.executor.policy.record_approval_event("APPROVAL_REQUESTED", approval.approval_id, approval.tool)
        return {
            "status": "approval_required",
            "approval_id": approval.approval_id,
            "expires_at": _iso(approval.expires_at),
            "review": approval.review,
        }

    def list(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
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
                    "review": item.review,
                }
                for item in self._records.values()
                if item.session_id == session_id
            ]

    def decide(self, approval_id: str, session_id: str, approved: bool) -> dict[str, Any]:
        with self._lock:
            self._expire()
            item = self._records.get(approval_id)
            if item is None or item.session_id != session_id:
                return {"status": "not_found"}
            if item.status != "pending":
                return {"status": item.status, "approval_id": item.approval_id}
            item.status = "approved" if approved else "denied"
            if not approved:
                item.request = None
            self.executor.policy.record_approval_event(
                "APPROVAL_APPROVED" if approved else "APPROVAL_DENIED",
                item.approval_id,
                item.tool,
            )
            return {"status": item.status, "approval_id": item.approval_id}

    def execute(self, approval_id: str, session_id: str) -> dict[str, Any]:
        """Execute an approved in-memory proposal once, then drop its request."""
        with self._lock:
            self._expire()
            item = self._records.get(approval_id)
            if item is None or item.session_id != session_id:
                return {"status": "not_found"}
            if item.status != "approved":
                return {"status": f"approval_{item.status}", "approval_id": item.approval_id}
            request = item.request
            if request is None:
                return {"status": "approval_consumed", "approval_id": item.approval_id}
            approval = self.consume(approval_id, request, session_id)
            if not approval["approved"]:
                return {"status": approval["reason"], "approval_id": item.approval_id}
            try:
                return self.executor.execute(request, has_approval=True)
            finally:
                item.request = None

    def consume(self, approval_id: str | None, request: ToolRequest, session_id: str) -> dict[str, Any]:
        with self._lock:
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
                item.request = None
                return {"approved": False, "reason": "policy_changed_after_approval"}
            if item.request_fingerprint != self._request_fingerprint(canonical):
                item.status = "stale"
                item.request = None
                return {"approved": False, "reason": "request_changed_after_approval"}
            decision = self.executor.policy.authorize(canonical, has_approval=True)
            if not decision.allowed:
                item.status = "stale"
                item.request = None
                return {"approved": False, "reason": decision.reason}
            item.status = "consumed"
            self.executor.policy.record_approval_event("APPROVAL_CONSUMED", item.approval_id, item.tool)
            return {"approved": True, "reason": "exact_one_shot_approval"}

    def _expire(self) -> None:
        now = _now()
        for item in self._records.values():
            if item.status == "pending" and item.expires_at <= now:
                item.status = "expired"
                item.request = None

    @staticmethod
    def _review(request: ToolRequest) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "tool": request.tool,
            "risk": request.risk.value,
            "target": ApprovalStore._review_value("target", request.target),
            "arguments": ApprovalStore._review_value("arguments", dict(request.arguments)),
        }

    @classmethod
    def _review_value(cls, key: str, value: Any, depth: int = 0) -> Any:
        if depth > 3 or _SENSITIVE_KEY.search(key):
            return "[redacted]"
        if isinstance(value, str):
            if _SENSITIVE_VALUE.search(value):
                return "[redacted]"
            if key == "text":
                return {
                    "chars": len(value),
                    "preview": value[:_MAX_REVIEW_STRING] + ("…" if len(value) > _MAX_REVIEW_STRING else ""),
                }
            return value[:_MAX_REVIEW_STRING] + ("…" if len(value) > _MAX_REVIEW_STRING else "")
        if isinstance(value, dict):
            return {str(name): cls._review_value(str(name), item, depth + 1) for name, item in list(value.items())[:16]}
        if isinstance(value, (list, tuple)):
            return [cls._review_value(key, item, depth + 1) for item in list(value)[:16]]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:_MAX_REVIEW_STRING]

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
