"""Unit tests for the owned top-level action repair hook (no JAWL import)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.native_jawl_action_repair import (  # noqa: E402
    install_native_action_repair,
    repair_raw_answer,
)

TERMINAL = "HostTerminalMessages.send_message_to_terminal"


class FakeLoop:
    def _parse_response(self, raw_answer):
        # Emulate the native parser: an actions envelope parses, a bare
        # top-level action object collapses into empty actions.
        import json

        try:
            data = json.loads(raw_answer)
        except ValueError:
            return None, "invalid json"
        if isinstance(data, dict) and isinstance(data.get("actions"), list):
            actions = data["actions"]
            if actions and isinstance(actions[0], dict) and actions[0].get("tool_name"):
                return SimpleNamespace(actions=actions, goal_state=""), None
            return SimpleNamespace(actions=[], goal_state=""), None
        return SimpleNamespace(actions=[], goal_state=""), None


class SimpleNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ActionRepairTests(unittest.TestCase):
    def test_perception_is_source_filled_next_to_native_response_fields(self):
        from pydantic import BaseModel
        from unittest.mock import patch
        from types import SimpleNamespace as NS
        from jawl_voicecompanion.native_jawl_action_repair import _with_perception
        class Response(BaseModel):
            observation: str = "checked result"
            @property
            def thoughts(self):
                return "[Observation]: " + self.observation
        with patch.dict(sys.modules, {"src.l3_agent.context.companion": NS(current_perception=lambda: "Video: two cars; audio: music")}):
            response = _with_perception(Response())
        self.assertEqual(response.perception, "Video: two cars; audio: music")
        self.assertIn("[Perception]", response.thoughts)
        self.assertIn("[Observation]", response.thoughts)

    def test_bare_top_level_action_is_wrapped(self):
        raw = '{"tool_name": "%s", "parameters": {"message": "Привет!"}}' % TERMINAL
        repaired = repair_raw_answer(raw)
        self.assertIn('"actions"', repaired)
        self.assertIn('"text"', repaired)
        self.assertNotIn('"message"', repaired)

    def test_proper_envelope_is_untouched(self):
        raw = '{"actions": [{"tool_name": "%s", "parameters": {"text": "ok"}}]}' % TERMINAL
        self.assertEqual(repair_raw_answer(raw), raw)

    def test_non_json_and_thoughts_are_untouched(self):
        self.assertEqual(repair_raw_answer("hello"), "hello")
        raw = '{"observation": "x", "reasoning": "y"}'
        self.assertEqual(repair_raw_answer(raw), raw)

    def test_random_extra_keys_are_not_wrapped(self):
        raw = '{"foo": 1, "bar": 2}'
        self.assertEqual(repair_raw_answer(raw), raw)

    def test_install_wraps_parse_and_falls_back(self):
        loop = FakeLoop()
        install_native_action_repair(FakeLoop)
        bare = '{"tool_name": "%s", "parameters": {"message": "Связь есть."}}' % TERMINAL
        parsed, error = loop._parse_response(bare)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.actions[0]["parameters"]["text"], "Связь есть.")
        # Already-valid envelopes still parse.
        good = '{"actions": [{"tool_name": "%s", "parameters": {"text": "ok"}}]}' % TERMINAL
        parsed, error = loop._parse_response(good)
        self.assertEqual(parsed.actions[0]["parameters"]["text"], "ok")
        # Unrepairable input keeps the native empty-actions result.
        parsed, error = loop._parse_response('{"foo": 1}')
        self.assertEqual(parsed.actions, [])


if __name__ == "__main__":
    unittest.main()
