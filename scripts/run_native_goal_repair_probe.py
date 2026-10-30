"""Actual pinned Goal parser/ledger repair contract; no model or side effects."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import uuid4
from copy import deepcopy

from run_owned_jawl_brain import check_isolation, resolve_source, load_extension
from verify_jawl_snapshot import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-probe", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_probe:
        parser.error("pass --allow-probe; no real model or native action will execute")
    check_isolation()
    home = Path(os.environ["JAWL_INSTANCE_HOME"]).resolve()
    if not args.report.resolve().is_relative_to(home) or args.report.exists():
        parser.error("report must be new and inside the selected owned profile")
    source = resolve_source()
    report = {"pass": False, "scope": "actual native parser/validator/ledger patcher, fake SQL/event sinks; no model/actions",
              "snapshot": verify(source)}
    sys.path.insert(0, str(source))
    try:
        from src.l3_agent.react.loop import ReactLoop, _ledger_completion_eligible
        from src.l3_agent.goals.manager import GoalRecord
        from src.l3_agent.goals.ledger import LedgerActionOutcome, apply_ledger_patch
        from src.l3_agent.llm.providers.contracts import RetryPolicy
        extension = load_extension("_goal_repair_contract_probe", "native_goal_completion_repair.py")
        extension.install_native_goal_completion_repair()
        goal = GoalRecord(goal_id=uuid4().hex, objective="fixture", created_at=time.time(),
                          updated_at=time.time(), last_activity_at=time.time())
        before = goal.model_dump()
        ticks = []
        async def save_tick(**value):
            ticks.append(value)
            return "fixture-tick"
        async def publish(*args, **kwargs):
            pass
        loop = object.__new__(ReactLoop)
        loop.goal_manager = SimpleNamespace(active_goal=goal, task_ledger_enabled=True)
        loop.agent_state = SimpleNamespace(current_trace_id=uuid4().hex, current_step=1, max_react_steps=15)
        loop.executor = SimpleNamespace(retry_policy=RetryPolicy(tool_protocol_retries=1), last_call_metrics={})
        loop.sql_ticks = SimpleNamespace(save_tick=save_tick)
        loop.event_bus = SimpleNamespace(publish=publish)
        raw = json.dumps({"v": 2, "state": "done", "calls": [], "summary": "fixture completion",
            "ledger": {"phase": "completed", "completed_add": ["fixture step"],
                       "pending_steps": [], "next_action": "none", "blockers": []}})
        parsed, error = loop._parse_response(raw_answer=raw)
        report["first_parse"] = {"returned_none": parsed is None, "repair_reason": error == extension.REPAIR_REASON,
                                 "goal_unchanged": goal.model_dump() == before}
        if parsed is not None:
            report["first_parse"].update(goal_state=parsed.goal_state, action_count=len(parsed.actions),
                                         ledger_type=type(parsed.ledger).__name__)
            try:
                preview = deepcopy(goal)
                if parsed.ledger is not None:
                    apply_ledger_patch(preview.task_ledger, parsed.ledger)
                report["native_preview_eligible"] = _ledger_completion_eligible(preview)
            except Exception as exc:
                report["native_preview_error"] = type(exc).__name__ + ": " + str(exc)[:200]
        if parsed is not None or error != extension.REPAIR_REASON or goal.model_dump() != before:
            raise RuntimeError("false completion preview changed native durable state")
        asyncio.run(loop._handle_protocol_error(raw, error))
        repeated, error = loop._parse_response(raw)
        repeated_preview = deepcopy(goal)
        if repeated is not None and repeated.ledger is not None:
            apply_ledger_patch(repeated_preview.task_ledger, repeated.ledger)
        if repeated is None or error is not None or _ledger_completion_eligible(repeated_preview):
            raise RuntimeError("repeated false completion bypassed native rejection")
        report.update(one_native_protocol_error=len(ticks) == 1,
                      unchanged_goal_after_false_done=goal.model_dump() == before,
                      repeated_assertion_still_ineligible=True)
        # A valid native action outcome plus terminal patch keeps its original
        # path. The preview must not commit that patch itself.
        goal.task_ledger.last_action_batch = [LedgerActionOutcome(action_id="read", tool="HostOSReader.read_file",
                                                               status="success", evidence_id="fixture")]
        goal.task_ledger.pending_steps = ["verify"]
        valid_before = goal.model_dump()
        loop.agent_state.current_trace_id = uuid4().hex
        valid, error = loop._parse_response(raw)
        if valid is None or error is not None or goal.model_dump() != valid_before:
            raise RuntimeError("valid completion patch was rejected or committed by preview")
        report.update(valid_completion_preserved=True, preview_does_not_commit=True)
        report["pass"] = all(report[key] for key in ("one_native_protocol_error", "unchanged_goal_after_false_done",
                            "repeated_assertion_still_ineligible", "valid_completion_preserved", "preview_does_not_commit"))
    except Exception as exc:
        report["failure"] = type(exc).__name__ + ": " + str(exc)[:200]
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "report": str(args.report)}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
