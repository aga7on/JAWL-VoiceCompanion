"""Honor native Goal wake deadlines while retaining immediate event wakeups."""
from dataclasses import dataclass
import importlib
import time

_INSTALL = "__jawl_owned_goal_wakeup_backoff__"
_DUPLICATE_ACTION_MARKER = "previously successful native action batch was proposed again"
_DUPLICATE_RETRY_MARKER = "no-progress-repeat="
_DUPLICATE_RETRY_LIMIT = 6
_DUPLICATE_BACKOFF_CAP_SECONDS = 60


@dataclass(frozen=True)
class Installation:
    manager_class: type
    wrapped_should_run: object
    wrapped_seconds_until: object
    wrapped_mark_event: object
    wrapped_finish_cycle: object


def install_native_goal_wakeup_backoff(manager_class=None):
    if manager_class is None:
        manager_class = importlib.import_module("src.l3_agent.goals.manager").GoalManager
    existing = vars(manager_class).get(_INSTALL)
    if existing is not None:
        if (manager_class.should_run_heartbeat is existing.wrapped_should_run
                and manager_class.seconds_until_wakeup is existing.wrapped_seconds_until
                and manager_class.mark_event_pending is existing.wrapped_mark_event
                and manager_class.finish_cycle is existing.wrapped_finish_cycle):
            return existing
        raise RuntimeError("native Goal wakeup backoff hook was replaced")

    original_should_run = manager_class.should_run_heartbeat
    original_seconds_until = manager_class.seconds_until_wakeup
    original_mark_event = manager_class.mark_event_pending
    original_finish_cycle = manager_class.finish_cycle

    def duplicate_counts(manager):
        counts = getattr(manager, "_jawl_duplicate_action_counts", None)
        if counts is None:
            counts = {}
            setattr(manager, "_jawl_duplicate_action_counts", counts)
        return counts

    def should_run(manager, now=None):
        goal = getattr(manager, "active_goal", None)
        if goal is None:
            return True
        current = time.time() if now is None else float(now)
        wake = getattr(goal, "next_wakeup_at", None)
        if wake is not None:
            if float(wake) > current:
                return False
        return original_should_run(manager, now)

    def seconds_until(manager, now=None):
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

    async def mark_event(manager, event_name):
        # An external event is an explicit reason to resume early. HEARTBEAT
        # itself must leave the persisted backoff deadline intact.
        if event_name != "HEARTBEAT":
            goal = getattr(manager, "active_goal", None)
            if goal is not None:
                goal.next_wakeup_at = None
                duplicate_counts(manager).pop(str(getattr(goal, "goal_id", "")), None)
        return await original_mark_event(manager, event_name)

    async def finish_cycle(
        manager, *, state, summary="", wake_after_seconds=None
    ):
        goal = getattr(manager, "active_goal", None)
        goal_id = str(getattr(goal, "goal_id", "")) if goal is not None else ""
        counts = duplicate_counts(manager)
        summary_text = str(summary or "")
        is_duplicate = (
            state == "continue"
            and _DUPLICATE_ACTION_MARKER in summary_text.casefold()
        )
        if is_duplicate and goal_id:
            previous = counts.get(goal_id, 0)
            retries = previous + 1
            counts[goal_id] = retries
            if retries >= _DUPLICATE_RETRY_LIMIT:
                counts.pop(goal_id, None)
                return await original_finish_cycle(
                    manager,
                    state="blocked",
                    summary=(
                        "Repeated identical successful native action batch without "
                        f"Goal progress ({retries} consecutive retries). Automatic "
                        "execution is paused; operator review is required."
                    ),
                    wake_after_seconds=None,
                )
            delay = min(2 ** (retries - 1), _DUPLICATE_BACKOFF_CAP_SECONDS)
            summary_text = (
                "A previously successful native action batch was proposed again; "
                "it was not re-executed. Review the recorded result and emit Goal "
                "Protocol v2 state=done or a new evidence-backed action. "
                f"{_DUPLICATE_RETRY_MARKER}{retries}; next retry in {delay}s."
            )
            wake_after_seconds = delay
        elif goal_id:
            counts.pop(goal_id, None)
        return await original_finish_cycle(
            manager,
            state=state,
            summary=summary_text,
            wake_after_seconds=wake_after_seconds,
        )

    installation = Installation(
        manager_class, should_run, seconds_until, mark_event, finish_cycle
    )
    manager_class.should_run_heartbeat = should_run
    manager_class.seconds_until_wakeup = seconds_until
    manager_class.mark_event_pending = mark_event
    manager_class.finish_cycle = finish_cycle
    setattr(manager_class, _INSTALL, installation)
    return installation
