"""Kernel top-level action repair for the native JAWL parser.

Spec lineage: the retired product extension ``native_jawl_action_repair``
(ADR-049 slice 5). ``parse_with_repair`` is invoked natively by
``ReactLoop._parse_response``; native parsing stays authoritative.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-repair-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l3_agent.react import action_repair  # noqa: E402

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
    def parse(self, loop, raw):
        return action_repair.parse_with_repair(
            loop, raw, lambda lp, raw_answer: lp._parse_response(raw_answer)
        )

    def test_perception_is_source_filled_next_to_native_response_fields(self):
        from pydantic import BaseModel
        from types import SimpleNamespace as NS

        class Response(BaseModel):
            observation: str = "checked result"

            @property
            def thoughts(self):
                return "[Observation]: " + self.observation
        with patch.dict(sys.modules, {"src.l3_agent.context.companion": NS(current_perception=lambda: "Video: two cars; audio: music")}):
            response = action_repair._with_perception(Response())
        self.assertEqual(response.perception, "Video: two cars; audio: music")
        self.assertIn("[Perception]", response.thoughts)
        self.assertIn("[Observation]", response.thoughts)

    def test_bare_top_level_action_is_wrapped(self):
        raw = '{"tool_name": "%s", "parameters": {"message": "Привет!"}}' % TERMINAL
        repaired = action_repair.repair_raw_answer(raw)
        self.assertIn('"actions"', repaired)
        self.assertIn('"text"', repaired)
        self.assertNotIn('"message"', repaired)

    def test_proper_envelope_is_untouched(self):
        raw = '{"actions": [{"tool_name": "%s", "parameters": {"text": "ok"}}]}' % TERMINAL
        self.assertEqual(action_repair.repair_raw_answer(raw), raw)

    def test_non_json_and_thoughts_are_untouched(self):
        self.assertEqual(action_repair.repair_raw_answer("hello"), "hello")
        raw = '{"observation": "x", "reasoning": "y"}'
        self.assertEqual(action_repair.repair_raw_answer(raw), raw)

    def test_random_extra_keys_are_not_wrapped(self):
        raw = '{"foo": 1, "bar": 2}'
        self.assertEqual(action_repair.repair_raw_answer(raw), raw)

    def test_parse_with_repair_wraps_and_falls_back(self):
        loop = FakeLoop()
        bare = '{"tool_name": "%s", "parameters": {"message": "Связь есть."}}' % TERMINAL
        parsed, error = self.parse(loop, bare)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.actions[0]["parameters"]["text"], "Связь есть.")
        # Already-valid envelopes still parse.
        good = '{"actions": [{"tool_name": "%s", "parameters": {"text": "ok"}}]}' % TERMINAL
        parsed, error = self.parse(loop, good)
        self.assertEqual(parsed.actions[0]["parameters"]["text"], "ok")
        # Unrepairable input keeps the native empty-actions result.
        parsed, error = self.parse(loop, '{"foo": 1}')
        self.assertEqual(parsed.actions, [])


if __name__ == "__main__":
    unittest.main()
