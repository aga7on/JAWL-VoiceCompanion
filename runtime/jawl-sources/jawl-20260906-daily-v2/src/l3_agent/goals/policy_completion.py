"""End a correlated request after native HostOS authority denies an action.

Observe the native security check, never reimplement its policy or interpret
tool output text. Native journals still record the failed attempt. Remaining
actions in the same batch cannot run after the denial. Durable goals and
uncorrelated autonomous cycles retain native behavior.
"""

from __future__ import annotations

from typing import Any, Set

from src.l3_agent.companion_gateway import current_companion_turn_id
from src.utils.event.registry import Events
from src.utils.policy_denial import (
    attempt_denied,
    observe_native_policy_deny,
    skill_attempt,
)

NATIVE_POLICY_DENIAL_REASON = (
    "Native HostOS policy denied the action; the request was stopped."
)
STOPPED_MESSAGE = "Request stopped after native HostOS policy denial."

# Per-request latch keyed by companion turn id: parallel turns never inherit
# each other's denials, and uncorrelated autonomous cycles have no latch at
# all (they retain native failure behavior and keep their next actions).
_DENIED_REQUESTS: Set[str] = set()


def native_policy_denied() -> bool:
    """Whether the active correlated request already recorded a denial."""

    turn_id = current_companion_turn_id()
    return bool(turn_id) and turn_id in _DENIED_REQUESTS


def record_native_policy_denial() -> bool:
    """Record a native denial for the active correlated request.

    Called only where native authority raises (via the attempt mark).
    Returns whether the request must stop; uncorrelated autonomous cycles
    retain native failure behavior.
    """

    turn_id = current_companion_turn_id()
    if not turn_id:
        return False
    _DENIED_REQUESTS.add(turn_id)
    return True


def close_request(turn_id: str) -> None:
    """Release the latch when the correlated request finishes."""

    _DENIED_REQUESTS.discard(str(turn_id or "").strip())


async def publish_request_stopped(event_bus: Any, turn_id: str) -> None:
    """Emit the single safe terminal error for a denial-stopped request.

    The reason is a fixed constant: native denial detail (paths, sentinels,
    exception text) never reaches the correlated client.
    """

    await event_bus.publish(
        Events.REACT_TICK_SAVED,
        companion_turn_id=turn_id,
        companion_gateway_type="turn.error",
        companion_gateway_reason=NATIVE_POLICY_DENIAL_REASON,
    )
    flush = getattr(event_bus, "flush", None)
    if flush is not None:
        await flush(timeout=3.0)


__all__ = [
    "NATIVE_POLICY_DENIAL_REASON",
    "STOPPED_MESSAGE",
    "attempt_denied",
    "close_request",
    "native_policy_denied",
    "observe_native_policy_deny",
    "publish_request_stopped",
    "record_native_policy_denial",
    "skill_attempt",
]
