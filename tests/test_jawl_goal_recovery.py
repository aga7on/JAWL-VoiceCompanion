import asyncio
import importlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path


class JawlGoalRecoveryTests(unittest.TestCase):
    def test_in_flight_action_is_persisted_and_reconciled_after_restart(self):
        snapshot = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
        )
        old = {
            key: os.environ.get(key)
            for key in (
                "JAWL_INSTANCE_ID",
                "JAWL_LOG_DIR",
                "PYTHONDONTWRITEBYTECODE",
            )
        }
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            os.environ.update(
                {
                    "JAWL_INSTANCE_ID": "goal-recovery-test",
                    "JAWL_LOG_DIR": str(temp_root / "logs"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            sys.path.insert(0, str(snapshot))
            before_modules = set(sys.modules)
            try:
                AgentState = importlib.import_module(
                    "src.l0_state.agent.state"
                ).AgentState
                GoalManager = importlib.import_module(
                    "src.l3_agent.goals.manager"
                ).GoalManager
                TaskLedgerPatch = importlib.import_module(
                    "src.l3_agent.goals.ledger"
                ).TaskLedgerPatch
                ledger_module = importlib.import_module(
                    "src.l3_agent.goals.ledger"
                )
                LedgerActionOutcome = ledger_module.LedgerActionOutcome
                TaskLedger = ledger_module.TaskLedger
                apply_ledger_patch = ledger_module.apply_ledger_patch

                store = temp_root / "data" / "goals.json"
                first = GoalManager(
                    store,
                    AgentState(),
                    recover_on_start=False,
                )

                async def seed() -> None:
                    await first.create("verify a native side effect after restart")
                    await first.record_action_intent(
                        [
                            {
                                "action_id": "write-1",
                                "tool_name": "HostOSWriter.write_file",
                                "parameters": {"filepath": "sandbox/probe.txt"},
                            }
                        ]
                    )

                asyncio.run(seed())
                second = GoalManager(store, AgentState(), recover_on_start=True)
                goal = second.active_goal
                self.assertIsNotNone(goal)
                assert goal is not None
                self.assertTrue(goal.pending_work)
                self.assertEqual(
                    goal.last_cycle_status,
                    "restart_reconciliation_required",
                )
                self.assertEqual(
                    goal.task_ledger.last_action_batch[0].status,
                    "needs_reconciliation",
                )
                self.assertIn("postcondition", goal.task_ledger.next_action)
                self.assertTrue(
                    any(
                        "Uncertain native action outcome" in item
                        for item in goal.task_ledger.blockers
                    )
                )

                async def completion_is_rejected_until_reconciled() -> None:
                    rejected = await second.finish_cycle(
                        state="completed",
                        summary="The provider returned a completion.",
                    )
                    assert rejected is not None
                    self.assertEqual(rejected.status, "active")
                    self.assertEqual(
                        rejected.last_cycle_status,
                        "reconciliation_required",
                    )
                    with self.assertRaises(ValueError):
                        await second.update(
                            status="complete",
                            summary="Operator attempted an unsafe completion.",
                        )

                    with self.assertRaises(ValueError):
                        await second.record_action_intent(
                            [
                                {
                                    "action_id": "write-1",
                                    "tool_name": "HostOSWriter.write_file",
                                }
                            ]
                        )
                    await second.record_action_intent(
                        [
                            {
                                "action_id": "action_1",
                                "tool_name": "HostOSReader.read_file",
                            }
                        ]
                    )
                    await second.record_action_result(
                        "* [action_id=action_1; status=success;] exact marker",
                        actions=[
                            {
                                "action_id": "action_1",
                                "tool_name": "HostOSReader.read_file",
                            }
                        ],
                    )
                    preserved_probe = second.active_goal
                    assert preserved_probe is not None
                    self.assertEqual(
                        [item.status for item in preserved_probe.task_ledger.last_action_batch],
                        ["needs_reconciliation", "success"],
                    )

                    await second.record_action_result(
                        "* [action_id=read-1; status=success;] postcondition=present",
                        actions=[
                            {
                                "action_id": "read-1",
                                "tool_name": "HostOSReader.read_file",
                            }
                        ],
                    )
                    preserved = second.active_goal
                    assert preserved is not None
                    self.assertEqual(
                        preserved.task_ledger.last_action_batch[0].status,
                        "needs_reconciliation",
                    )
                    self.assertEqual(
                        preserved.task_ledger.last_action_batch[0].tool,
                        "HostOSWriter.write_file",
                    )

                    await second.record_ledger_patch(
                        TaskLedgerPatch(
                            reconcile_actions=[
                                {
                                    "action_id": "write-1",
                                    "tool": "HostOSWriter.write_file",
                                    "status": "confirmed",
                                    "evidence": "Independent reader returned the exact marker.",
                                }
                            ],
                            phase="verified",
                        )
                    )
                    completed = await second.finish_cycle(
                        state="completed",
                        summary="Postcondition verified.",
                    )
                    assert completed is not None
                    self.assertEqual(completed.status, "complete")

                asyncio.run(completion_is_rejected_until_reconciled())

                ambiguous = TaskLedger(
                    last_action_batch=[
                        LedgerActionOutcome(
                            action_id="action_1",
                            tool="HostOSWriter.write_file",
                            status="needs_reconciliation",
                            evidence_id="writer-evidence",
                        ),
                        LedgerActionOutcome(
                            action_id="action_1",
                            tool="HostOSReader.read_file",
                            status="needs_reconciliation",
                            evidence_id="reader-evidence",
                        ),
                    ]
                )
                self.assertFalse(
                    apply_ledger_patch(
                        ambiguous,
                        TaskLedgerPatch(
                            reconcile_actions=[
                                {
                                    "action_id": "action_1",
                                    "status": "confirmed",
                                    "evidence": "id-only patch must be rejected as ambiguous",
                                }
                            ]
                        ),
                    )
                )
                self.assertEqual(
                    [item.status for item in ambiguous.last_action_batch],
                    ["needs_reconciliation", "needs_reconciliation"],
                )
                self.assertTrue(
                    apply_ledger_patch(
                        ambiguous,
                        TaskLedgerPatch(
                            reconcile_actions=[
                                {
                                    "action_id": "action_1",
                                    "tool": "HostOSWriter.write_file",
                                    "status": "confirmed",
                                    "evidence": "writer postcondition was independently verified",
                                }
                            ]
                        ),
                    )
                )
                self.assertEqual(
                    [item.status for item in ambiguous.last_action_batch],
                    ["confirmed", "needs_reconciliation"],
                )
            finally:
                logging.shutdown()
                sys.path.pop(0)
                for name in list(sys.modules):
                    if name not in before_modules and (
                        name == "src" or name.startswith("src.")
                    ):
                        sys.modules.pop(name, None)
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
