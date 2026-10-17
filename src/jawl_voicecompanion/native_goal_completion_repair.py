"""Offer one native protocol repair before rejecting a false Goal completion.

Use the pinned validator and ledger patcher on an in-memory copy. Never change
durable Goal state, accept an ineligible completion, or replay native actions.
An exhausted native repair budget or repeated assertion follows the original
native rejection path.
"""
from copy import deepcopy
from dataclasses import dataclass
import importlib
import re

_INSTALL = "__jawl_owned_goal_completion_repair__"
_STATE = "__jawl_owned_goal_protocol_state__"
_TRACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
REPAIR_REASON = (
    "Goal completion is not eligible for the exact active Goal. Earlier Goals "
    "are history, not completion evidence. Use this Goal's native ledger, "
    "complete and verify missing work, preserve confirmed effects, and only "
    "then return state=done."
)


@dataclass
class _Cycle:
    trace: str
    errors: int = 0
    offered: bool = False


@dataclass(frozen=True)
class Installation:
    loop_class: type
    wrapped_parse: object
    wrapped_error: object


def _cycle(loop):
    trace = getattr(getattr(loop, "agent_state", None), "current_trace_id", "")
    if not isinstance(trace, str) or _TRACE.fullmatch(trace) is None:
        return None
    state = getattr(loop, _STATE, None)
    if not isinstance(state, _Cycle) or state.trace != trace:
        state = _Cycle(trace)
        setattr(loop, _STATE, state)
    return state


def install_native_goal_completion_repair(loop_class=None, *, eligible=None, patch_ledger=None):
    if loop_class is None or eligible is None or patch_ledger is None:
        native = importlib.import_module("src.l3_agent.react.loop")
        ledger = importlib.import_module("src.l3_agent.goals.ledger")
        loop_class = loop_class or native.ReactLoop
        eligible = eligible or native._ledger_completion_eligible
        patch_ledger = patch_ledger or ledger.apply_ledger_patch
    existing = vars(loop_class).get(_INSTALL)
    if existing is not None:
        if (loop_class._parse_response is existing.wrapped_parse
                and loop_class._handle_protocol_error is existing.wrapped_error):
            return existing
        raise RuntimeError("native Goal completion repair hook was replaced")
    original_parse = loop_class._parse_response
    original_error = loop_class._handle_protocol_error

    def parse(loop, raw_answer):
        parsed, error = original_parse(loop, raw_answer)
        manager = getattr(loop, "goal_manager", None)
        goal = getattr(manager, "active_goal", None)
        if (error or parsed is None or goal is None or not getattr(manager, "task_ledger_enabled", True)
                or getattr(parsed, "goal_state", "") != "done" or getattr(parsed, "actions", None)):
            return parsed, error
        state = _cycle(loop)
        limit = getattr(getattr(getattr(loop, "executor", None), "retry_policy", None), "tool_protocol_retries", 1)
        limit = limit if isinstance(limit, int) else 1
        if state is None or state.offered or state.errors >= limit:
            return parsed, error
        # This is a preview only. Native record_ledger_patch and the final
        # completion guard retain authority and run on the original path.
        try:
            candidate = deepcopy(goal)
            patch = getattr(parsed, "ledger", None)
            if patch is not None:
                patch_ledger(candidate.task_ledger, patch)
            ready = eligible(candidate)
        except Exception:
            return parsed, error  # preserve the original native error semantics
        if ready:
            return parsed, error
        state.offered = True
        return None, REPAIR_REASON

    async def protocol_error(loop, *args, **kwargs):
        state = _cycle(loop)
        if state is not None:
            state.errors += 1
        return await original_error(loop, *args, **kwargs)

    installation = Installation(loop_class, parse, protocol_error)
    loop_class._parse_response = parse
    loop_class._handle_protocol_error = protocol_error
    setattr(loop_class, _INSTALL, installation)
    return installation
