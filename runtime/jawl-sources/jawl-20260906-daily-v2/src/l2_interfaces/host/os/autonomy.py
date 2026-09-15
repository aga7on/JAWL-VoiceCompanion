"""Shared validation for durable unattended ROOT authority."""

from __future__ import annotations

import math
import time
from typing import Any


ROOT_ACCESS_LEVEL = 3
MAX_AUTONOMY_LEASE_SECONDS = 86400


def validate_root_autonomy_lease(
    payload: object, *, now: float | None = None
) -> dict[str, Any] | None:
    """Return a bounded lease record or ``None`` when it is not trusted.

    The record is deliberately filesystem-portable: the instance supervisor
    can validate it after the JAWL process has crashed, while HostOS remains
    the only writer through its native operator-control path.
    """

    if not isinstance(payload, dict):
        return None
    if (
        payload.get("schema_version") != 1
        or payload.get("active") is not True
        or payload.get("revoked_at") is not None
        or payload.get("access_level") != ROOT_ACCESS_LEVEL
    ):
        return None
    lease_id = payload.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id or len(lease_id) > 64:
        return None
    try:
        issued_at = float(payload["issued_at"])
        expires_at = float(payload["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    current = time.time() if now is None else float(now)
    if not all(math.isfinite(value) for value in (issued_at, expires_at, current)):
        return None
    if (
        expires_at <= current
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_AUTONOMY_LEASE_SECONDS
    ):
        return None
    actor = payload.get("actor", "operator")
    return {
        "schema_version": 1,
        "active": True,
        "access_level": ROOT_ACCESS_LEVEL,
        "lease_id": lease_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "actor": str(actor or "operator")[:80],
    }
