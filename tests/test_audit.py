import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.audit import AuditLog  # noqa: E402
from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402


class AuditLogTests(unittest.TestCase):
    def test_policy_metadata_round_trips_without_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.ndjson"
            log = AuditLog(path)
            policy = HostOSPolicy(audit_sink=log.append)
            policy.set_access_level(3, actor="test")
            log.append({"type": "manual", "payload": {"argv": "must-not-be-written", "tool": "shell.exec"}})

            events = log.events()
            self.assertEqual(events[0]["type"], "ACCESS_LEVEL_CHANGED")
            self.assertEqual(events[-1]["payload"], {"tool": "shell.exec"})
            self.assertNotIn("must-not-be-written", path.read_text(encoding="utf-8"))

    def test_invalid_lines_are_skipped_and_limit_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.ndjson"
            path.write_text('not-json\n{"type":"ok"}\n', encoding="utf-8")
            self.assertEqual(AuditLog(path).events(), [{"type": "ok"}])


if __name__ == "__main__":
    unittest.main()
