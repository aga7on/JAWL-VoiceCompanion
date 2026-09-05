import sys
import threading
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway, validate_response_envelope  # noqa: E402
from jawl_voicecompanion.jawl_gateway_contract import JawlGatewayEvent  # noqa: E402
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

    def test_invalid_responder_text_falls_back_to_canonical_envelope(self):
        def malformed(_text):
            return None

        gateway = TextGateway(responder=malformed, brain_name="provider")
        response = gateway.handle_text("provider check")
        validate_response_envelope(response)
        self.assertEqual(response["avatar"]["state"], "speaking")
        self.assertEqual(gateway.health()["components"]["jawl"], "offline_fallback")

    def test_native_responder_envelope_is_preserved_for_text_and_stream(self):
        native = TextGateway().handle_text("seed")
        native.update({
            "response_id": "jawl-response-7",
            "turn_id": "jawl-turn-7",
            "emotion": {"id": "joy", "intensity": 0.9, "confidence": 0.95},
            "avatar": {"expression": "joy", "motion": "wave", "state": "speaking"},
            "voice": {"provider": "tera", "voice_id": "mita", "rate": 1.1, "style": "warm"},
            "actions": [{"action_id": "a-7", "tool": "demo", "type": "observe"}],
        })

        class NativeResponder:
            supports_native_envelope = True

            def respond_envelope(self, _text, cancel_event=None):
                del cancel_event
                return native

        gateway = TextGateway(responder=NativeResponder(), brain_name="native")
        response = gateway.handle_text("preserve")
        self.assertEqual(response, native)
        streamed = list(gateway.stream_text("preserve stream"))
        self.assertEqual(streamed[-1]["response"], native)
        self.assertEqual(streamed[0]["text"], native["text"])

    def test_native_provider_failure_is_terminal_and_not_speakable(self):
        class NativeUnavailable:
            supports_native_envelope = True

            def respond_envelope(self, _text, cancel_event=None):
                del cancel_event
                raise ConnectionError("provider offline")

        response = TextGateway(responder=NativeUnavailable()).handle_text("request")
        self.assertFalse(response["speak"])
        self.assertEqual(response["avatar"]["state"], "error")
        self.assertEqual(response["emotion"]["id"], "error")

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

    def test_stream_fallback_messages_preserve_russian_utf8(self):
        empty_events = list(TextGateway().stream_text("   "))
        self.assertEqual(empty_events[-1]["response"]["text"], "Я не услышала текст. Попробуй повторить команду.")

        def unavailable_stream(_text, cancel_event=None):
            del cancel_event
            raise ConnectionError("offline")
            yield "unreachable"

        offline_events = list(TextGateway(responder=unavailable_stream).stream_text("проверка"))
        self.assertIn("JAWL сейчас недоступен", offline_events[0]["text"])

        class CancelledStream:
            def stream(self, _text, cancel_event=None):
                del cancel_event
                raise JawlTurnCancelled("cancelled")
                yield "unreachable"

        cancelled_events = list(TextGateway(responder=CancelledStream()).stream_text("стоп"))
        self.assertEqual(cancelled_events[-1]["response"]["text"], "Ответ отменён новым сообщением.")

    def test_response_envelope_rejects_invalid_nested_values(self):
        valid = TextGateway().handle_text("Привет")
        invalid_cases = []

        unknown = deepcopy(valid)
        unknown["unexpected"] = True
        invalid_cases.append(unknown)

        bad_emotion = deepcopy(valid)
        bad_emotion["emotion"]["intensity"] = 2
        invalid_cases.append(bad_emotion)

        bad_avatar = deepcopy(valid)
        bad_avatar["avatar"]["state"] = "executing"
        invalid_cases.append(bad_avatar)

        authority = deepcopy(valid)
        authority["actions"] = [{"tool": "shell.exec", "requested_access_level": 3}]
        invalid_cases.append(authority)

        for envelope in invalid_cases:
            with self.subTest(envelope=envelope):
                with self.assertRaises(ValueError):
                    validate_response_envelope(envelope)

    def test_native_jawl_event_contract_requires_exact_correlation(self):
        response = TextGateway().handle_text("Привет")
        event = JawlGatewayEvent.from_mapping({
            "schema_version": 1,
            "event_seq": 7,
            "turn_id": response["turn_id"],
            "type": "assistant.final",
            "payload": {"response": response},
        })
        self.assertEqual(event.type, "assistant.final")
        self.assertEqual(event.to_mapping()["turn_id"], response["turn_id"])

        mismatched = deepcopy(response)
        mismatched["turn_id"] = "other-turn"
        with self.assertRaises(ValueError):
            JawlGatewayEvent.from_mapping({
                "schema_version": 1,
                "event_seq": 8,
                "turn_id": response["turn_id"],
                "type": "assistant.final",
                "payload": {"response": mismatched},
            })

    def test_native_jawl_event_contract_rejects_tool_details_and_unknown_fields(self):
        base = {
            "schema_version": 1,
            "event_seq": 1,
            "turn_id": "turn-1",
            "type": "tool.started",
            "payload": {"action_id": "action-1", "tool": "hostos.shell"},
        }
        event = JawlGatewayEvent.from_mapping(base)
        self.assertEqual(event.payload["tool"], "hostos.shell")

        with self.assertRaises(ValueError):
            JawlGatewayEvent.from_mapping({**base, "unexpected": True})
        with self.assertRaises(ValueError):
            JawlGatewayEvent.from_mapping({
                **base,
                "payload": {"action_id": "action-1", "arguments": {"cmd": "whoami"}},
            })


if __name__ == "__main__":
    unittest.main()
