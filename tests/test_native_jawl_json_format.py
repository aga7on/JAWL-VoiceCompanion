"""Local JSON wire correction preserves the complete native action surface."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("json_format_test_extension", ROOT / "src/jawl_voicecompanion/native_jawl_json_format.py")
extension = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = extension
spec.loader.exec_module(extension)


class NativeJsonFormatTests(unittest.TestCase):
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

    def provider(self, url, kwargs):
        class Provider:
            def _request_kwargs(self, request):
                return dict(kwargs)
        extension.install_native_json_format(Provider)
        result = Provider()
        result.client = SimpleNamespace(api_url=url)
        return result

    def test_local_envelope_constrains_only_wire_syntax_preserving_native_context_and_sampling(self):
        schema = {"type": "object", "properties": {
            "actions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "v": {"enum": [2]}, "calls": {"type": "array"}, "ledger": {"type": "object"},
        }}
        tools = [{"type": "function", "function": {"name": "execute_skill", "parameters": schema}}]
        messages = [{"role": "system", "content": "full native discovery/persona/policy/Goal Protocol v2"}]
        original = {"response_format": {"type": "json_object"}, "tools": tools,
                    "messages": messages, "temperature": .3, "stream": True}
        provider = self.provider("http://127.0.0.1:8990/v1", original)
        actual = provider._request_kwargs(SimpleNamespace(tool_transport="json_envelope"))
        wire = actual["response_format"]["json_schema"]["schema"]
        self.assertEqual(wire["properties"], {name: schema["properties"][name] for name in ("actions", "calls")})
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
            provider = self.provider("http://127.0.0.1/v1", original)
            self.assertEqual(provider._request_kwargs(SimpleNamespace(tool_transport="json_envelope")), original)

    def test_native_action_shapes_reject_historical_outcomes_and_preserve_arbitrary_tools_goal_calls(self):
        import ast
        import jsonschema
        source = ROOT / 'runtime/jawl-sources/jawl-20260906-daily-v2/src/l3_agent/skills/schema.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'ACTION_SCHEMA' for target in node.targets))
        native_tools = ast.literal_eval(assignment.value)
        original = {'response_format': {'type': 'json_object'}, 'tools': native_tools}
        provider = self.provider('http://127.0.0.1/v1', original)
        schema = provider._request_kwargs(SimpleNamespace(tool_transport='json_envelope'))['response_format']['json_schema']['schema']
        for value in [
            {'actions': [{'tool_name': 'AnyDiscoveredSkill.operation', 'parameters': {'arbitrary_arg': {'values': [1, 2]}}, 'action_id': 'write'}]},
            {'v': 2, 'state': 'act', 'calls': [{'tool': 'AnyDiscoveredSkill.operation', 'args': {'future_arg': True}}], 'ledger': {'pending_steps': ['next']}},
            {'actions': [], 'reasoning': 'x' * 5000}]:
            jsonschema.validate(value, schema)
        for value in [
            {'actions': [{'action_id': 'action_1', 'status': 'success', 'duration_ms': 7.3}]},
            {'actions': [{'tool_name': 'AnyDiscoveredSkill.operation', 'parameters': {}, 'status': 'success'}]},
            {'calls': [{'status': 'success', 'duration_ms': 7.3}]}]:
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(value, schema)

    def test_chat_bound_keeps_arbitrary_tool_parameters_and_goal_v2_fields_available(self):
        provider = self.provider("http://127.0.0.1/v1", {
            "response_format": {"type": "json_object"},
            "tools": [{"function": {"name": "execute_skill", "parameters": {"type": "object"}}}],
        })
        with patch.dict(sys.modules, {"_owned_jawl_delivery": SimpleNamespace(native_companion_chat_active=lambda: True)}):
            schema = provider._request_kwargs(SimpleNamespace(tool_transport="json_envelope"))["response_format"]["json_schema"]["schema"]
        import jsonschema
        jsonschema.validate({"reasoning": "brief", "actions": [{"tool_name": "AnyDiscoveredSkill.any", "parameters": {"new_native_arg": [1, 2]}}],
                             "v": 2, "state": "wait", "calls": [], "ledger": {"pending_steps": ["task"]}}, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"reasoning": "x" * 321}, schema)
        with patch.dict(sys.modules, {"_owned_jawl_delivery": SimpleNamespace(native_companion_chat_active=lambda: False)}):
            goal_schema = provider._request_kwargs(SimpleNamespace(tool_transport="json_envelope"))["response_format"]["json_schema"]["schema"]
        jsonschema.validate({"reasoning": "x" * 5000, "v": 2, "state": "act"}, goal_schema)

    def test_remote_native_transport_optout_and_custom_schema_are_untouched(self):
        for url, transport, fmt in (
            ("https://remote.example/v1", "json_envelope", {"type": "json_object"}),
            ("http://127.0.0.1/v1", "native", {"type": "json_object"}),
            ("http://127.0.0.1/v1", "json_envelope", None),
            ("http://127.0.0.1/v1", "json_envelope", {"type": "json_schema", "json_schema": {"schema": {"type": "array"}}}),
        ):
            with self.subTest(url=url, transport=transport, fmt=fmt):
                original = {"tools": ["all"], **({"response_format": fmt} if fmt is not None else {})}
                provider = self.provider(url, original)
                self.assertEqual(provider._request_kwargs(SimpleNamespace(tool_transport=transport)), original)

    def test_install_is_idempotent_and_detects_replaced_wrapper(self):
        class Provider:
            def _request_kwargs(self, request):
                return {}
        first = extension.install_native_json_format(Provider)
        self.assertIs(extension.install_native_json_format(Provider), first)
        Provider._request_kwargs = lambda self, request: {}
        with self.assertRaises(RuntimeError):
            extension.install_native_json_format(Provider)
