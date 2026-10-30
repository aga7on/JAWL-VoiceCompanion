"""Native action proof cannot pass on late/failed tools or unrelated memory."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("owned_agent_work_test", ROOT / "scripts/run_owned_agent_work_acceptance.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class AgentWorkAcceptanceTests(unittest.TestCase):
    def test_policy_acceptance_rejects_generic_errors_and_unverified_final(self):
        gateway = entry.TaskGateway.__new__(entry.TaskGateway)
        gateway.reader = None
        gateway.finals = {'turn': entry.NATIVE_POLICY_DENIAL_REASON}
        for terminal, reason in [('turn.error', 'missing reply'), ('assistant.final', entry.NATIVE_POLICY_DENIAL_REASON)]:
            gateway._submit = lambda *args, terminal=terminal: ('turn', terminal)
            gateway.errors = {'turn': reason}
            with self.assertRaises(entry.ProfileFailure):
                gateway.turn('test', policy_refusal=True)
        gateway._submit = lambda *args: ('turn', 'turn.error')
        gateway.errors = {'turn': entry.NATIVE_POLICY_DENIAL_REASON}
        self.assertEqual(gateway.turn('test', policy_refusal=True), ('turn', entry.NATIVE_POLICY_DENIAL_REASON))

    def test_policy_journal_rejects_retries_and_success_after_denial(self):
        rows = [{'companion_turn_id': 'turn', 'event': 'action_started', 'tool_name': 'HostOSWriter.write_file'},
                {'companion_turn_id': 'turn', 'event': 'action_finished', 'tool_name': 'HostOSWriter.write_file', 'is_success': False}]
        self.assertTrue(entry.policy_journal_proof(rows, 'turn')['writer_denied'])
        with self.assertRaises(ValueError):
            entry.policy_journal_proof(rows + rows, 'turn')
        with self.assertRaises(ValueError):
            entry.policy_journal_proof(rows + [{'companion_turn_id': 'turn', 'event': 'action_finished',
                                              'tool_name': 'HostTerminalMessages.send_message_to_terminal', 'is_success': True}], 'turn')
    def test_browser_report_requires_post_effect_llm_context_not_a_planned_confirmation(self):
        effects = [{"companion_turn_id": "current", "event": "action_finished", "is_success": True,
                    "tool_name": "BrowserInteraction.click", "timestamp": "2026-10-16T00:00:02+00:00"},
                   {"companion_turn_id": "current", "event": "action_started", "tool_name": entry.TERMINAL_TOOL,
                    "timestamp": "2026-10-16T00:00:04+00:00"}]
        good = {"turn_id": "current", "created_at": "2026-10-16T00:00:03+00:00",
                "messages": [{"role": "user", "chars": 100, "acceptance_marker_counts": [1], "native_browser_marker_counts": [1]}]}
        self.assertTrue(entry.context_observation_proof(effects, [good], "current", "BrowserInteraction.click")
                        ["observed_after_effect_before_terminal"])
        for context in (dict(good, turn_id="other"), dict(good, created_at="2026-10-16T00:00:01+00:00"),
                        dict(good, created_at="2026-10-16T00:00:05+00:00"),
                        dict(good, messages=[{"role": "system", "acceptance_marker_counts": [1]}]),
                        dict(good, messages=[{"role": "user", "acceptance_marker_counts": [0]}]),
                        dict(good, messages=[{"role": "user", "acceptance_marker_counts": [1]}])):
            with self.subTest(context=context), self.assertRaises(ValueError):
                entry.context_observation_proof(effects, [context], "current", "BrowserInteraction.click")
        extraction = {"companion_turn_id": "current", "event": "action_finished", "is_success": True,
                      "tool_name": "BrowserExtraction.extract_text", "timestamp": "2026-10-16T00:00:02.5+00:00"}
        result = entry.context_observation_proof(effects + [extraction],
                                                [dict(good, messages=[{"role": "user", "chars": 100, "acceptance_marker_counts": [1]}])],
                                                "current", "BrowserInteraction.click")
        self.assertEqual(result["source"], "native_BrowserExtraction_result")

    def test_form_read_must_follow_save_effect_and_precede_reply_with_either_native_read(self):
        click = {"companion_turn_id": "current", "event": "action_finished", "is_success": True,
                 "tool_name": "BrowserInteraction.click"}
        terminal = {"companion_turn_id": "current", "event": "action_started", "tool_name": entry.TERMINAL_TOOL}
        allowed = {"BrowserExtraction.extract_text", "BrowserNavigation.navigate"}
        for tool in allowed:
            read = dict(click, tool_name=tool)
            result = entry.journal_read_after_effect([click, read, terminal], "current", "BrowserInteraction.click", allowed)
            self.assertEqual(result["fresh_read_tool"], tool)
            for events in ([read, click, terminal], [click, terminal, read],
                           [click, dict(read, is_success=False), terminal],
                           [click, dict(read, companion_turn_id="other"), terminal]):
                with self.subTest(tool=tool, events=events), self.assertRaises(ValueError):
                    entry.journal_read_after_effect(events, "current", "BrowserInteraction.click", allowed)

    def test_required_effect_must_succeed_on_same_turn_before_terminal_action(self):
        effect = {"companion_turn_id": "current", "event": "action_finished",
                  "tool_name": "HostOSWriter.write_file", "is_success": True}
        terminal = {"companion_turn_id": "current", "event": "action_started", "tool_name": entry.TERMINAL_TOOL}
        proof = entry.journal_proof([effect, terminal], "current", {"HostOSWriter.write_file"})
        self.assertEqual(proof["required_tools_completed_before_terminal"], ["HostOSWriter.write_file"])
        for events in ([terminal, effect], [dict(effect, is_success=False), terminal],
                       [dict(effect, companion_turn_id="historical"), terminal], [effect]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                entry.journal_proof(events, "current", {"HostOSWriter.write_file"})

    def test_canonical_memory_requires_one_active_exact_key_value_pair(self):
        current = {"memory_key": "test", "status": "active", "value": "corrected", "revision": 2}
        payload = {"structured": {"memories": [dict(current, status="superseded", value="old"), current]}}
        self.assertEqual(entry.current_memory(payload, "test", "corrected")["revision"], 2)
        for rows in ([dict(current, value="old"), dict(current, memory_key="unrelated")],
                     [current, current], [dict(current, status="superseded")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                entry.current_memory({"structured": {"memories": rows}}, "test", "corrected")

    def test_journal_ignores_only_incomplete_concurrent_tail_and_rejects_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.jsonl"
            path.write_bytes(b'{"event":"durable"}\n{"event":"incomplete"')
            self.assertEqual(entry.read_journal(path), [{"event": "durable"}])
            path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "bound"):
                entry.read_journal(path)

    def test_disposable_form_persists_value_and_counts_each_save(self):
        fixture = entry.Fixture("Owned test page")
        with requests.Session() as session:
            session.trust_env = False
            with fixture:
                self.assertIn("Owned test page", session.get(fixture.url, timeout=3).text)
                self.assertEqual(session.post(fixture.url + "save", json={"value": "saved"}, timeout=3).status_code, 200)
                self.assertEqual(fixture.posts, 1)
                self.assertEqual(fixture.value, "saved")
                self.assertIn("Saved: saved", session.get(fixture.url, timeout=3).text)
                self.assertEqual(session.post(fixture.url + "save", json={"value": "x" * 129}, timeout=3).status_code, 400)
                self.assertEqual(fixture.posts, 1)
        self.assertTrue(fixture.closed)


if __name__ == "__main__":
    unittest.main()
