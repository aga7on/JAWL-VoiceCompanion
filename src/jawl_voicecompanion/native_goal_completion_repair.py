"""Offer one native protocol repair before rejecting a false Goal completion.

Use the pinned validator and ledger patcher on an in-memory copy. Never change
durable Goal state, accept an ineligible completion, or replay native actions.
An exhausted native repair budget or repeated assertion follows the original
native rejection path.
"""
from copy import deepcopy
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
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
_GOAL_V2_DIAGNOSTIC_LIMIT = 128 * 1024
_GOAL_V2_DIAGNOSTIC_RECORD_LIMIT = 32
_GOAL_V2_DIAGNOSTIC_SEEN: set[str] = set()


def goal_v2_structure_diagnostic(raw_answer, parse_error=None):
    """Describe why a compact Goal payload is invalid without retaining values."""
    text = str(raw_answer or "")[:60_000]
    start = text.find('{"observation"')
    if start < 0:
        start = text.find("{")
    end = text.rfind("}")
    candidate = text[start:end + 1] if start >= 0 and end > start else ""
    try:
        json.loads(candidate, strict=False)
        return {"issue": "valid_json_structure_unavailable", "raw_length": len(text)}
    except json.JSONDecodeError as exc:
        known_keys = sorted(set(re.findall(
            r'"(v|state|calls|ledger|actions|goal_state)"\s*:', candidate)
        ))
        return {
            "issue": "json_syntax_error",
            "error_kind": str(exc.msg)[:80],
            "error_position": int(exc.pos),
            "raw_length": len(text),
            "known_protocol_keys_seen": known_keys,
            "parse_error_has_invalid_json_prefix": "Invalid JSON format" in str(parse_error or ""),
        }
    except (TypeError, ValueError):
        pass
    return {"issue": "json_syntax_error", "raw_length": len(text), "parse_error_present": bool(parse_error)}


def goal_v2_payload_diagnostic(payload):
    """Summarize the exact dict rejected by the pinned native v2 validator."""
    fixed = {"v", "state", "calls", "ledger", "note", "summary", "wake_after_seconds"}
    result = {
        "issue": "v2_validation_failure",
        "unknown_field_count": sum(key not in fixed for key in payload),
        "state": payload.get("state") if payload.get("state") in {"act", "continue", "wait", "done", "blocked"} else "invalid_or_missing",
        "calls_type": type(payload.get("calls", [])).__name__,
        "calls_count": len(payload.get("calls", [])) if isinstance(payload.get("calls", []), list) else None,
        "ledger_type": type(payload.get("ledger")).__name__ if "ledger" in payload else "omitted",
        "summary_type": type(payload.get("summary", "")).__name__,
        "note_type": type(payload.get("note", "")).__name__,
    }
    calls = payload.get("calls", [])
    if payload.get("state") == "act" and isinstance(calls, list) and not calls:
        result["issue"] = "act_requires_call"
    elif payload.get("state") in {"done", "wait", "blocked"} and isinstance(calls, list) and calls:
        result["issue"] = "terminal_state_has_calls"
    elif payload.get("state") in {"done", "wait", "blocked"} and not isinstance(payload.get("summary"), str):
        result["issue"] = "terminal_summary_not_string"
    elif not isinstance(calls, list):
        result["issue"] = "calls_not_list"
    elif isinstance(payload.get("ledger"), dict):
        try:
            from src.l3_agent.goals.ledger import TaskLedgerPatch
            TaskLedgerPatch.model_validate(payload["ledger"])
        except Exception as exc:  # noqa: BLE001
            result["issue"] = "ledger_validation_" + type(exc).__name__
    return result

def _record_goal_v2_diagnostic(raw_answer, parse_error=None):
    if os.environ.get("JAWL_ACCEPTANCE_GOAL_PROTOCOL_DIAGNOSTICS") != "1":
        return
    raw_home = os.environ.get("JAWL_INSTANCE_HOME", "")
    raw_log = os.environ.get("JAWL_LOG_DIR", "")
    if not raw_home or not raw_log or not Path(raw_home).is_absolute() or not Path(raw_log).is_absolute():
        return
    home, logs = Path(raw_home).resolve(), Path(raw_log).resolve()
    instances = (Path(__file__).resolve().parents[2] / "runtime/instances").resolve()
    if home == instances or not home.is_relative_to(instances) or not logs.is_relative_to(home):
        return
    path = logs / "goal-protocol-diagnostics.jsonl"
    if path.is_symlink() or (path.exists() and path.stat().st_size >= _GOAL_V2_DIAGNOSTIC_LIMIT):
        return
    try:
        record = goal_v2_structure_diagnostic(raw_answer, parse_error=parse_error)
        signature = json.dumps(record, sort_keys=True)
        if signature in _GOAL_V2_DIAGNOSTIC_SEEN or len(_GOAL_V2_DIAGNOSTIC_SEEN) >= _GOAL_V2_DIAGNOSTIC_RECORD_LIMIT:
            return
        _GOAL_V2_DIAGNOSTIC_SEEN.add(signature)
        line = json.dumps(record, ensure_ascii=True) + "\n"
        if (path.stat().st_size if path.exists() else 0) + len(line.encode("utf-8")) > _GOAL_V2_DIAGNOSTIC_LIMIT:
            return
        logs.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)
    except Exception:
        return


def _record_goal_v2_payload_diagnostic(payload):
    if os.environ.get("JAWL_ACCEPTANCE_GOAL_PROTOCOL_DIAGNOSTICS") != "1":
        return
    raw_home, raw_log = os.environ.get("JAWL_INSTANCE_HOME", ""), os.environ.get("JAWL_LOG_DIR", "")
    if not raw_home or not raw_log or not Path(raw_home).is_absolute() or not Path(raw_log).is_absolute():
        return
    home, logs = Path(raw_home).resolve(), Path(raw_log).resolve()
    instances = (Path(__file__).resolve().parents[2] / "runtime/instances").resolve()
    if home == instances or not home.is_relative_to(instances) or not logs.is_relative_to(home):
        return
    path = logs / "goal-protocol-diagnostics.jsonl"
    try:
        record = goal_v2_payload_diagnostic(payload)
        signature = json.dumps(record, sort_keys=True)
        if signature in _GOAL_V2_DIAGNOSTIC_SEEN or len(_GOAL_V2_DIAGNOSTIC_SEEN) >= _GOAL_V2_DIAGNOSTIC_RECORD_LIMIT:
            return
        if path.is_symlink() or (path.exists() and path.stat().st_size >= _GOAL_V2_DIAGNOSTIC_LIMIT):
            return
        _GOAL_V2_DIAGNOSTIC_SEEN.add(signature)
        line = json.dumps(record, ensure_ascii=True) + "\n"
        if (path.stat().st_size if path.exists() else 0) + len(line.encode("utf-8")) > _GOAL_V2_DIAGNOSTIC_LIMIT:
            return
        logs.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)
    except Exception:
        return


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

    # Instrument the exact object received by the pinned native validator.
    # Do not wrap fake classes used by unit tests.
    if eligible is not None and loop_class.__module__.startswith("src.l3_agent"):
        schema = importlib.import_module("src.l3_agent.skills.schema")
        original_payload = schema._goal_v2_payload
        def payload_probe(data):
            parsed = original_payload(data)
            if parsed is None and isinstance(data, dict) and data.get("v") == 2:
                _record_goal_v2_payload_diagnostic(data)
            return parsed
        schema._goal_v2_payload = payload_probe

    def parse(loop, raw_answer):
        parsed, error = original_parse(loop, raw_answer)
        if isinstance(error, str) and "Invalid JSON format" in error:
            _record_goal_v2_diagnostic(raw_answer, parse_error=error)
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
