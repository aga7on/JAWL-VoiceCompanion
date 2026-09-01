import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled  # noqa: E402


class GatewayTests(unittest.TestCase):
    def test_text_turn_returns_valid_response_envelope_shape(self):
        response = TextGateway().handle_text("Привет")
        for field in ("schema_version", "response_id", "turn_id", "text", "speak", "emotion", "avatar", "actions", "interruptible", "proactive"):
            self.assertIn(field, response)
        self.assertEqual(response["schema_version"], 1)
        self.assertTrue(response["speak"])

    def test_empty_turn_is_silent_and_usable(self):
        response = TextGateway().handle_text("   ")
        self.assertFalse(response["speak"])
        self.assertEqual(response["avatar"]["state"], "idle")

    def test_health_reports_degraded_dependencies_explicitly(self):
        health = TextGateway().health()
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["components"]["hostos"], "policy_only_dry_run")

    def test_real_brain_outage_falls_back_to_usable_text(self):
        def unavailable(_text):
            raise ConnectionError("not available")

        gateway = TextGateway(responder=unavailable, brain_name="jawl_terminal")
        response = gateway.handle_text("Проверь связь")
        self.assertIn("недоступен", response["text"])
        self.assertEqual(gateway.health()["components"]["jawl"], "offline_fallback")

    def test_new_user_turn_cancels_pending_responder(self):
        started = threading.Event()

        class BlockingResponder:
            def respond(self, text, cancel_event):
                if text == "старый":
                    started.set()
                    cancel_event.wait(2)
                    raise JawlTurnCancelled("cancelled")
                return "Новый ответ"

        gateway = TextGateway(responder=BlockingResponder(), brain_name="jawl_terminal")
        old_result = {}
        thread = threading.Thread(target=lambda: old_result.setdefault("value", gateway.handle_text("старый")))
        thread.start()
        self.assertTrue(started.wait(1))
        new_result = gateway.handle_text("новый")
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(new_result["text"], "Новый ответ")
        self.assertFalse(old_result["value"]["speak"])

    def test_stream_text_emits_deltas_and_final_envelope_once(self):
        class StreamingResponder:
            def stream(self, text, cancel_event=None):
                del text, cancel_event
                yield "first "
                yield "second"

        gateway = TextGateway(responder=StreamingResponder(), brain_name="streaming_test")
        events = list(gateway.stream_text("prompt"))
        self.assertEqual([event["type"] for event in events], ["delta", "delta", "final"])
        self.assertEqual("".join(event["text"] for event in events[:-1]), "first second")
        self.assertEqual(events[-1]["response"]["text"], "first second")
        self.assertEqual(gateway.state()["last_turn"]["response"]["text"], "first second")


if __name__ == "__main__":
    unittest.main()
