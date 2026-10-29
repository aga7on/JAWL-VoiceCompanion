"""Honor native Goal wake deadlines while retaining immediate event wakeups.

``GoalManager.should_run_heartbeat``/``seconds_until_wakeup`` gate on the
persisted ``next_wakeup_at`` deadline before native deterministic-wait
semantics; external events clear the deadline early. A repeated identical
successful action batch gets bounded exponential backoff and then blocks for
operator review. Invoked natively by ``GoalManager``; no product extension
layer installs anything.
"""

from __future__ import annotations

import time
from typing import Any, Optional

DUPLICATE_ACTION_MARKER = "previously successful native action batch was proposed again"
DUPLICATE_RETRY_MARKER = "no-progress-repeat="
_DUPLICATE_RETRY_LIMIT = 6
_DUPLICATE_BACKOFF_CAP_SECONDS = 60


def duplicate_counts(manager: Any) -> dict[str, int]:
    counts = getattr(manager, "_jawl_duplicate_action_counts", None)
    if counts is None:
        counts = {}
        setattr(manager, "_jawl_duplicate_action_counts", counts)
    return counts


def should_run(manager: Any, now: Optional[float] = None) -> bool:
    """Deadline-aware heartbeat gate (future deadline suppresses the run)."""
    goal = getattr(manager, "active_goal", None)
    if goal is None:
        return True
    current = time.time() if now is None else float(now)
    wake = getattr(goal, "next_wakeup_at", None)
    if wake is not None and float(wake) > current:
        return False
    # Native deterministic-wait semantics below the deadline gate.
    if not getattr(manager, "suppress_waiting_heartbeats", True):
        return True
    if getattr(goal, "pending_work", False):
        return True
    return wake is not None and float(wake) <= current


def seconds_until(manager: Any, now: Optional[float] = None) -> Optional[float]:
    """Seconds until the persisted wake deadline, or 0.0 for pending work."""
    goal = getattr(manager, "active_goal", None)
    if goal is None:
        return None
    current = time.time() if now is None else float(now)
    wake = getattr(goal, "next_wakeup_at", None)
    if wake is not None:
        return max(0.0, float(wake) - current)
    if getattr(goal, "pending_work", False):
        return 0.0
    return None


def clear_backoff_for_event(manager: Any, event_name: str) -> None:
    """External events are an explicit reason to resume early; HEARTBEAT is not."""
    if event_name == "HEARTBEAT":
        return
    goal = getattr(manager, "active_goal", None)
    if goal is not None:
        goal.next_wakeup_at = None
        duplicate_counts(manager).pop(str(getattr(goal, "goal_id", "")), None)


def apply_duplicate_backoff(
    manager: Any,
    *,
    state: str,
    summary: str = "",
    wake_after_seconds: Optional[int] = None,
) -> tuple[str, str, Optional[int]]:
    """Rewrite a duplicate successful action batch into bounded backoff."""
    goal = getattr(manager, "active_goal", None)
    goal_id = str(getattr(goal, "goal_id", "")) if goal is not None else ""
    counts = duplicate_counts(manager)
    summary_text = str(summary or "")
    is_duplicate = (
        state == "continue"
        and DUPLICATE_ACTION_MARKER in summary_text.casefold()
    )
    if is_duplicate and goal_id:
        previous = counts.get(goal_id, 0)
        retries = previous + 1
        counts[goal_id] = retries
        if retries >= _DUPLICATE_RETRY_LIMIT:
            counts.pop(goal_id, None)
            return (
                "blocked",
                (
                    "Repeated identical successful native action batch without "
                    f"Goal progress ({retries} consecutive retries). Automatic "
                    "execution is paused; operator review is required."
                ),
                None,
            )
        delay = min(2 ** (retries - 1), _DUPLICATE_BACKOFF_CAP_SECONDS)
        summary_text = (
            "A previously successful native action batch was proposed again; "
            "it was not re-executed. Review the recorded result and emit Goal "
            "Protocol v2 state=done or a new evidence-backed action. "
            f"{DUPLICATE_RETRY_MARKER}{retries}; next retry in {delay}s."
        )
        wake_after_seconds = delay
    elif goal_id:
        counts.pop(goal_id, None)
    return state, summary_text, wake_after_seconds
