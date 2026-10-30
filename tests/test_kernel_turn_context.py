"""Kernel companion turn context bound into native JAWL context.

Spec lineage: the retired product extension ``native_jawl_turn_context``
(ADR-049 slice 3). The provider contains no user supplied text; native
ordering and budget compaction stay authoritative.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import time
import unittest
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-context-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l3_agent.companion_gateway import (  # noqa: E402
    reset_companion_turn_id,
    set_companion_turn_id,
)
from src.l3_agent.context import companion  # noqa: E402

BINDING = companion._BINDING_TEXT
FAST_HINT = companion._FAST_CONVERSATION_HINT


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
        payload = companion.prepare_companion_context(self, payload)
        blocks = await self.registry.gather_all(
            event_name=event_name,
            payload=payload,
            missed_events=missed_events,
            agent_state=None,
        )
        self.build_calls.append((event_name, dict(blocks)))
        return "\n\n\n".join(blocks.values())


class TurnContextKernelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = Registry()
        self.builder = Builder(self.registry)

    async def build(self, event_name, payload):
        return await self.builder.build(event_name, payload, [])

    async def bound_build(self, turn_id, event_name, payload):
        token = set_companion_turn_id(turn_id)
        try:
            return await self.build(event_name, payload)
        finally:
            reset_companion_turn_id(token)

    # ------------------------------------------------------------------
    # Declared capacity
    # ------------------------------------------------------------------

    def test_large_declared_window_retains_catalog_and_disables_fixed_goal_cap(self):
        from pydantic import BaseModel

        class Budget(BaseModel):
            max_dynamic_chars: int = 18000
            skills_max_chars: int = 9000
            recent_ticks_max_chars: int = 5000
            hypotheses_max_chars: int = 3000
            provider_max_chars: int = 3000

        builder = SimpleNamespace(
            budget=Budget(), goal_manager=SimpleNamespace(compact_context=True)
        )
        with patch.dict("os.environ", {"JAWL_CONTEXT_WINDOW_TOKENS": "1048576"}):
            companion.apply_declared_capacity(builder)
        self.assertFalse(builder.goal_manager.compact_context)
        self.assertEqual(builder.budget.max_dynamic_chars, 1572864)
        catalog = "tool schema " * 8000
        # Exercise the pinned native budgeting algorithm, not just the numbers:
        # this is the path that used to remove discovered tool schemas.
        native = _SNAPSHOT / "src" / "l3_agent" / "context" / "builder.py"
        tree = ast.parse(native.read_text(encoding="utf-8"))
        cls = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ContextBuilder"
        )
        methods = [
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef)
            and n.name in {"_trim_block", "_join_blocks", "_apply_context_budget"}
        ]
        scope = {"Dict": dict}
        fixture = ast.ClassDef(
            name="NativeBudget", bases=[], keywords=[], body=methods, decorator_list=[]
        )
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[fixture], type_ignores=[])),
                str(native),
                "exec",
            ),
            scope,
        )
        native_budget = scope["NativeBudget"]()
        native_budget.budget = builder.budget
        blocks, trimmed = native_budget._apply_context_budget(
            {"skills": catalog, "host_terminal": "conversation " * 5000}
        )
        self.assertEqual(blocks["skills"], catalog)
        self.assertFalse(trimmed)

    def test_absent_small_or_invalid_capacity_preserves_native_policy(self):
        for value in ("0", "8192", "invalid", "2097152"):
            builder = SimpleNamespace(
                budget=SimpleNamespace(),
                goal_manager=SimpleNamespace(compact_context=True),
            )
            original = builder.budget
            with patch.dict("os.environ", {"JAWL_CONTEXT_WINDOW_TOKENS": value}):
                companion.apply_declared_capacity(builder)
            self.assertIs(builder.budget, original)
            self.assertTrue(builder.goal_manager.compact_context)

    # ------------------------------------------------------------------
    # Perception packet + binding
    # ------------------------------------------------------------------

    async def test_va_packet_becomes_separate_native_section_and_message_stays_clean(self):
        packet = {"version": 1, "generated_at": time.time(), "channels": {"screen": {"text": "окно браузера", "age_s": 1, "ttl_s": 30}}}
        import json as _json

        message = "Что на экране?" + "\n\n<va_perception>" + _json.dumps(packet) + "\n</va_perception>"
        payload = {"_companion_turn_id": "turn-1", "message": message}
        result = await self.bound_build("turn-1", "HOST_TERMINAL_MESSAGE", payload)
        self.assertIn("## PERCEPTION / VA", result)
        self.assertIn("Видео (", result)
        self.assertNotIn("va_perception", result)
        self.assertNotIn("Что на экране?", result)
        # The input payload dict is never mutated.
        self.assertEqual(payload["message"], message)

    async def test_work_requests_never_enter_casual_lane(self):
        self.assertFalse(companion.is_conversational_text("Открой терминал и проверь файлы"))
        self.assertFalse(companion.is_conversational_text("/help"))
        self.assertFalse(companion.is_conversational_text("x" * 200))
        self.assertTrue(companion.is_conversational_text("Привет, как у тебя дела?"))

    async def test_binding_is_present_on_first_and_internal_heartbeat_steps(self):
        token = set_companion_turn_id("turn-1")
        try:
            payload = {"_companion_turn_id": "turn-1", "message": "Сделай отчёт по задаче"}
            first = await self.build("HOST_TERMINAL_MESSAGE", payload)
            second = await self.build("HEARTBEAT", {"_companion_turn_id": "turn-1"})
        finally:
            reset_companion_turn_id(token)
        self.assertIn(BINDING, first)
        self.assertIn(BINDING, second)
        self.assertIn("turn_id: turn-1", first)

    async def test_provider_is_gathered_before_native_budgeted_result(self):
        await self.bound_build("turn-1", "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-1"})
        self.assertIn(companion._PROVIDER_NAME, self.registry._providers)
        source = (_SNAPSHOT / "src" / "l3_agent" / "context" / "builder.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            source.index("prepare_companion_context(self, payload)"),
            source.index("self.registry.gather_all("),
        )

    async def test_background_or_uncorrelated_payload_is_unchanged(self):
        result = await self.build("HEARTBEAT", {"message": "просто фон"})
        self.assertNotIn(BINDING, result)
        self.assertEqual(result, "")

    async def test_mismatched_or_invalid_turn_id_fails_closed(self):
        token = set_companion_turn_id("turn-1")
        try:
            mismatched = await self.build(
                "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-2", "message": "Сделай отчёт"}
            )
            invalid = await self.build(
                "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "bad id!", "message": "Сделай отчёт"}
            )
        finally:
            reset_companion_turn_id(token)
        self.assertNotIn(BINDING, mismatched)
        self.assertNotIn(BINDING, invalid)

    async def test_registry_registration_is_once_and_idempotent(self):
        companion.ensure_registered(self.registry, section=Section.INTERFACES)
        first = dict(self.registry._providers)
        companion.ensure_registered(self.registry, section=Section.INTERFACES)
        self.assertEqual(first, self.registry._providers)
        self.assertEqual(len(self.registry._providers), 1)

    async def test_registries_are_isolated_and_concurrent(self):
        other = Registry()
        companion.ensure_registered(self.registry)
        companion.ensure_registered(other)
        self.assertIsNot(self.registry._providers, other._providers)
        self.assertEqual(len(other._providers), 1)

    async def test_concurrent_turn_ids_do_not_cross_bind(self):
        results = {}

        async def run(turn_id):
            token = set_companion_turn_id(turn_id)
            try:
                await asyncio.sleep(0.01 if turn_id == "turn-a" else 0)
                results[turn_id] = await self.build(
                    "HOST_TERMINAL_MESSAGE",
                    {"_companion_turn_id": turn_id, "message": "Сделай отчёт"},
                )
            finally:
                reset_companion_turn_id(token)

        await asyncio.gather(run("turn-a"), run("turn-b"))
        self.assertIn("turn_id: turn-a", results["turn-a"])
        self.assertNotIn("turn-b", results["turn-a"])
        self.assertIn("turn_id: turn-b", results["turn-b"])
        self.assertNotIn("turn-a", results["turn-b"])

    async def test_provider_collision_fails_closed_before_original_build(self):
        self.registry.register_provider(
            companion._PROVIDER_NAME, lambda **_: "collide", section=Section.INTERFACES
        )
        with self.assertRaisesRegex(RuntimeError, "collision"):
            companion.prepare_companion_context(self.builder, {"_companion_turn_id": "x"})

    async def test_original_build_exceptions_propagate(self):
        class BoomRegistry(Registry):
            async def gather_all(self, **_):
                raise RuntimeError("boom")

        builder = Builder(BoomRegistry())
        with self.assertRaisesRegex(RuntimeError, "boom"):
            await builder.build("HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-1"}, [])

    async def test_binding_is_fixed_bounded_and_does_not_interpolate_payload_text(self):
        user_text = "secret user content" * 500
        result = await self.bound_build(
            "turn-1", "HEARTBEAT", {"_companion_turn_id": "turn-1", "text": user_text}
        )
        self.assertLess(len(result), 800)
        self.assertNotIn("secret user content", result)
        self.assertNotIn("private", result.lower())
        self.assertNotIn("persona", result.lower())
        self.assertNotIn("permission", result.lower())

    async def test_binding_is_subject_to_exact_native_provider_budget(self):
        native = _SNAPSHOT / "src" / "l3_agent" / "context" / "builder.py"
        tree = ast.parse(native.read_text(encoding="utf-8"))
        cls = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ContextBuilder"
        )
        names = {"_trim_block", "_join_blocks", "_apply_context_budget"}
        methods = [
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        self.assertEqual(len(methods), 3)
        fixture = ast.ClassDef(
            name="NativeBudget", bases=[], keywords=[], body=methods, decorator_list=[]
        )
        scope = {"Dict": dict}
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[fixture], type_ignores=[])),
                str(native),
                "exec",
            ),
            scope,
        )
        budget = scope["NativeBudget"]()
        budget.budget = SimpleNamespace(
            skills_max_chars=512,
            recent_ticks_max_chars=512,
            hypotheses_max_chars=512,
            provider_max_chars=64,
            max_dynamic_chars=4096,
        )
        binding = await self.bound_build(
            "turn-1", "HOST_TERMINAL_MESSAGE", {"_companion_turn_id": "turn-1"}
        )
        compacted, trimmed = budget._apply_context_budget(
            {companion._PROVIDER_NAME: binding}
        )
        self.assertLessEqual(len(compacted[companion._PROVIDER_NAME]), 64)
        self.assertIn(companion._PROVIDER_NAME, trimmed)
        # This intentionally proves native limits win, not that tight budgets
        # guarantee retention or that any model follows the delivery guidance.

    async def test_original_heartbeat_step_rewrite_remains_archived(self):
        native_builder = (
            _SNAPSHOT / "src" / "l3_agent" / "context" / "builder.py"
        )
        source_text = native_builder.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        builder_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ContextBuilder"
        )
        heartbeat = next(
            node
            for node in builder_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_heartbeat_provider"
        )
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
        archived_branch = next(
            node for node in heartbeat.body if isinstance(node, ast.If)
        )
        self.assertIn("local_payload = {}", source_segment)
        self.assertEqual(
            ast.dump(archived_branch, include_attributes=False),
            ast.dump(fixture, include_attributes=False),
        )

    async def test_conversational_turn_adds_fast_hint_while_action_turn_does_not(self):
        chat_ctx = await self.bound_build(
            "turn-1",
            "HOST_TERMINAL_MESSAGE",
            {"_companion_turn_id": "turn-1", "message": "Привет, как у тебя дела?"},
        )
        self.assertIn("Fast conversational reply mode", chat_ctx)

        action_ctx = await self.bound_build(
            "turn-1",
            "HOST_TERMINAL_MESSAGE",
            {"_companion_turn_id": "turn-1", "message": "Открой терминал и проверь файлы в папке"},
        )
        self.assertNotIn("Fast conversational reply mode", action_ctx)


if __name__ == "__main__":
    unittest.main()
