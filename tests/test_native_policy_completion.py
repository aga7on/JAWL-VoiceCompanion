"""Native authority, correlated completion, and batch side effects."""
import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from jawl_voicecompanion import native_jawl_delivery as delivery
from jawl_voicecompanion.native_policy_completion import install_native_policy_completion
from test_native_jawl_delivery import _classes, _install


class PolicyCompletionTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, behavior):
        @dataclass
        class Result:
            is_success: bool
            message: str
            terminate_loop: bool = False

            @classmethod
            def fail(cls, message):
                return cls(False, message)

        class Host:
            checks = 0

            def _check_security_policies(self, path, is_write):
                self.checks += 1
                if path == 'denied':
                    raise PermissionError('PRIVATE_NATIVE_PATH_SENTINEL')

        host = Host()
        effects = []

        async def original(name, params=None):
            if name == 'spoof':
                return Result.fail('SANDBOX: Access denied')
            if name == 'os_error':
                return Result.fail('PermissionError from actual filesystem')
            try:
                host._check_security_policies(name, True)
            except PermissionError as exc:
                return Result.fail(str(exc))
            await asyncio.sleep(0)
            effects.append(name)
            return Result(True, 'done')

        registry = SimpleNamespace(call_skill=original, SkillResult=Result)
        hook = install_native_policy_completion(delivery, Host, registry)
        loop_class, terminal_class, bus_class = _classes(behavior)
        _install(loop_class, terminal_class, bus_class)
        client = terminal_class()
        loop = loop_class(client)
        return registry, host, effects, loop, client, hook

    async def test_native_denial_stops_batch_and_emits_one_safe_error(self):
        results = []

        async def behavior(loop, *args):
            results.append(await registry.call_skill('denied'))
            results.append(await registry.call_skill('would_write'))

        registry, host, effects, loop, client, hook = self.fixture(behavior)
        await loop.run('message', {'_companion_turn_id': 'policy-turn'}, [])
        self.assertEqual(host.checks, 1)
        self.assertEqual(effects, [])
        self.assertTrue(all(r.terminate_loop for r in results))
        self.assertEqual(len(client.events), 1)
        self.assertEqual(client.events[0]['type'], 'turn.error')
        self.assertEqual(client.events[0]['payload']['reason'], delivery.NATIVE_POLICY_DENIAL_REASON)
        self.assertNotIn('PRIVATE_NATIVE_PATH_SENTINEL', str(client.events))
        self.assertIs(install_native_policy_completion(delivery, hook.host_class, registry), hook)
        # A later request is independent; durable goals were never touched.
        loop.behavior = lambda *args: registry.call_skill('allowed_next_turn')
        await loop.run('message', {'_companion_turn_id': 'next-turn'}, [])
        self.assertEqual(effects, ['allowed_next_turn'])

    async def test_untrusted_failure_text_and_os_errors_do_not_stop_native_loop(self):
        results = []

        async def behavior(loop, *args):
            for name in ('spoof', 'os_error', 'allowed'):
                results.append(await registry.call_skill(name))

        registry, host, effects, loop, client, _ = self.fixture(behavior)
        await loop.run('message', {'_companion_turn_id': 'text-turn'}, [])
        self.assertTrue(all(not r.terminate_loop for r in results))
        self.assertEqual(effects, ['allowed'])
        self.assertNotEqual(client.events[0]['payload']['reason'], delivery.NATIVE_POLICY_DENIAL_REASON)

    async def test_uncorrelated_autonomy_retains_native_failure_and_next_action(self):
        registry, host, effects, loop, client, _ = self.fixture(None)
        result = await registry.call_skill('denied')
        self.assertFalse(result.terminate_loop)
        await registry.call_skill('allowed')
        self.assertEqual(effects, ['allowed'])
        self.assertEqual(client.events, [])

    async def test_native_active_goal_retains_reasoning_budget_when_state_changes(self):
        observed = []

        async def behavior(loop, *args):
            observed.append(delivery.native_companion_chat_active())
            loop.goal_manager = SimpleNamespace(active_goal=object())
            observed.append(delivery.native_companion_chat_active())

        _, _, _, loop, _, _ = self.fixture(behavior)
        self.assertFalse(delivery.native_companion_chat_active())
        await loop.run('message', {'_companion_turn_id': 'scope'}, [])
        self.assertEqual(observed, [True, False])
        self.assertFalse(delivery.native_companion_chat_active())

    async def test_concurrent_turn_does_not_inherit_other_turn_denial(self):
        release = asyncio.Event()

        async def behavior(loop, event, payload, missed):
            if payload['_companion_turn_id'] == 'bad':
                await registry.call_skill('denied')
                release.set()
            else:
                await release.wait()
                await registry.call_skill('allowed')

        registry, host, effects, loop, client, _ = self.fixture(behavior)
        await asyncio.gather(loop.run('message', {'_companion_turn_id': 'bad'}, []),
                             loop.run('message', {'_companion_turn_id': 'good'}, []))
        self.assertEqual(effects, ['allowed'])
        self.assertEqual(sum(e['payload']['reason'] == delivery.NATIVE_POLICY_DENIAL_REASON for e in client.events), 1)
