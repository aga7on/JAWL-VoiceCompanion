import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_unattended_goal_soak import (
    cleanup_cycle_target,
    forbidden_goal_actions,
    journal_cycle_evidence,
    terminal_ledger_evidence,
    wait_for_goal,
)


class UnattendedGoalSoakHarnessTests(unittest.TestCase):
    def test_wait_for_goal_treats_failed_goal_as_terminal(self):
        calls = []

        def request(_port_file, _action, _params, timeout):
            calls.append(timeout)
            return {"goal_id": "failed-goal", "status": "failed"}

        import scripts.run_unattended_goal_soak as harness

        original = harness.control_request
        harness.control_request = request
        try:
            result = wait_for_goal(Path("unused"), "failed-goal", 30, poll_seconds=0.5)
        finally:
            harness.control_request = original
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(calls), 1)

    def test_journal_evidence_is_scoped_to_the_marker_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp) / "action_journal.jsonl"
            entries = [
                {
                    "event": "action_started",
                    "plan_id": "old-plan",
                    "action_id": "action_1",
                    "tool_name": "HostTerminalMessages.send_message_to_terminal",
                    "parameters": {"text": "startup"},
                },
                {
                    "event": "action_started",
                    "plan_id": "target-plan",
                    "action_id": "action_1",
                    "tool_name": "HostOSWriter.write_file",
                    "parameters": {"content": "MARKER"},
                },
                {
                    "event": "action_finished",
                    "plan_id": "target-plan",
                    "action_id": "action_1",
                    "tool_name": "HostOSWriter.write_file",
                    "is_success": True,
                },
                {
                    "event": "action_finished",
                    "plan_id": "old-plan",
                    "action_id": "action_1",
                    "tool_name": "HostOSWriter.write_file",
                    "is_success": True,
                },
                {
                    "event": "action_started",
                    "plan_id": "target-plan",
                    "action_id": "action_2",
                    "tool_name": "HostOSReader.read_file",
                    "parameters": {"filepath": "sandbox/probe.txt"},
                },
                {
                    "event": "action_finished",
                    "plan_id": "target-plan",
                    "action_id": "action_2",
                    "tool_name": "HostOSReader.read_file",
                    "is_success": True,
                },
            ]
            journal.write_text(
                "".join(json.dumps(item) + "\n" for item in entries),
                encoding="utf-8",
            )

            evidence = journal_cycle_evidence(journal, "MARKER")

        self.assertEqual(evidence["action_started_count"], 1)
        self.assertEqual(evidence["action_finished_count"], 2)
        self.assertEqual(evidence["successful_target_writes"], 1)
        self.assertEqual(
            evidence["tools_seen"],
            ["HostOSReader.read_file", "HostOSWriter.write_file"],
        )

    def test_journal_evidence_excludes_idempotent_write_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp) / "action_journal.jsonl"
            entries = [
                {
                    "event": "action_started",
                    "plan_id": "target-plan",
                    "action_id": "write-1",
                    "tool_name": "HostOSWriter.write_file",
                    "parameters": {"content": "MARKER"},
                },
                {
                    "event": "action_finished",
                    "plan_id": "target-plan",
                    "action_id": "write-1",
                    "tool_name": "HostOSWriter.write_file",
                    "is_success": True,
                    "message": "created",
                },
                {
                    "event": "action_started",
                    "plan_id": "target-plan",
                    "action_id": "write-2",
                    "tool_name": "HostOSWriter.write_file",
                    "parameters": {"content": "MARKER"},
                },
                {
                    "event": "action_finished",
                    "plan_id": "target-plan",
                    "action_id": "write-2",
                    "tool_name": "HostOSWriter.write_file",
                    "is_success": True,
                    "message": "True (idempotent no-op; requested content already matched)",
                },
            ]
            journal.write_text(
                "".join(json.dumps(item) + "\n" for item in entries),
                encoding="utf-8",
            )
            evidence = journal_cycle_evidence(journal, "MARKER")

        self.assertEqual(evidence["successful_target_writes"], 1)
        self.assertEqual(evidence["idempotent_noop_writes"], 1)

    def test_forbidden_legacy_goal_action_is_reported(self):
        goal = {
            "evidence": [
                {"kind": "action_intent", "summary": "GoalSkills.update_goal[action_1]"},
            ],
            "task_ledger": {"failed_attempts": []},
        }
        self.assertEqual(forbidden_goal_actions(goal), ["GoalSkills.update_goal"])

    def test_cleanup_cycle_target_skips_missing_fixture_without_native_call(self):
        with tempfile.TemporaryDirectory() as temp:
            disk_file = Path(temp) / "missing.txt"
            result = cleanup_cycle_target(
                base="http://127.0.0.1:2367",
                headers={},
                relative_file="sandbox/missing.txt",
                disk_file=disk_file,
                timeout=1,
            )
        self.assertEqual(result, {"file_absent": True, "delete_skipped": True})

    def test_terminal_ledger_evidence_requires_complete_proof(self):
        goal = {
            "task_ledger": {
                "current_phase": "completed",
                "completed_steps": ["file created and verified"],
                "pending_steps": [],
                "next_action": "none",
                "blockers": [],
                "last_action_batch": [
                    {"tool": "HostOSReader.read_file", "status": "success"},
                ],
            }
        }
        evidence = terminal_ledger_evidence(goal)
        self.assertEqual(evidence["phase"], "completed")
        self.assertTrue(evidence["has_required_step"])
        self.assertTrue(evidence["last_action_batch_all_success"])

    def test_terminal_ledger_evidence_rejects_pending_work(self):
        goal = {
            "task_ledger": {
                "current_phase": "completed",
                "completed_steps": ["file created and verified"],
                "pending_steps": ["finish goal"],
                "next_action": "finish goal",
                "blockers": [],
                "last_action_batch": [
                    {"tool": "HostOSReader.read_file", "status": "success"},
                ],
            }
        }
        evidence = terminal_ledger_evidence(goal)
        self.assertEqual(evidence["pending_steps"], ["finish goal"])
        self.assertEqual(evidence["next_action"], "finish goal")


if __name__ == "__main__":
    unittest.main()
