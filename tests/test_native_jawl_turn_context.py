import ast
import asyncio
from contextvars import ContextVar
import sys
import unittest
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.native_jawl_turn_context import (  # noqa: E402
    install_native_jawl_turn_context,
)


class Section(IntEnum):
    INTERFACES = 50
    HEARTBEAT = 160


class Registry:
    def __init__(self):
        self._providers = {}

    def register_provider(self, name, provider_func, section):
        self._providers[name] = {"func": provider_func, "section": section}

    async def gather_all(self, *, event_name, payload, missed_events, agent_state):
        names = sorted(
            self._providers,
            key=lambda name: (self._providers[name]["section"].value, name),
        )
        blocks = {}
        for name in names:
            result = await self._providers[name]["func"](
                event_name=event_name,
                payload=payload,
                missed_events=missed_events,
                agent_state=agent_state,
            )
            if result:
                blocks[name] = result
        return blocks


class Builder:
    def __init__(self, registry):
        self.registry = registry
        self.build_calls = []

    async def build(self, event_name, payload, missed_events):
        blocks = await self.registry.gather_all(
            event_name=event_name,
            payload=payload,
            missed_events=missed_events,
            agent_state=None,
        )
        # Model the native builder's regular provider budget after gathering.
        self.build_calls.append((event_name, dict(blocks)))
        return "\n\n\n".join(blocks.values())[:800]


def install(current_turn_id):
    return install_native_jawl_turn_context(
        Builder, Section.INTERFACES, current_turn_id=current_turn_id
    )


class NativeJawlTurnContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Each test gets a fresh class because installation patches build.
        class IsolatedBuilder(Builder):
            pass

        self.builder_class = IsolatedBuilder
        self.active_turn = "turn-1"
        self.installation = install_native_jawl_turn_context(
            self.builder_class,
            Section.INTERFACES,
            current_turn_id=lambda: self.active_turn,
        )

    async def build(self, event_name, payload):
        builder = self.builder_class(Registry())
        result = await builder.build(event_name, payload, [])
        return builder, result

    async def test_binding_is_present_on_first_and_internal_heartbeat_steps(self):
        _, first = await self.build(
            "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-1"}
        )
        _, second = await self.build(
            "HEARTBEAT", {"_companion_turn_id": "turn-1"}
        )
        for context in (first, second):
            self.assertIn("same active user turn", context)
            self.assertIn("HEARTBEAT here is an internal step", context)
            self.assertIn("terminal delivery is still required", context)
            self.assertIn("do not send it again", context)
            self.assertIn("turn_id: turn-1", context)

    async def test_provider_is_gathered_before_native_budgeted_result(self):
        registry = Registry()

        async def native_heartbeat(**_kwargs):
            return "native heartbeat block"

        registry.register_provider("heartbeat", native_heartbeat, Section.HEARTBEAT)
        builder = self.builder_class(registry)
        result = await builder.build(
            "HEARTBEAT", {"_companion_turn_id": "turn-1"}, []
        )
        self.assertEqual(len(builder.build_calls), 1)
        blocks = builder.build_calls[0][1]
        self.assertIn("jawl_companion_turn_binding", blocks)
        self.assertEqual(list(blocks), ["jawl_companion_turn_binding", "heartbeat"])
        self.assertTrue(result.startswith(blocks["jawl_companion_turn_binding"]))
        self.assertIn("native heartbeat block", result)

    async def test_background_or_uncorrelated_payload_is_unchanged(self):
        _, result = await self.build("HEARTBEAT", {"reason": "background"})
        self.assertEqual(result, "")

    async def test_mismatched_or_invalid_turn_id_fails_closed(self):
        for payload_id in (
            "turn-old",
            " turn-1",
            "turn\n1",
            "x" * 129,
            123,
            None,
        ):
            _, result = await self.build(
                "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": payload_id}
            )
            self.assertEqual(result, "")

        self.active_turn = "bad id"
        _, result = await self.build(
            "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "bad id"}
        )
        self.assertEqual(result, "")

    async def test_registry_registration_is_once_and_idempotent(self):
        registry = Registry()
        builder = self.builder_class(registry)
        await builder.build("HEARTBEAT", {"_companion_turn_id": "turn-1"}, [])
        await builder.build("HEARTBEAT", {"_companion_turn_id": "turn-1"}, [])
        self.assertEqual(
            list(registry._providers).count("jawl_companion_turn_binding"), 1
        )
        self.assertIs(
            install_native_jawl_turn_context(
                self.builder_class,
                Section.INTERFACES,
                current_turn_id=self.installation.current_turn_id,
            ),
            self.installation,
        )

    async def test_registries_are_isolated_and_concurrent(self):
        left_registry, right_registry = Registry(), Registry()
        left = self.builder_class(left_registry)
        right = self.builder_class(right_registry)
        await asyncio.gather(
            left.build("HEARTBEAT", {"_companion_turn_id": "turn-1"}, []),
            right.build("HEARTBEAT", {"_companion_turn_id": "turn-1"}, []),
        )
        left_provider = left_registry._providers["jawl_companion_turn_binding"]["func"]
        right_provider = right_registry._providers["jawl_companion_turn_binding"]["func"]
        self.assertIs(left_provider, right_provider)
        self.assertEqual(len(left_registry._providers), 1)
        self.assertEqual(len(right_registry._providers), 1)

    async def test_concurrent_turn_ids_do_not_cross_bind(self):
        class IsolatedBuilder(Builder):
            pass

        active_turn = ContextVar("test_active_turn", default="")
        install_native_jawl_turn_context(
            IsolatedBuilder,
            Section.INTERFACES,
            current_turn_id=active_turn.get,
        )

        async def run_turn(turn_id):
            token = active_turn.set(turn_id)
            try:
                return await IsolatedBuilder(Registry()).build(
                    "HEARTBEAT", {"_companion_turn_id": turn_id}, []
                )
            finally:
                active_turn.reset(token)

        left, right = await asyncio.gather(run_turn("turn-left"), run_turn("turn-right"))
        self.assertIn("turn_id: turn-left", left)
        self.assertNotIn("turn-right", left)
        self.assertIn("turn_id: turn-right", right)
        self.assertNotIn("turn-left", right)

    async def test_provider_collision_fails_closed_before_original_build(self):
        registry = Registry()
        registry.register_provider("jawl_companion_turn_binding", lambda **_: "", Section.INTERFACES)
        builder = self.builder_class(registry)
        with self.assertRaisesRegex(RuntimeError, "collision"):
            await builder.build("HEARTBEAT", {}, [])
        self.assertEqual(builder.build_calls, [])

    async def test_original_build_exceptions_propagate(self):
        class BrokenBuilder(self.builder_class):
            async def build(self, event_name, payload, missed_events):
                raise LookupError("native build failed")

        install_native_jawl_turn_context(
            BrokenBuilder,
            Section.INTERFACES,
            current_turn_id=lambda: "turn-1",
        )
        with self.assertRaisesRegex(LookupError, "native build failed"):
            await BrokenBuilder(Registry()).build("HEARTBEAT", {}, [])

    async def test_binding_is_fixed_bounded_and_does_not_interpolate_payload_text(self):
        user_text = "secret user content" * 500
        _, result = await self.build(
            "HEARTBEAT",
            {"_companion_turn_id": "turn-1", "text": user_text},
        )
        self.assertLess(len(result), 400)
        self.assertNotIn(user_text, result)
        self.assertNotIn("private", result.lower())
        self.assertNotIn("persona", result.lower())
        self.assertNotIn("permission", result.lower())

    async def test_binding_is_subject_to_exact_native_provider_budget(self):
        native = Path(__file__).parents[1] / 'runtime/jawl-sources/jawl-20260906-daily-v2/src/l3_agent/context/builder.py'
        tree = ast.parse(native.read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ContextBuilder')
        names = {'_trim_block', '_join_blocks', '_apply_context_budget'}
        methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual(len(methods), 3)
        fixture = ast.ClassDef(name='NativeBudget', bases=[], keywords=[], body=methods, decorator_list=[])
        scope = {'Dict': dict}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fixture], type_ignores=[])), str(native), 'exec'), scope)
        budget = scope['NativeBudget']()
        budget.budget = SimpleNamespace(skills_max_chars=512, recent_ticks_max_chars=512,
            hypotheses_max_chars=512, provider_max_chars=64, max_dynamic_chars=4096)
        _, binding = await self.build('HOST_TERMINAL_MESSAGE', {'_companion_turn_id': 'turn-1'})
        compacted, trimmed = budget._apply_context_budget({'jawl_companion_turn_binding': binding})
        self.assertLessEqual(len(compacted['jawl_companion_turn_binding']), 64)
        self.assertIn('jawl_companion_turn_binding', trimmed)
        # This intentionally proves native limits win, not that tight budgets
        # guarantee retention or that any model follows the delivery guidance.

    async def test_original_heartbeat_step_rewrite_remains_archived(self):
        root = Path(__file__).parents[1]
        native_builder = (
            root
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
            / "src"
            / "l3_agent"
            / "context"
            / "builder.py"
        )
        tree = ast.parse(native_builder.read_text(encoding="utf-8"))
        builder_class = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ContextBuilder"
        )
        heartbeat = next(
            node
            for node in builder_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_heartbeat_provider"
        )
        source_text = native_builder.read_text(encoding="utf-8")
        source_segment = ast.get_source_segment(source_text, heartbeat)
        fixture = ast.parse(
            """if self.agent_state.current_step > 1 and local_event_name != 'HEARTBEAT':
    processed_event = {
        'name': f'{local_event_name} [Already received on step 1]',
        'payload': local_payload.copy(),
        'time': 'Step 1',
        'level': 'PROCESSED',
    }
    local_missed_events.append(processed_event)
    local_event_name = 'HEARTBEAT'
    local_payload = {}
"""
        ).body[0]
        archived_branch = next(node for node in heartbeat.body if isinstance(node, ast.If))
        self.assertIn("local_payload = {}", source_segment)
        self.assertEqual(
            ast.dump(archived_branch, include_attributes=False),
            ast.dump(fixture, include_attributes=False),
        )


if __name__ == "__main__":
    unittest.main()
