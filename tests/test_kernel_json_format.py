"""Kernel JSON-envelope wire policy for the native JAWL provider.

Spec lineage: the retired product extension ``native_jawl_json_format``
(ADR-049 slice 4). ``apply_envelope_policy`` is invoked natively by
``OpenAICompatibleProvider._request_kwargs``; tests drive it through a small
harness with the per-turn companion state bound via ``chat()``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
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
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-envelope-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l3_agent import companion_gateway  # noqa: E402
from src.l3_agent.llm import envelope_policy as extension  # noqa: E402


def chat(message="", *, goal_active=False):
    """Bind the per-turn companion state the way a correlated run does."""
    return companion_gateway.bind_companion_turn_state(
        companion_gateway.CompanionTurnState(message, lambda: goal_active)
    )


class NativeJsonFormatTests(unittest.TestCase):
    def call(self, kwargs, request, *, url="http://127.0.0.1/v1",
             chat_turn=None, goal_active=False):
        provider = SimpleNamespace(client=SimpleNamespace(api_url=url))
        if chat_turn is not None:
            token = chat(chat_turn, goal_active=goal_active)
            try:
                return extension.apply_envelope_policy(dict(kwargs), request, provider=provider)
            finally:
                companion_gateway.reset_companion_turn_state(token)
        return extension.apply_envelope_policy(dict(kwargs), request, provider=provider)

    def test_gemini_relay_uses_plain_json_with_native_argument_validation(self):
        original = {"model": "gemini-3.8-flash", "response_format": {"type": "json_object"},
                    "tools": [{"function": {"name": "execute_skill", "parameters": {"type": "object"}}}],
                    "messages": [{"role": "user", "content": "full context"}]}
        actual = self.call(original, SimpleNamespace(tool_transport="json_envelope"))
        self.assertEqual(actual["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", actual)
        self.assertIn("full context", actual["messages"][-1]["content"])
        self.assertIn("No SDK function", actual["messages"][0]["content"])

    def test_ordinary_chat_can_register_a_durable_goal_before_final_delivery(self):
        import jsonschema
        original = {"response_format": {"type": "json_object"}, "tools": [{"function": {
            "name": "execute_skill", "parameters": {"type": "object", "properties": {
                "actions": {"type": "array", "items": {"type": "object"}},
            }},
        }}], "messages": [{"role": "system", "content": "Full task policy"}]}
        with patch.dict(sys.modules, {
            "src.l3_agent.skills.registry": SimpleNamespace(_REGISTRY={
                "GoalSkills.create_goal": {"hidden": False},
                "HostOSReader.read_file": {"hidden": False},
                "HostTerminalMessages.send_message_to_terminal": {"hidden": False},
            }),
        }):
            actual = self.call(original, SimpleNamespace(tool_transport="json_envelope"),
                              chat_turn="Привет!")
        schema = actual["response_format"]["json_schema"]["schema"]
        jsonschema.validate({"actions": [{"tool_name": "GoalSkills.create_goal", "parameters": {"objective": "Inspect repository"}}]}, schema)
        self.assertIn("acknowledgement alone does not start background work", actual["messages"][0]["content"])

    def test_unassigned_heartbeat_keeps_tools_and_provider_budget(self):
        import jsonschema
        original = {"response_format": {"type": "json_object"}, "max_tokens": 2048,
                    "tools": [{"function": {"name": "execute_skill", "parameters": {
                        "type": "object", "properties": {"actions": {"type": "array", "items": {"type": "object"}}},
                    }}}]}
        request = SimpleNamespace(tool_transport="json_envelope", metadata={"trace": {"event_name": "HEARTBEAT"}})
        actual = self.call(original, request)
        self.assertEqual(actual["max_tokens"], 2048)
        jsonschema.validate({"actions": [{"tool_name": "HostOSReader.read_file", "parameters": {"filepath": "fixture.txt"}}]}, actual["response_format"]["json_schema"]["schema"])

    def test_context_slimming_requires_explicit_opt_in(self):
        messages = [{"role": "system", "content": "Full persona and task history" * 400}, {"role": "user", "content": "hi"}]
        with patch.dict(os.environ, {"JAWL_FAST_CONVERSATION": "0"}):
            self.assertIsNone(extension._fast_lane_messages(messages))

    def test_context_diagnostic_exports_only_public_names_counts_and_owned_bounded_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "runtime/instances/fixture"
            logs = home / "logs"
            env = {"JAWL_ACCEPTANCE_CONTEXT_DIAGNOSTICS": "1", "JAWL_INSTANCE_HOME": str(home), "JAWL_LOG_DIR": str(logs)}
            kwargs = {"messages": [{"role": "user", "content": "PRIVATE_SENTINEL BrowserNavigation.navigate PRIVATE_THOUGHT"}]}
            with patch.object(extension, "ROOT", root), patch.dict(os.environ, env, clear=True):
                extension.record_owned_context_summary(kwargs)
                path = logs / "owned-context-summary.jsonl"
                text = path.read_text("utf-8")
                self.assertNotIn("PRIVATE_SENTINEL", text)
                self.assertNotIn("PRIVATE_THOUGHT", text)
                record = json.loads(text)
                self.assertEqual(record["messages"][0]["public_skill_name_counts"]["BrowserNavigation.navigate"], 1)
                (logs / "acceptance-context-markers.json").write_text(json.dumps(["PRIVATE_SENTINEL"]), encoding="utf-8")
                extension.record_owned_context_summary(kwargs)
                text = path.read_text("utf-8")
                self.assertNotIn("PRIVATE_SENTINEL", text)
                self.assertEqual(json.loads(text.splitlines()[-1])["messages"][0]["acceptance_marker_counts"], [1])
                extension.record_owned_context_summary({"messages": [{"role": "user", "content":
                    "### WEB BROWSER [ON]\nVisible AOM:\nPRIVATE_SENTINEL\n## RECENT TICKS\nPRIVATE_SENTINEL"}]})
                msg = json.loads(path.read_text("utf-8").splitlines()[-1])["messages"][0]
                self.assertEqual(msg["acceptance_marker_counts"], [2])
                self.assertEqual(msg["native_browser_marker_counts"], [1])
                path.write_bytes(b" " * (128 * 1024))
                extension.record_owned_context_summary(kwargs)
                self.assertEqual(path.stat().st_size, 128 * 1024)
                os.environ["JAWL_LOG_DIR"] = str(root / "foreign")
                with self.assertRaises(ValueError):
                    extension.record_owned_context_summary(kwargs)
                self.assertFalse((root / "foreign").exists())

    def test_local_envelope_constrains_only_wire_syntax_preserving_native_context_and_sampling(self):
        schema = {"type": "object", "properties": {
            "actions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "v": {"enum": [2]}, "calls": {"type": "array"}, "ledger": {"type": "object"},
        }}
        tools = [{"type": "function", "function": {"name": "execute_skill", "parameters": schema}}]
        messages = [{"role": "system", "content": "full native discovery/persona/policy/Goal Protocol v2"}]
        original = {"response_format": {"type": "json_object"}, "tools": tools,
                    "messages": messages, "temperature": .3, "stream": True}
        actual = self.call(original, SimpleNamespace(tool_transport="json_envelope"))
        wire = actual["response_format"]["json_schema"]["schema"]
        self.assertEqual(wire["properties"], {
            name: schema["properties"][name] for name in ("actions", "calls", "v", "ledger")
        })
        self.assertTrue(wire["additionalProperties"])
        self.assertIsNot(wire["properties"]["actions"], schema["properties"]["actions"])
        self.assertNotIn("tools", actual)
        for key in ("messages", "temperature", "stream"):
            self.assertIs(actual[key], original[key])
        self.assertEqual(original["response_format"], {"type": "json_object"})
        self.assertIs(original["tools"], tools)

    def test_actual_native_sdk_tools_and_explicit_tool_choice_are_never_removed(self):
        for tools, choice in (([{"function": {"name": "native_file_write", "parameters": {}}}], None),
                              ([{"function": {"name": "execute_skill", "parameters": {}}}], "required")):
            original = {"response_format": {"type": "json_object"}, "tools": tools, "tool_choice": choice}
            self.assertEqual(
                self.call(original, SimpleNamespace(tool_transport="json_envelope")), original
            )

    def test_native_action_shapes_reject_historical_outcomes_and_preserve_arbitrary_tools_goal_calls(self):
        import ast
        import jsonschema
        source = _SNAPSHOT / "src/l3_agent/skills/schema.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "ACTION_SCHEMA" for target in node.targets))
        native_tools = ast.literal_eval(assignment.value)
        original = {"response_format": {"type": "json_object"}, "tools": native_tools}
        schema = self.call(original, SimpleNamespace(tool_transport="json_envelope"))["response_format"]["json_schema"]["schema"]
        for value in [
            {"actions": [{"tool_name": "AnyDiscoveredSkill.operation", "parameters": {"arbitrary_arg": {"values": [1, 2]}}, "action_id": "write"}]},
            {"v": 2, "state": "act", "calls": [{"tool": "AnyDiscoveredSkill.operation", "args": {"future_arg": True}}], "ledger": {"pending_steps": ["next"]}},
            {"actions": [], "reasoning": "x" * 5000}]:
            jsonschema.validate(value, schema)
        for value in [
            {"actions": [{"action_id": "action_1", "status": "success", "duration_ms": 7.3}]},
            {"actions": [{"tool_name": "AnyDiscoveredSkill.operation", "parameters": {}, "status": "success"}]},
            {"calls": [{"status": "success", "duration_ms": 7.3}]}]:
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(value, schema)

    def test_chat_bound_keeps_arbitrary_tool_parameters_and_goal_v2_fields_available(self):
        base = {
            "response_format": {"type": "json_object"},
            "tools": [{"function": {"name": "execute_skill", "parameters": {"type": "object"}}}],
        }
        schema = self.call(base, SimpleNamespace(tool_transport="json_envelope"), chat_turn="hi")["response_format"]["json_schema"]["schema"]
        import jsonschema
        jsonschema.validate({"reasoning": "brief", "actions": [{"tool_name": "AnyDiscoveredSkill.any", "parameters": {"new_native_arg": [1, 2]}}],
                             "v": 2, "state": "wait", "calls": [], "ledger": {"pending_steps": ["task"]}}, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"reasoning": "x" * 321}, schema)
        goal_schema = self.call(base, SimpleNamespace(tool_transport="json_envelope"))["response_format"]["json_schema"]["schema"]
        jsonschema.validate({"reasoning": "x" * 5000, "v": 2, "state": "act"}, goal_schema)

    def test_goal_start_requires_one_valid_goal_action(self):
        base = {
            "response_format": {"type": "json_object"},
            "tools": [{"function": {"name": "execute_skill", "parameters": {
                "type": "object", "properties": {
                    "actions": {"type": "array", "items": {"type": "object"}},
                    "calls": {"type": "array", "items": {"type": "object"}},
                    "v": {"type": "integer", "enum": [2]},
                    "state": {"type": "string", "enum": ["act", "continue", "wait", "done", "blocked"]},
                    "note": {"type": "string"},
                    "summary": {"type": "string"},
                    "wake_after_seconds": {"type": "integer", "minimum": 1},
                    "ledger": {"type": "object"},
                },
            }}}],
            "messages": [{"role": "user", "content": "## ACTIVE GOAL\nDo the durable next action."}],
            "max_tokens": 2048,
        }
        request = SimpleNamespace(
            tool_transport="json_envelope",
            metadata={"trace": {"event_name": "GOAL_OPERATOR_CONTROL"}},
        )
        token = chat("делай цель")
        try:
            actual = self.call(base, request)
            schema = actual["response_format"]["json_schema"]["schema"]
            self.assertEqual(actual["max_tokens"], 2048)
            self.assertTrue({"calls", "v", "state", "note", "ledger"}.issubset(schema["properties"]))
            self.assertEqual(schema["required"], ["v", "state"])
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(len(schema["oneOf"]), 3)
            self.assertIn("do not call GoalSkills", actual["messages"][0]["content"])
            import jsonschema
            jsonschema.validate({
                "v": 2,
                "state": "act",
                "calls": [{"tool": "HostOSWriter.write_file", "args": {"path": "sandbox/x", "text": "ok"}}],
                "ledger": {"phase": "completed", "next_action": "none"},
            }, schema)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({"v": 2, "state": "act", "calls": []}, schema)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({"v": 2, "state": "act", "calls": [{"tool": "x"}]}, schema)
            # GOAL_OPERATOR_CONTROL may cover the whole ReAct cycle; after its
            # final verified action it must be able to emit the native terminal
            # envelope instead of calling the legacy lifecycle tool.
            jsonschema.validate({"v": 2, "state": "done", "summary": "Verified.", "ledger": {}}, schema)
            # A goal may already be active when the owned brain starts. That
            # startup event must receive the same action-required grammar.
            request.metadata["trace"]["event_name"] = "SYSTEM_CORE_START"
            startup_schema = self.call(base, request)["response_format"]["json_schema"]["schema"]
            self.assertEqual(startup_schema["required"], ["v", "state"])
            self.assertEqual(len(startup_schema["oneOf"]), 3)
        finally:
            companion_gateway.reset_companion_turn_state(token)

    def test_active_goal_hides_legacy_lifecycle_skill_docs(self):
        base = {
            "response_format": {"type": "json_object"},
            "tools": [{"function": {"name": "execute_skill", "parameters": {
                "type": "object", "properties": {
                    "actions": {"type": "array"}, "calls": {"type": "array"},
                    "v": {"type": "integer", "enum": [2]},
                    "state": {"type": "string", "enum": ["act", "continue", "wait", "done", "blocked"]},
                },
            }}}],
            "messages": [
                {"role": "system", "content": (
                    "## SKILLS\n"
                    "GoalSkills.update_goal(status, summary) - finish a Goal\n"
                    "GoalSkills.schedule_goal_wakeup(seconds, summary) - wait\n"
                    "HostOSReader.read_file(filepath) - read a file\n"
                    "## POLICY\nKeep evidence."
                )},
                {"role": "user", "content": "## ACTIVE GOAL\nVerify the file."},
            ],
        }
        request = SimpleNamespace(tool_transport="json_envelope", metadata={
            "trace": {"event_name": "GOAL_OPERATOR_CONTROL"},
        })
        with patch.dict(sys.modules, {
            "src.l3_agent.skills.registry": SimpleNamespace(_REGISTRY={
                "GoalSkills.get_goal": {"hidden": False},
                "GoalSkills.update_goal": {"hidden": False},
                "GoalSkills.schedule_goal_wakeup": {"hidden": False},
                "HostOSReader.read_file": {"hidden": False},
                "HostOSWriter.write_file": {"hidden": False},
                "Hidden.admin": {"hidden": True},
            }),
        }):
            actual = self.call(base, request)
        system_content = actual["messages"][0]["content"]
        self.assertIn("HostOSReader.read_file", system_content)
        self.assertNotIn("GoalSkills.update_goal(status", system_content)
        self.assertNotIn("GoalSkills.schedule_goal_wakeup(seconds", system_content)
        self.assertIn("do not call goalskills", system_content.lower())
        tool_enum = actual["response_format"]["json_schema"]["schema"]["oneOf"][0]["properties"]["calls"]["items"]["properties"]["tool"]["enum"]
        self.assertEqual(tool_enum, ["HostOSReader.read_file", "HostOSWriter.write_file"])
        import jsonschema
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"v": 2, "state": "act", "calls": [{
                "tool": "GoalSkills.update_goal", "args": {"status": "complete"},
            }]}, actual["response_format"]["json_schema"]["schema"])

    def test_active_goal_heartbeat_still_accepts_terminal_state_without_calls(self):
        base = {
            "response_format": {"type": "json_object"},
            "tools": [{"function": {"name": "execute_skill", "parameters": {"type": "object", "properties": {
                "actions": {"type": "array"}, "calls": {"type": "array"},
                "v": {"type": "integer", "enum": [2]},
                "state": {"type": "string", "enum": ["act", "continue", "wait", "done", "blocked"]},
                "summary": {"type": "string"}, "ledger": {"type": "object"},
            }}}}],
            "messages": [{"role": "system", "content": "## ACTIVE GOAL\nDo work."}],
            "max_tokens": 2048,
        }
        request = SimpleNamespace(tool_transport="json_envelope", metadata={"trace": {"event_name": "HEARTBEAT"}})
        schema = self.call(base, request)["response_format"]["json_schema"]["schema"]
        import jsonschema
        jsonschema.validate({"v": 2, "state": "done", "summary": "verified", "ledger": {}}, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"v": 2, "state": "act", "calls": []}, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"actions": [{"tool_name": "GoalSkills.update_goal", "parameters": {}}]}, schema)

    def test_no_progress_goal_response_is_terminal_only(self):
        base = {
            "response_format": {"type": "json_object"},
            "tools": [{"function": {"name": "execute_skill", "parameters": {
                "type": "object", "properties": {
                    "actions": {"type": "array"}, "calls": {"type": "array"},
                    "v": {"type": "integer", "enum": [2]},
                    "state": {"type": "string", "enum": ["act", "continue", "wait", "done", "blocked"]},
                    "summary": {"type": "string"}, "ledger": {"type": "object"},
                },
            }}}],
            "messages": [{"role": "user", "content": (
                "## ACTIVE GOAL\nA previously successful action repeated; "
                "no-progress-repeat=1; next retry in 1s."
            )}],
        }
        request = SimpleNamespace(tool_transport="json_envelope", metadata={
            "trace": {"event_name": "HEARTBEAT"},
        })
        actual = self.call(base, request)
        schema = actual["response_format"]["json_schema"]["schema"]
        self.assertEqual(len(schema["oneOf"]), 1)
        terminal = schema["oneOf"][0]
        self.assertEqual(terminal["properties"]["state"]["enum"], ["wait", "done", "blocked"])
        self.assertEqual(terminal["properties"]["calls"]["maxItems"], 0)
        import jsonschema
        jsonschema.validate({"v": 2, "state": "done", "summary": "Verified.", "ledger": {}}, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"v": 2, "state": "act", "calls": [{
                "tool": "HostOSReader.read_file", "args": {"filepath": "x"},
            }]}, schema)

    def test_startup_without_goal_stays_short_and_comment_only(self):
        for event_name in ("SYSTEM_CORE_START",):
            with self.subTest(event_name=event_name):
                base = {
                    "response_format": {"type": "json_object"},
                    "tools": [{"function": {"name": "execute_skill", "parameters": {
                        "type": "object", "properties": {"actions": {"type": "array"}, "calls": {"type": "array"}},
                    }}}],
                    "messages": [{"role": "system", "content": "Passive perception."}],
                    "max_tokens": 2048,
                }
                request = SimpleNamespace(tool_transport="json_envelope", metadata={"trace": {"event_name": event_name}})
                actual = self.call(base, request)
                schema = actual["response_format"]["json_schema"]["schema"]
                self.assertEqual(actual["max_tokens"], 320)
                self.assertEqual(set(schema["properties"]), {"actions"})
                self.assertFalse(schema["additionalProperties"])

    def test_remote_native_transport_optout_and_custom_schema_are_untouched(self):
        for url, transport, fmt in (
            ("https://remote.example/v1", "json_envelope", {"type": "json_object"}),
            ("http://127.0.0.1/v1", "native", {"type": "json_object"}),
            ("http://127.0.0.1/v1", "json_envelope", None),
            ("http://127.0.0.1/v1", "json_envelope", {"type": "json_schema", "json_schema": {"schema": {"type": "array"}}}),
        ):
            with self.subTest(url=url, transport=transport, fmt=fmt):
                original = {"tools": ["all"], **({"response_format": fmt} if fmt is not None else {})}
                self.assertEqual(self.call(original, SimpleNamespace(tool_transport=transport), url=url), original)

    def test_provider_request_kwargs_applies_the_policy_natively(self):
        source = (_SNAPSHOT / "src/l3_agent/llm/providers/openai_compatible.py").read_text(encoding="utf-8")
        self.assertIn("envelope_policy.apply_envelope_policy(kwargs, request, provider=self)", source)
        self.assertLess(
            source.index("envelope_policy.apply_envelope_policy"),
            source.index("async def complete("),
        )


if __name__ == "__main__":
    unittest.main()
