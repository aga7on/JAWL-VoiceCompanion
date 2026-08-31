import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.hostos_policy import DryRunHostOS, HostOSPolicy  # noqa: E402
from jawl_voicecompanion.models import AccessLevel, RiskClass, ToolRequest  # noqa: E402


class HostOSPolicyTests(unittest.TestCase):
    def test_default_policy_denies_desktop_control(self):
        result = DryRunHostOS(HostOSPolicy()).execute(
            ToolRequest(tool="desktop.act", risk=RiskClass.INTERACTIVE)
        )
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["reason"], "requires_access_level_2")

    def test_observer_can_read_but_cannot_control(self):
        policy = HostOSPolicy(active_level=AccessLevel.OBSERVER)
        observe = ToolRequest(tool="desktop.observe", risk=RiskClass.OBSERVE)
        control = ToolRequest(tool="desktop.act", risk=RiskClass.INTERACTIVE)
        self.assertTrue(policy.authorize(observe).allowed)
        self.assertEqual(policy.authorize(control).status, "denied")

    def test_requested_level_cannot_self_elevate(self):
        policy = HostOSPolicy()
        request = ToolRequest(
            tool="desktop.act",
            risk=RiskClass.INTERACTIVE,
            requested_access_level=3,
        )
        self.assertEqual(policy.authorize(request).status, "denied")
        self.assertEqual(policy.active_level, AccessLevel.SANDBOX)

    def test_operator_control_requires_approval(self):
        policy = HostOSPolicy(active_level=AccessLevel.OPERATOR)
        request = ToolRequest(tool="desktop.act", risk=RiskClass.INTERACTIVE)
        self.assertEqual(policy.authorize(request).status, "approval_required")
        self.assertTrue(policy.authorize(request, has_approval=True).allowed)

    def test_emergency_stop_blocks_even_root(self):
        policy = HostOSPolicy(active_level=AccessLevel.ROOT)
        policy.set_emergency_stop()
        request = ToolRequest(tool="shell.exec", risk=RiskClass.SHELL)
        self.assertEqual(policy.authorize(request, has_approval=True).reason, "emergency_stop_active")

    def test_audit_keeps_metadata_but_not_arguments(self):
        policy = HostOSPolicy(active_level=AccessLevel.OPERATOR)
        request = ToolRequest(
            tool="desktop.act",
            risk=RiskClass.INTERACTIVE,
            arguments={"text": "secret-value"},
        )
        DryRunHostOS(policy).execute(request)
        audit_text = str(policy.audit())
        self.assertIn("desktop.act", audit_text)
        self.assertNotIn("secret-value", audit_text)


if __name__ == "__main__":
    unittest.main()
