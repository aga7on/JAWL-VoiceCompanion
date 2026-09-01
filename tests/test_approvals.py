import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.approvals import ApprovalStore  # noqa: E402
from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.models import AccessLevel, RiskClass, ToolRequest  # noqa: E402


class ApprovalStoreTests(unittest.TestCase):
    def make_store(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        executor = HostOSExecutor(
            policy=HostOSPolicy(active_level=AccessLevel.ROOT),
            sandbox_root=Path(directory.name),
            dry_run=True,
        )
        return ApprovalStore(executor), executor

    def test_approval_is_exact_one_shot_and_redacted(self):
        store, executor = self.make_store()
        request = ToolRequest(
            tool="shell.exec",
            risk=RiskClass.SHELL,
            arguments={"argv": ["echo", "secret-value"]},
        )
        pending = store.request(request, "session-a")
        approval_id = pending["approval_id"]
        self.assertNotIn("secret-value", str(store.list("session-a")))
        self.assertEqual(store.decide(approval_id, "session-a", True)["status"], "approved")
        self.assertTrue(store.consume(approval_id, request, "session-a")["approved"])
        self.assertFalse(store.consume(approval_id, request, "session-a")["approved"])
        self.assertEqual(executor.policy.audit()[-1]["type"], "APPROVAL_CONSUMED")

    def test_modified_request_cannot_reuse_approval(self):
        store, _executor = self.make_store()
        request = ToolRequest(
            tool="shell.exec",
            risk=RiskClass.SHELL,
            arguments={"argv": ["echo", "one"]},
        )
        approval_id = store.request(request, "session-a")["approval_id"]
        store.decide(approval_id, "session-a", True)
        changed = ToolRequest(
            tool="shell.exec",
            risk=RiskClass.SHELL,
            arguments={"argv": ["echo", "two"]},
        )
        result = store.consume(approval_id, changed, "session-a")
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "request_changed_after_approval")

    def test_approved_proposal_executes_once_and_drops_request(self):
        store, executor = self.make_store()
        request = ToolRequest(
            tool="shell.exec",
            risk=RiskClass.SHELL,
            arguments={"argv": ["echo", "secret-value"]},
        )
        approval_id = store.request(request, "session-a")["approval_id"]
        review = store.list("session-a")[0]["review"]
        self.assertEqual(review["arguments"]["argv"][1], "[redacted]")
        store.decide(approval_id, "session-a", True)
        result = store.execute(approval_id, "session-a")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(store.execute(approval_id, "session-a")["status"], "approval_consumed")
        self.assertNotIn("secret-value", str(store.list("session-a")))
        self.assertEqual(executor.policy.audit()[-1]["type"], "TOOL_AUTHORIZATION")

    def test_policy_change_invalidates_approval(self):
        store, executor = self.make_store()
        request = ToolRequest(tool="shell.exec", risk=RiskClass.SHELL, arguments={"argv": ["echo", "x"]})
        approval_id = store.request(request, "session-a")["approval_id"]
        store.decide(approval_id, "session-a", True)
        executor.policy.set_emergency_stop(True)
        result = store.consume(approval_id, request, "session-a")
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "policy_changed_after_approval")


if __name__ == "__main__":
    unittest.main()
