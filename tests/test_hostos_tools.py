import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.models import AccessLevel, RiskClass, ToolRequest  # noqa: E402


class HostOSToolTests(unittest.TestCase):
    def test_screen_observation_is_policy_gated_and_uses_adapter(self):
        class FakeScreen:
            def observe(self, *, include_image):
                return {"status": "verified", "include_image": include_image, "persisted": False}

        with tempfile.TemporaryDirectory() as directory:
            policy = HostOSPolicy(active_level=AccessLevel.OBSERVER)
            executor = HostOSExecutor(
                policy=policy,
                sandbox_root=Path(directory),
                dry_run=False,
                screen_capture=FakeScreen(),
            )
            result = executor.execute(
                ToolRequest(tool="screen.observe", risk=RiskClass.OBSERVE)
            )
            self.assertEqual(result["status"], "verified")
            self.assertTrue(result["result"]["include_image"])
            self.assertFalse(result["result"]["persisted"])

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

    def test_conditional_workspace_write_rejects_stale_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            executor = HostOSExecutor(
                HostOSPolicy(active_level=AccessLevel.OPERATOR),
                root / "sandbox",
                workspace_roots=(root,),
                host_roots=(root,),
                dry_run=False,
            )
            initial = executor.execute(ToolRequest(
                tool="filesystem.write",
                risk=RiskClass.WORKSPACE_WRITE,
                arguments={"path": str(path), "text": "original"},
            ))
            self.assertEqual(initial["status"], "verified")
            snapshot = executor.execute(ToolRequest(
                tool="filesystem.read",
                risk=RiskClass.OBSERVE,
                arguments={"path": str(path)},
            ))
            path.write_text("external change", encoding="utf-8")
            stale = executor.execute(ToolRequest(
                tool="filesystem.write",
                risk=RiskClass.WORKSPACE_WRITE,
                arguments={
                    "path": str(path),
                    "text": "agent overwrite",
                    "expected_sha256": snapshot["result"]["sha256"],
                },
            ))
            self.assertEqual(stale["status"], "stale_file")
            self.assertEqual(path.read_text(encoding="utf-8"), "external change")

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

    def test_emergency_stop_cancels_running_shell_process(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = HostOSPolicy(active_level=AccessLevel.ROOT)
            policy.set_unattended(True)
            executor = HostOSExecutor(policy, Path(directory), dry_run=False)
            result = []
            worker = threading.Thread(
                target=lambda: result.append(executor.execute(ToolRequest(
                    tool="shell.exec",
                    risk=RiskClass.SHELL,
                    arguments={"argv": [sys.executable, "-c", "import time; time.sleep(30)"]},
                ))),
                daemon=True,
            )
            worker.start()
            for _ in range(50):
                if executor._processes:
                    break
                time.sleep(0.02)
            state = executor.activate_emergency_stop(actor="test")
            worker.join(timeout=2)
            self.assertTrue(state["stopped_processes"])
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
