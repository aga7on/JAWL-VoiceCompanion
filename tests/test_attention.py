import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.attention import AttentionPresence  # noqa: E402


def _event(summary="editor changed", significance=1, event_id="screen-1"):
    return {
        "schema_version": 1,
        "event_id": event_id,
        "session_id": "test",
        "type": "SCREEN_DELTA",
        "payload": {
            "summary": summary,
            "significance": significance,
            "changed": True,
            "raw_frame_persisted": False,
        },
    }


class AttentionTests(unittest.TestCase):
    def test_low_salience_screen_change_is_not_proactive(self):
        attention = AttentionPresence(cooldown_seconds=0)
        result = attention.consume(_event())
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(attention.intents(), [])

    def test_salient_change_creates_bounded_speak_intent(self):
        delivered = []
        attention = AttentionPresence(cooldown_seconds=0, intent_sink=delivered.append)
        result = attention.consume(_event("Появилась ошибка в редакторе"))
        self.assertEqual(result["status"], "proposed")
        self.assertTrue(result["delivered"])
        intent = result["intent"]
        self.assertEqual(intent["type"], "SPEAK_INTENT")
        self.assertEqual(intent["payload"]["significance"], 3)
        self.assertFalse(intent["payload"]["raw_frame_persisted"])
        self.assertEqual(delivered, [intent])

    def test_dnd_duplicate_and_budget_are_enforced(self):
        attention = AttentionPresence(cooldown_seconds=0, budget_per_hour=1, dnd=True)
        self.assertEqual(attention.consume(_event("Ошибка", event_id="dnd"))["status"], "suppressed")
        attention.configure(dnd=False)
        self.assertEqual(attention.consume(_event("Ошибка", event_id="one"))["status"], "proposed")
        self.assertEqual(attention.consume(_event("Ошибка", event_id="one"))["status"], "duplicate")
        self.assertEqual(attention.consume(_event("Ошибка", event_id="two"))["reason"], "proactive_budget_exhausted")

    def test_private_summary_is_never_forwarded(self):
        delivered = []
        attention = AttentionPresence(intent_sink=delivered.append)
        result = attention.consume(_event("Password error", event_id="private"))
        self.assertEqual(result["reason"], "screen_summary_private")
        self.assertEqual(delivered, [])


if __name__ == "__main__":
    unittest.main()
