import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.attention import AttentionPresence  # noqa: E402
from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority  # noqa: E402


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

    def test_active_user_suppresses_proactive_screen_speech(self):
        attention = AttentionPresence(
            cooldown_seconds=0,
            activity_provider=lambda: {
                "status": "verified",
                "user_active": True,
                "idle_seconds": 3.2,
                "foreground_class": "Editor",
            },
        )
        result = attention.consume(_event("РћС€РёР±РєР° РІ СЂРµРґР°РєС‚РѕСЂРµ", event_id="active"))
        self.assertEqual(result["status"], "suppressed")
        self.assertEqual(result["reason"], "user_active")
        self.assertEqual(attention.state()["activity"]["foreground_class"], "Editor")

    def test_active_conversation_suppresses_proactive_screen_speech(self):
        arbiter = TurnArbiter()
        token = arbiter.begin(TurnPriority.USER_FINAL)
        attention = AttentionPresence(cooldown_seconds=0, turn_arbiter=arbiter)

        result = attention.consume(_event("Ошибка в активном диалоге"))

        self.assertEqual(result["status"], "suppressed")
        self.assertEqual(result["reason"], "conversation_active")
        arbiter.complete(token)

    def test_activity_provider_failure_is_degraded_but_does_not_break_gate(self):
        attention = AttentionPresence(
            cooldown_seconds=0,
            activity_provider=lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
        )
        result = attention.consume(_event("РћС€РёР±РєР°", significance=3, event_id="activity-failure"))
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(attention.state()["activity"]["status"], "degraded")

    def test_quiet_hours_suppress_proactive_intents_and_support_midnight(self):
        attention = AttentionPresence(
            cooldown_seconds=0,
            quiet_hours="22:00-07:00",
            clock=lambda: datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc),
        )
        result = attention.consume(_event("Ошибка", event_id="quiet"))
        self.assertEqual(result["status"], "suppressed")
        self.assertEqual(result["reason"], "quiet_hours_active")
        self.assertTrue(attention.state()["quiet_hours_active"])

    def test_quiet_hours_configuration_is_validated_and_preserved(self):
        attention = AttentionPresence(quiet_hours="22:00-07:00")
        attention.configure(dnd=True)
        self.assertEqual(attention.state()["quiet_hours"], "22:00-07:00")
        with self.assertRaises(ValueError):
            attention.configure(quiet_hours="25:00-07:00")


if __name__ == "__main__":
    unittest.main()
