"""Kernel Goal completion repair for the native JAWL parser.

Spec lineage: the retired product extension ``native_goal_completion_repair``
(ADR-049 slice 8). ``ReactLoop._parse_response`` offers one bounded repair
preview via ``consider_completion_repair``; native completion authority,
durable Goal state and the original rejection path are preserved.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-goalrepair-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l3_agent.goals import completion_repair  # noqa: E402

REPAIR_REASON = completion_repair.REPAIR_REASON


def native_validator():
    source = _SNAPSHOT / "src/l3_agent/react/loop.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_ledger_completion_eligible")
    scope = {"Any": Any}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)
    return scope[function.name]


class GoalCompletionRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.validator = native_validator()

        def patch_ledger(ledger, fields):
            for key, value in fields.items():
                setattr(ledger, key, value)

        self.patch_ledger = patch_ledger

    def parse(self, loop, raw="fixture"):
        # Mirror the native wiring: parse first, then the one repair preview.
        parsed, error = loop._parse_response(raw)
        return completion_repair.consider_completion_repair(
            loop, parsed, error, raw,
            eligible=self.validator, patch_ledger=self.patch_ledger,
        )

    async def handle_error(self, loop, raw, error):
        completion_repair.note_protocol_error(loop)
        return await loop._handle_protocol_error(raw, error)

    def test_opt_in_goal_diagnostic_records_shape_only_inside_owned_profile(self):
        marker = "PRIVATE_GOAL_SENTINEL_7241"
        raw = json.dumps({"v": 2, "state": "act", "calls": [], "private": marker})
        diagnostic = completion_repair.goal_v2_structure_diagnostic(raw)
        self.assertEqual(diagnostic["issue"], "valid_json_structure_unavailable")
        self.assertNotIn(marker, json.dumps(diagnostic))
        safe = completion_repair.goal_v2_payload_diagnostic({"v": 2, "state": "act", "calls": [], "secret": marker})
        self.assertEqual(safe["issue"], "act_requires_call")
        self.assertEqual(safe["unknown_field_count"], 1)
        self.assertNotIn(marker, json.dumps(safe))
        instances = completion_repair.ROOT / "runtime/instances"
        instances.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=instances) as temporary:
            home = Path(temporary)
            logs = home / "logs"
            env = {
                "JAWL_ACCEPTANCE_GOAL_PROTOCOL_DIAGNOSTICS": "1",
                "JAWL_INSTANCE_HOME": str(home),
                "JAWL_LOG_DIR": str(logs),
            }
            with patch.dict(os.environ, env, clear=False):
                completion_repair._record_goal_v2_diagnostic(raw)
            contents = (logs / "goal-protocol-diagnostics.jsonl").read_text("utf-8")
            self.assertIn("valid_json_structure_unavailable", contents)
            self.assertNotIn("private", contents)
            self.assertNotIn(marker, contents)

    def test_goal_diagnostic_classifies_truncated_json_without_copying_text(self):
        marker = "PRIVATE_GOAL_SENTINEL_9918"
        raw = '{"v":2,"state":"act","calls":[{"tool":"x","args":}],"private":"' + marker
        result = completion_repair.goal_v2_structure_diagnostic(
            raw, parse_error="System Error: Invalid JSON format. Details: Unterminated string."
        )
        self.assertEqual(result["issue"], "json_syntax_error")
        self.assertEqual(result["known_protocol_keys_seen"], ["calls", "state", "v"])
        self.assertNotIn(marker, json.dumps(result))

    def fixture(self, *, limit=1):
        class Loop:
            def _parse_response(self, raw_answer):
                return self.parsed, self.error

            async def _handle_protocol_error(self, raw, error):
                self.protocol_errors.append(error)

        loop = Loop()
        goal = SimpleNamespace(status='active', task_ledger=SimpleNamespace(current_phase='start', pending_steps=[],
                    next_action='', blockers=[], last_action_batch=[]))
        loop.goal_manager = SimpleNamespace(active_goal=goal, task_ledger_enabled=True)
        loop.agent_state = SimpleNamespace(current_trace_id='trace-one')
        loop.executor = SimpleNamespace(retry_policy=SimpleNamespace(tool_protocol_retries=limit))
        loop.parsed = SimpleNamespace(goal_state='done', actions=[], ledger={'current_phase': 'completed'})
        loop.error = None
        loop.protocol_errors = []
        return loop, goal

    async def test_false_done_gets_one_native_repair_without_mutating_ledger(self):
        loop, goal = self.fixture()
        parsed, error = self.parse(loop, raw='fixture')
        self.assertIsNone(parsed)
        self.assertEqual(error, REPAIR_REASON)
        self.assertEqual(goal.task_ledger.current_phase, 'start')
        self.assertFalse(self.validator(goal))
        await self.handle_error(loop, 'fixture', error)
        # Repeated assertion is returned to the unchanged native rejection path.
        self.assertIs(self.parse(loop)[0], loop.parsed)
        self.assertFalse(self.validator(goal))
        self.assertEqual(len(loop.protocol_errors), 1)

    async def test_valid_done_uses_patched_copy_and_keeps_original_native_transition(self):
        loop, goal = self.fixture()
        goal.task_ledger.pending_steps = ['verify']
        goal.task_ledger.last_action_batch = [SimpleNamespace(tool='HostOSReader.read_file', status='success')]
        loop.parsed.ledger = {'current_phase': 'completed', 'pending_steps': []}
        self.assertEqual(self.parse(loop), (loop.parsed, None))
        self.assertEqual(goal.task_ledger.pending_steps, ['verify'])
        self.assertEqual(goal.task_ledger.current_phase, 'start')

    async def test_exhausted_budget_actionful_response_and_explicit_block_are_unchanged(self):
        loop, _ = self.fixture()
        await self.handle_error(loop, 'invalid-json', 'native syntax error')
        self.assertEqual(self.parse(loop), (loop.parsed, None))
        for limit in (0,):
            loop, _ = self.fixture(limit=limit)
            self.assertEqual(self.parse(loop), (loop.parsed, None))
        for state, actions in [('act', []), ('blocked', []), ('done', [object()])]:
            loop, _ = self.fixture()
            loop.parsed.goal_state, loop.parsed.actions = state, actions
            self.assertEqual(self.parse(loop), (loop.parsed, None))

    async def test_trace_reset_and_non_goal_or_invalid_trace_have_no_hidden_state_change(self):
        loop, _ = self.fixture()
        self.assertEqual(self.parse(loop)[1], REPAIR_REASON)
        self.assertIsNone(self.parse(loop)[1])
        loop.agent_state.current_trace_id = 'trace-two'
        self.assertEqual(self.parse(loop)[1], REPAIR_REASON)
        for kind in ['no_goal', 'bad_trace', 'disabled_ledger', 'syntax_error']:
            loop, _ = self.fixture()
            if kind == 'no_goal':
                loop.goal_manager.active_goal = None
            elif kind == 'bad_trace':
                loop.agent_state.current_trace_id = ''
            elif kind == 'disabled_ledger':
                loop.goal_manager.task_ledger_enabled = False
            else:
                loop.error = 'native syntax error'
            self.assertEqual(self.parse(loop), (loop.parsed, loop.error))

    def test_loop_wires_the_repair_natively(self):
        source = (_SNAPSHOT / "src/l3_agent/react/loop.py").read_text(encoding="utf-8")
        self.assertIn("completion_repair.consider_completion_repair(", source)
        self.assertIn("completion_repair.note_protocol_error(self)", source)
        schema_source = (_SNAPSHOT / "src/l3_agent/skills/schema.py").read_text(encoding="utf-8")
        self.assertIn("completion_repair.record_goal_v2_payload_diagnostic(data)", schema_source)


if __name__ == "__main__":
    unittest.main()
