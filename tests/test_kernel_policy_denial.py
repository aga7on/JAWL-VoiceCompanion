"""Kernel policy completion: native HostOS denial stops only the correlated request.

Spec lineage: the retired product extension ``native_policy_completion``
(ADR-049 slice 1). Native authority is observed at its raise point; the
message surface is a fixed constant and never carries denial detail.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-policy-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l2_interfaces.host.os.client import HostOSClient  # noqa: E402
from src.l3_agent.companion_gateway import (  # noqa: E402
    current_companion_turn_id,
    reset_companion_turn_id,
    set_companion_turn_id,
)
from src.l3_agent.goals import policy_completion  # noqa: E402
from src.l3_agent.skills import registry as skill_registry  # noqa: E402
from src.l3_agent.skills.registry import SkillResult  # noqa: E402


class _StubHost:
    """Runs the real denial wrapper over a stubbed native policy body."""

    def _evaluate_security_policies(self, resolved_path, is_write):
        raise PermissionError("PRIVATE_NATIVE_PATH_SENTINEL")

    _check_security_policies = HostOSClient._check_security_policies


class _Bus:
    def __init__(self):
        self.published = []
        self.flushed = None

    async def publish(self, event, **payload):
        self.published.append((event, payload))

    async def flush(self, timeout=None):
        self.flushed = timeout


class PolicyCompletionKernelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._registered = []
        self.addCleanup(self._unregister_all)

    def _unregister_all(self):
        for name in self._registered:
            skill_registry._REGISTRY.pop(name, None)

    def _register(self, name, func):
        skill_registry.register_custom_callable(func, name, "kernel probe", "probe.py")
        self._registered.append(name)

    def test_denial_marks_attempt_at_the_raise_point(self):
        host = _StubHost()
        with policy_completion.skill_attempt():
            self.assertFalse(policy_completion.attempt_denied())
            with self.assertRaises(PermissionError):
                host._check_security_policies("denied", True)
            self.assertTrue(policy_completion.attempt_denied())
        self.assertFalse(policy_completion.attempt_denied())

    async def test_native_denial_stops_batch_and_emits_one_safe_error(self):
        host = _StubHost()
        effects = []

        async def denied_probe(path: str = "denied"):
            try:
                host._check_security_policies(path, True)
            except PermissionError as exc:
                # A skill may swallow the exception; the raise point already
                # marked the attempt.
                return SkillResult.fail(str(exc))
            effects.append(path)
            return SkillResult.ok("done")

        async def write_probe(path: str = "would_write"):
            effects.append(path)
            return SkillResult.ok("done")

        self._register("denied_probe", denied_probe)
        self._register("write_probe", write_probe)

        token = set_companion_turn_id("policy-turn")
        try:
            first = await skill_registry.call_skill("denied_probe", {})
            second = await skill_registry.call_skill("write_probe", {})
        finally:
            policy_completion.close_request(current_companion_turn_id())
            reset_companion_turn_id(token)

        self.assertTrue(first.terminate_loop)
        self.assertTrue(second.terminate_loop)
        self.assertEqual(second.message, policy_completion.STOPPED_MESSAGE)
        self.assertEqual(effects, [])

        bus = _Bus()
        await policy_completion.publish_request_stopped(bus, "policy-turn")
        self.assertEqual(len(bus.published), 1)
        _, payload = bus.published[0]
        self.assertEqual(payload["companion_gateway_type"], "turn.error")
        self.assertEqual(
            payload["companion_gateway_reason"],
            policy_completion.NATIVE_POLICY_DENIAL_REASON,
        )
        self.assertNotIn("PRIVATE_NATIVE_PATH_SENTINEL", str(bus.published))

        # A later request is independent; durable goals were never touched.
        token = set_companion_turn_id("next-turn")
        try:
            third = await skill_registry.call_skill("write_probe", {"path": "later"})
        finally:
            policy_completion.close_request(current_companion_turn_id())
            reset_companion_turn_id(token)
        self.assertFalse(third.terminate_loop)
        self.assertEqual(effects, ["later"])

    async def test_untrusted_failure_text_and_os_errors_do_not_stop_request(self):
        effects = []

        async def spoof_probe(path: str = "spoof"):
            return SkillResult.fail("SANDBOX: Access denied")

        async def os_error_probe(path: str = "os_error"):
            raise PermissionError("PermissionError from actual filesystem")

        async def allowed_probe(path: str = "allowed"):
            effects.append(path)
            return SkillResult.ok("done")

        self._register("spoof_probe", spoof_probe)
        self._register("os_error_probe", os_error_probe)
        self._register("allowed_probe", allowed_probe)

        token = set_companion_turn_id("text-turn")
        try:
            spoof = await skill_registry.call_skill("spoof_probe", {})
            os_error = await skill_registry.call_skill("os_error_probe", {})
            allowed = await skill_registry.call_skill("allowed_probe", {})
        finally:
            policy_completion.close_request(current_companion_turn_id())
            reset_companion_turn_id(token)

        self.assertFalse(spoof.terminate_loop)
        self.assertFalse(os_error.terminate_loop)
        self.assertFalse(allowed.terminate_loop)
        self.assertEqual(effects, ["allowed"])
        self.assertFalse(policy_completion.native_policy_denied())

    async def test_uncorrelated_autonomy_retains_native_failure_and_next_action(self):
        host = _StubHost()
        effects = []

        async def denied_probe(path: str = "denied"):
            try:
                host._check_security_policies(path, True)
            except PermissionError as exc:
                return SkillResult.fail(str(exc))
            effects.append(path)
            return SkillResult.ok("done")

        async def allowed_probe(path: str = "allowed"):
            effects.append(path)
            return SkillResult.ok("done")

        self._register("denied_probe", denied_probe)
        self._register("allowed_probe", allowed_probe)

        self.assertEqual(current_companion_turn_id(), "")
        denied = await skill_registry.call_skill("denied_probe", {})
        self.assertFalse(denied.terminate_loop)
        self.assertFalse(policy_completion.native_policy_denied())
        await skill_registry.call_skill("allowed_probe", {})
        self.assertEqual(effects, ["allowed"])

    async def test_concurrent_turns_do_not_inherit_each_other_denials(self):
        host = _StubHost()
        release = asyncio.Event()
        effects = []
        bus = _Bus()

        async def denied_probe(path: str = "denied"):
            try:
                host._check_security_policies(path, True)
            except PermissionError as exc:
                return SkillResult.fail(str(exc))
            effects.append(path)
            return SkillResult.ok("done")

        async def allowed_probe(path: str = "allowed"):
            effects.append(path)
            return SkillResult.ok("done")

        self._register("denied_probe", denied_probe)
        self._register("allowed_probe", allowed_probe)

        async def run_turn(turn_id, denied_first):
            token = set_companion_turn_id(turn_id)
            try:
                if denied_first:
                    await skill_registry.call_skill("denied_probe", {})
                    release.set()
                else:
                    await release.wait()
                    await skill_registry.call_skill("allowed_probe", {})
                if policy_completion.native_policy_denied():
                    await policy_completion.publish_request_stopped(
                        bus, current_companion_turn_id()
                    )
            finally:
                policy_completion.close_request(current_companion_turn_id())
                reset_companion_turn_id(token)

        await asyncio.gather(run_turn("bad", True), run_turn("good", False))
        self.assertEqual(effects, ["allowed"])
        self.assertEqual(len(bus.published), 1)
        _, payload = bus.published[0]
        self.assertEqual(payload["companion_turn_id"], "bad")
        self.assertEqual(
            payload["companion_gateway_reason"],
            policy_completion.NATIVE_POLICY_DENIAL_REASON,
        )

    def test_kernel_wiring_marks_raises_and_stops_the_request(self):
        loop_src = (_SNAPSHOT / "src" / "l3_agent" / "react" / "loop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("policy_completion.publish_request_stopped", loop_src)
        self.assertIn("policy_completion.close_request", loop_src)
        self.assertIn("policy_completion.native_policy_denied", loop_src)

        registry_src = (
            _SNAPSHOT / "src" / "l3_agent" / "skills" / "registry.py"
        ).read_text(encoding="utf-8")
        self.assertIn("policy_completion.skill_attempt", registry_src)
        self.assertIn("policy_completion.record_native_policy_denial", registry_src)

        client_src = (
            _SNAPSHOT / "src" / "l2_interfaces" / "host" / "os" / "client.py"
        ).read_text(encoding="utf-8")
        self.assertIn("observe_native_policy_deny", client_src)


if __name__ == "__main__":
    unittest.main()
