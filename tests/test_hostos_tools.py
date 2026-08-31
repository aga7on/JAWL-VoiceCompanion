import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.models import AccessLevel, RiskClass, ToolRequest  # noqa: E402


class HostOSToolTests(unittest.TestCase):
    def test_sandbox_read_write_are_real_only_when_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory) / "sandbox"
            sandbox.mkdir()
            executor = HostOSExecutor(
                policy=HostOSPolicy(),
                sandbox_root=sandbox,
                dry_run=False,
            )
            write = executor.execute(
                ToolRequest(
                    tool="sandbox.write",
                    risk=RiskClass.WORKSPACE_WRITE,
                    arguments={"path": "note.txt", "text": "hello"},
                )
            )
            self.assertEqual(write["status"], "verified")
            read = executor.execute(
                ToolRequest(
                    tool="sandbox.read",
                    risk=RiskClass.OBSERVE,
                    arguments={"path": "note.txt"},
                )
            )
            self.assertEqual(read["result"]["text"], "hello")

    def test_path_traversal_is_rejected_after_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory) / "sandbox"
            sandbox.mkdir()
            executor = HostOSExecutor(HostOSPolicy(), sandbox, dry_run=False)
            result = executor.execute(
                ToolRequest(
                    tool="sandbox.write",
                    risk=RiskClass.WORKSPACE_WRITE,
                    arguments={"path": "../escape.txt", "text": "blocked"},
                )
            )
            self.assertEqual(result["status"], "denied")
            self.assertFalse((Path(directory) / "escape.txt").exists())

    def test_registry_risk_overrides_model_supplied_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = HostOSExecutor(
                policy=HostOSPolicy(active_level=AccessLevel.SANDBOX),
                sandbox_root=Path(directory),
                dry_run=True,
            )
            result = executor.execute(
                ToolRequest(tool="shell.exec", risk=RiskClass.OBSERVE, arguments={"argv": ["whoami"]})
            )
            self.assertEqual(result["status"], "denied")
            self.assertEqual(result["reason"], "requires_access_level_3")

    def test_shell_requires_approval_even_at_root(self):
        with tempfile.TemporaryDirectory() as directory:
            executor = HostOSExecutor(
                policy=HostOSPolicy(active_level=AccessLevel.ROOT),
                sandbox_root=Path(directory),
                dry_run=True,
            )
            result = executor.execute(
                ToolRequest(tool="shell.exec", risk=RiskClass.SHELL, arguments={"argv": ["whoami"]})
            )
            self.assertEqual(result["status"], "approval_required")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory) / "sandbox"
            sandbox.mkdir()
            executor = HostOSExecutor(HostOSPolicy(), sandbox, dry_run=True)
            result = executor.execute(
                ToolRequest(
                    tool="sandbox.write",
                    risk=RiskClass.WORKSPACE_WRITE,
                    arguments={"path": "note.txt", "text": "must not exist"},
                )
            )
            self.assertEqual(result["status"], "degraded")
            self.assertFalse((sandbox / "note.txt").exists())


if __name__ == "__main__":
    unittest.main()

