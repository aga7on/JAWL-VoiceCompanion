import sys
import threading
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway, validate_response_envelope  # noqa: E402
from jawl_voicecompanion.jawl_gateway_contract import JawlGatewayEvent  # noqa: E402
from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled  # noqa: E402
from jawl_voicecompanion.arbiter import TurnArbiter, TurnPriority  # noqa: E402
from jawl_voicecompanion.perception_fusion import CognitiveTurnDecision, SenseNovaPerceptionBridge  # noqa: E402
from jawl_voicecompanion.attention import AttentionPresence  # noqa: E402


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

    def test_native_stream_uses_deltas_but_final_envelope_is_authoritative(self):
        native = TextGateway().handle_text("seed")
        native.update({
            "response_id": "jawl-response-stream-1",
            "turn_id": "jawl-turn-stream-1",
            "text": "Первая часть. Вторая часть.",
        })

        class NativeStreamingResponder:
            supports_native_envelope = True

            def stream_envelope(self, _text, cancel_event=None, correlation_id=None):
                del cancel_event, correlation_id
                yield {"type": "delta", "text": "Первая часть. "}
                yield {"type": "delta", "text": "Вторая часть."}
                yield {"type": "final", "response": native}

        events = list(TextGateway(responder=NativeStreamingResponder()).stream_text("stream"))
        self.assertEqual([event["type"] for event in events], ["delta", "delta", "final"])
        self.assertEqual("".join(event["text"] for event in events[:-1]), native["text"])
        self.assertEqual(events[-1]["response"], native)

    def test_native_stream_mismatch_is_discarded_as_terminal_error(self):
        native = TextGateway().handle_text("seed")
        native["text"] = "authoritative final"

        class MismatchedResponder:
            supports_native_envelope = True

            def stream_envelope(self, _text, cancel_event=None, correlation_id=None):
                del cancel_event, correlation_id
                yield {"type": "delta", "text": "provisional wrong"}
                yield {"type": "final", "response": native}

        events = list(TextGateway(responder=MismatchedResponder()).stream_text("stream"))
        self.assertEqual([event["type"] for event in events], ["delta", "error", "final"])
        self.assertTrue(events[1]["discard_deltas"])
        self.assertFalse(events[-1]["response"]["speak"])

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

    def test_partial_provider_failure_is_terminal_and_next_turn_recovers(self):
        class FlakyResponder:
            def __init__(self):
                self.calls = 0

            def stream(self, _text, cancel_event=None):
                del cancel_event
                self.calls += 1
                if self.calls == 1:
                    yield "provisional output"
                    raise ConnectionError("provider dropped after delta")
                yield "recovered output"

        gateway = TextGateway(responder=FlakyResponder(), brain_name="provider")
        failed = list(gateway.stream_text("first"))
        self.assertEqual([event["type"] for event in failed], ["delta", "error", "final"])
        self.assertTrue(failed[1]["discard_deltas"])
        self.assertFalse(failed[-1]["response"]["speak"])
        self.assertEqual(failed[-1]["response"]["avatar"]["state"], "error")

        recovered = list(gateway.stream_text("second"))
        self.assertEqual([event["type"] for event in recovered], ["delta", "final"])
        self.assertEqual(recovered[-1]["response"]["text"], "recovered output")
        self.assertNotEqual(failed[-1]["response"]["turn_id"], recovered[-1]["response"]["turn_id"])

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

    def test_transport_correlation_is_preserved_across_stream_and_state(self):
        correlation = "turn-browser-voice-42"
        events = list(TextGateway().stream_text(
            "проверка", session_id="browser-mic-42", correlation_id=correlation,
        ))
        self.assertTrue(events)
        self.assertTrue(all(event["correlation_id"] == correlation for event in events))
        final = events[-1]
        self.assertEqual(final["type"], "final")
        state = TextGateway()
        list(state.stream_text("проверка", session_id="browser-mic-42", correlation_id=correlation))
        self.assertEqual(state.state()["last_turn"]["correlation_id"], correlation)

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

    def test_proactive_turn_deferred_when_user_final_active(self):
        """When USER_FINAL is active, a PROACTIVE turn must NOT cancel the user,

        must NOT invoke responder, and bridge must return llm_invoked=False, audio_delivered=False.
        """
        arbiter = TurnArbiter()
        responder_calls: list[str] = []

        def tracked_responder(text: str, cancel_event=None):
            del cancel_event
            responder_calls.append(text)
            return "Ответ нейросети"

        gateway = TextGateway(responder=tracked_responder, arbiter=arbiter)
        bridge = SenseNovaPerceptionBridge(sensenova_client=gateway)

        # 1. Activate user token with USER_FINAL priority
        user_tok = arbiter.begin(TurnPriority.USER_FINAL)
        self.assertTrue(arbiter.is_current(user_tok))
        self.assertFalse(user_tok.cancelled)

        # 2. Invoke proactive turn through bridge
        decision = CognitiveTurnDecision(
            action="proactive_turn",
            proactive_packet={"prompt": "Пользователь молчит уже 10 секунд"},
            reason="Silence gap threshold met",
        )
        res = bridge.process_turn_decision(decision)

        # 3. Assertions required by specification:
        # - user_tok.cancelled строго False! Исходный user token НЕ отменился!
        self.assertIs(user_tok.cancelled, False)
        self.assertTrue(arbiter.is_current(user_tok))

        # - responder НЕ вызывался!
        self.assertEqual(len(responder_calls), 0)

        # - Bridge вернул llm_invoked=False, audio_delivered=False
        self.assertFalse(res["llm_invoked"])
        self.assertFalse(res["audio_delivered"])
        self.assertFalse(res["dispatched"])

    def test_user_final_supersedes_and_cancels_previous_user_final(self):
        """A new USER_FINAL must supersede and cancel the previous active USER_FINAL."""
        arbiter = TurnArbiter()
        tok1 = arbiter.begin(TurnPriority.USER_FINAL)
        self.assertTrue(arbiter.is_current(tok1))
        self.assertFalse(tok1.cancelled)

        tok2 = arbiter.begin(TurnPriority.USER_FINAL)
        self.assertTrue(tok1.cancelled)
        self.assertEqual(tok1.cancel_reason, "superseded_by_newer_priority_turn")
        self.assertTrue(tok1.cancel_event.is_set())
        self.assertFalse(tok2.cancelled)
        self.assertTrue(arbiter.is_current(tok2))

    def test_proactive_turn_succeeds_when_no_higher_priority_active(self):
        """When no user turn is active, PROACTIVE turn is admitted and runs."""
        arbiter = TurnArbiter()
        responder_calls: list[str] = []

        def tracked_responder(text: str, cancel_event=None):
            del cancel_event
            responder_calls.append(text)
            return "Проактивное приветствие"

        gateway = TextGateway(responder=tracked_responder, arbiter=arbiter)
        bridge = SenseNovaPerceptionBridge(sensenova_client=gateway)

        decision = CognitiveTurnDecision(
            action="proactive_turn",
            proactive_packet={"prompt": "Пора сделать перерыв"},
        )
        res = bridge.process_turn_decision(decision)

        self.assertTrue(res["dispatched"])
        self.assertTrue(res["llm_invoked"])
        self.assertEqual(len(responder_calls), 1)
        self.assertEqual(res["speech_output"], "Проактивное приветствие")

    def test_proactive_turn_suppressed_when_dnd_active(self):
        """DND active via packet or attention must suppress proactive turn immediately."""
        arbiter = TurnArbiter()
        responder_calls: list[str] = []

        def tracked_responder(text: str, cancel_event=None):
            del cancel_event
            responder_calls.append(text)
            return "Ответ"

        gateway = TextGateway(responder=tracked_responder, arbiter=arbiter)

        # 1. DND active in packet
        bridge1 = SenseNovaPerceptionBridge(sensenova_client=gateway)
        decision_dnd_packet = CognitiveTurnDecision(
            action="proactive_turn",
            proactive_packet={"prompt": "Привет", "dnd": True},
        )
        res1 = bridge1.process_turn_decision(decision_dnd_packet)
        self.assertFalse(res1["dispatched"])
        self.assertEqual(res1["reason"], "dnd_active")
        self.assertFalse(res1["llm_invoked"])
        self.assertEqual(len(responder_calls), 0)

        # 2. DND active in attention
        attention = AttentionPresence(dnd=True)
        bridge2 = SenseNovaPerceptionBridge(sensenova_client=gateway, attention=attention)
        decision_normal = CognitiveTurnDecision(
            action="proactive_turn",
            proactive_packet={"prompt": "Привет"},
        )
        res2 = bridge2.process_turn_decision(decision_normal)
        self.assertFalse(res2["dispatched"])
        self.assertEqual(res2["reason"], "dnd_active")
        self.assertFalse(res2["llm_invoked"])
        self.assertEqual(len(responder_calls), 0)

    def test_gateway_handle_text_returns_safe_deferred_envelope(self):
        """Direct call to handle_text with lower priority returns deferred envelope."""
        arbiter = TurnArbiter()
        user_tok = arbiter.begin(TurnPriority.USER_FINAL)

        called = False

        def mock_responder(text, cancel_event=None):
            nonlocal called
            called = True
            return "Не должно выполниться"

        gateway = TextGateway(responder=mock_responder, arbiter=arbiter)
        resp = gateway.handle_text("Фоновая проверка", priority=TurnPriority.PROACTIVE)

        self.assertFalse(called)
        self.assertFalse(user_tok.cancelled)
        self.assertFalse(resp["admitted"])
        self.assertEqual(resp["status"], "deferred")
        self.assertEqual(resp["reason"], "higher_priority_work_active")
        self.assertEqual(resp["text"], "")
        self.assertFalse(resp["speak"])
        self.assertEqual(resp["schema_version"], 1)
        validate_response_envelope(resp)


class ConversationHistoryTests(unittest.TestCase):
    def test_turn_is_persisted_and_reread_from_disk(self):
        import tempfile
        from jawl_voicecompanion.history import ConversationHistory  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationHistory(Path(tmp) / "conversation.ndjson")
            gateway = TextGateway(history_store=store)
            response = gateway.handle_text("Привет, запомни меня", session_id="seed-1")
            self.assertTrue(store.path.exists())
            turns = store.turns()
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]["user"], "Привет, запомни меня")
            self.assertEqual(turns[0]["response"]["text"], response["text"])
            reloaded = ConversationHistory(store.path).turns()
            self.assertEqual(reloaded[0]["user"], "Привет, запомни меня")

    def test_enriched_provider_text_does_not_replace_the_saved_user_message(self):
        import tempfile
        from jawl_voicecompanion.history import ConversationHistory  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationHistory(Path(tmp) / "conversation.ndjson")
            gateway = TextGateway(history_store=store)
            gateway.handle_text(
                "prior transcript + current request",
                history_user_text="current request",
            )
            self.assertEqual(store.turns()[0]["user"], "current request")

    def test_turn_history_prefers_persisted_store(self):
        import tempfile
        from jawl_voicecompanion.history import ConversationHistory  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationHistory(Path(tmp) / "conversation.ndjson")
            gateway = TextGateway(history_store=store)
            list(gateway.stream_text("голосовая реплика", session_id="voice-1"))
            history = gateway.turn_history(limit=50)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["user"], "голосовая реплика")


if __name__ == "__main__":
    unittest.main()
