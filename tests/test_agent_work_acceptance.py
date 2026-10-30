import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_owned_agent_work_acceptance import journal_proof  # noqa: E402


def event(turn_id, name, tool=None, success=None):
    item = {"companion_turn_id": turn_id, "event": name}
    if tool is not None:
        item["tool_name"] = tool
    if success is not None:
        item["is_success"] = success
    return item


class AgentWorkJournalTests(unittest.TestCase):
    def test_read_file_range_satisfies_fresh_file_read(self):
        turn = "turn-r7"
        events = [
            event(turn, "action_started", "HostOSWriter.write_file"),
            event(turn, "action_finished", "HostOSWriter.write_file", True),
            event(turn, "action_started", "HostOSReader.read_file_range"),
            event(turn, "action_finished", "HostOSReader.read_file_range", True),
            event(turn, "action_started", "HostTerminalMessages.send_message_to_terminal"),
        ]
        proof = journal_proof(
            events,
            turn,
            {"HostOSWriter.write_file", "HostOSReader.read_file"},
        )
        self.assertEqual(
            proof["required_tools_completed_before_terminal"],
            ["HostOSReader.read_file", "HostOSWriter.write_file"],
        )

    def test_missing_fresh_read_still_fails(self):
        turn = "turn-missing"
        events = [
            event(turn, "action_started", "HostOSWriter.write_file"),
            event(turn, "action_finished", "HostOSWriter.write_file", True),
            event(turn, "action_started", "HostTerminalMessages.send_message_to_terminal"),
        ]
        with self.assertRaisesRegex(ValueError, "HostOSReader.read_file"):
            journal_proof(events, turn, {"HostOSWriter.write_file", "HostOSReader.read_file"})

    def test_read_after_terminal_does_not_count(self):
        turn = "turn-late"
        events = [
            event(turn, "action_started", "HostOSWriter.write_file"),
            event(turn, "action_finished", "HostOSWriter.write_file", True),
            event(turn, "action_started", "HostTerminalMessages.send_message_to_terminal"),
            event(turn, "action_finished", "HostOSReader.read_file_range", True),
        ]
        with self.assertRaisesRegex(ValueError, "HostOSReader.read_file"):
            journal_proof(events, turn, {"HostOSWriter.write_file", "HostOSReader.read_file"})


if __name__ == "__main__":
    unittest.main()
