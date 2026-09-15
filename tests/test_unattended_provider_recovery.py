import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_unattended_provider_recovery import (
    goal_action,
    marker_write_evidence,
    relay_command_matches,
    successful_marker_writes,
)


class UnattendedProviderRecoveryTests(unittest.TestCase):
    def test_marker_evidence_excludes_idempotent_retries(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp) / "action_journal.jsonl"
            entries = [
                {
                    "event": "action_started", "plan_id": "p", "action_id": "a",
                    "tool_name": "HostOSWriter.write_file", "parameters": {"content": "M"},
                },
                {
                    "event": "action_finished", "plan_id": "p", "action_id": "a",
                    "tool_name": "HostOSWriter.write_file", "is_success": True,
                    "message": "idempotent no-op: already present",
                },
                {
                    "event": "action_started", "plan_id": "p2", "action_id": "a2",
                    "tool_name": "HostOSWriter.write_file", "parameters": {"content": "M"},
                },
                {
                    "event": "action_finished", "plan_id": "p2", "action_id": "a2",
                    "tool_name": "HostOSWriter.write_file", "is_success": True,
                    "message": "created",
                },
            ]
            journal.write_text("".join(json.dumps(item) + "\n" for item in entries), encoding="utf-8")
            evidence = marker_write_evidence(journal, "M")
            writes = successful_marker_writes(journal, "M")
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["action_id"], "a2")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["started"]["action_id"], "a2")

    def test_goal_action_matches_action_id_and_tool_together(self):
        goal = {
            "task_ledger": {
                "last_action_batch": [
                    {"action_id": "action_1", "tool": "HostOSReader.read_file", "status": "success"},
                    {"action_id": "action_1", "tool": "HostOSWriter.write_file", "status": "needs_reconciliation"},
                ]
            }
        }
        writer = goal_action(goal, "action_1", "HostOSWriter.write_file")
        self.assertEqual(writer["status"], "needs_reconciliation")
        self.assertIsNone(goal_action(goal, "action_1", "HostOSWriter.delete_file"))

    def test_automatic_stop_accepts_only_the_disposable_relay_port(self):
        command = (
            '"C:\\Python314\\python.exe" scripts\\opencode_header_relay.py '
            '--port 11438 --upstream http://127.0.0.1:11434'
        )
        self.assertTrue(relay_command_matches(command, 11438))
        self.assertFalse(relay_command_matches(command, 11434))
        self.assertFalse(relay_command_matches('python other_server.py --port 11438', 11438))


if __name__ == "__main__":
    unittest.main()
