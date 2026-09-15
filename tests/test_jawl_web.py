import json
import sys
import threading
import unittest
from queue import Empty, Queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled  # noqa: E402
from jawl_voicecompanion.jawl_web import JawlWebAdapter, JawlWebChatAdapter, JawlWebUnavailable  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


class _SseResponse:
    def __init__(self):
        self.lines = Queue()
        self.closed = threading.Event()
        self.lines.put(b'data: {"messages": [], "status": {"state": "online"}}\n')
        self.lines.put(b"\n")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def readline(self):
        while not self.closed.is_set():
            try:
                return self.lines.get(timeout=0.05)
            except Empty:
                continue
        return b""

    def close(self):
        self.closed.set()
        self.lines.put(b"")


class _BrokenOnCloseSseResponse(_SseResponse):
    def readline(self):
        if self.closed.is_set():
            raise AttributeError("closed response has no underlying stream")
        return super().readline()


class _EofSseResponse(_SseResponse):
    """Serve pre-queued SSE lines and then report EOF immediately."""

    def __init__(self, lines):
        self.lines = Queue()
        self.closed = threading.Event()
        for line in lines:
            self.lines.put(line)

    def readline(self):
        try:
            return self.lines.get_nowait()
        except Empty:
            return b""


class JawlWebTests(unittest.TestCase):
    def test_persona_filters_config_secrets(self):
        responses = {
            "/api/config": {
                "values": {
                    "settings:identity.agent_name": "Луна",
                    "settings:system.heartbeat_interval": 30,
                    "env:LLM_API_KEY_1": "must-not-leak",
                }
            }
        }

        def opener(request, timeout):
            self.assertEqual(
                next(value for key, value in request.headers.items() if key.casefold() == "x-console-token"),
                "secret",
            )
            return _Response(responses[request.full_url.removeprefix("http://127.0.0.1:8770")])

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        result = adapter.persona()
        self.assertEqual(result["settings"]["settings:identity.agent_name"], "Луна")
        self.assertNotIn("env:LLM_API_KEY_1", result["settings"])

    def test_hostos_status_is_bounded_and_uses_safe_config_allowlist(self):
        responses = {
            "/api/config": {
                "values": {
                    "interfaces:host.os.enabled": True,
                    "interfaces:host.os.access_level": 3,
                    "interfaces:host.os.secret": "must-not-leak",
                }
            }
        }

        def opener(request, timeout):
            return _Response(responses[request.full_url.removeprefix("http://127.0.0.1:8770")])

        result = JawlWebAdapter("http://127.0.0.1:8770", opener=opener).hostos()
        self.assertEqual(result["access_name"], "ROOT")
        self.assertTrue(result["enabled"])
        self.assertNotIn("secret", str(result))

    def test_remote_url_is_rejected_before_token_can_leave_machine(self):
        with self.assertRaises(ValueError):
            JawlWebAdapter("https://example.invalid", token="secret")

    def test_url_credentials_and_query_are_rejected(self):
        with self.assertRaises(ValueError):
            JawlWebAdapter("http://user:pass@127.0.0.1:8770", token="secret")
        with self.assertRaises(ValueError):
            JawlWebAdapter("http://127.0.0.1:8770/?token=secret", token="secret")

    def test_hostos_control_writes_config_and_restarts_agent_with_token(self):
        calls = []
        responses = {
            ("PUT", "/api/config"): {"ok": True, "written": ["config/interfaces.yaml"]},
            ("POST", "/api/agent/stop"): {"ok": True, "forced": False},
            ("POST", "/api/agent/start"): {"ok": True, "pid": 42},
        }

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            payload = json.loads(request.data.decode("utf-8")) if request.data else None
            calls.append((request.method, path, payload, request.headers.get("X-console-token")))
            return _Response(responses[(request.method, path)])

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        result = adapter.set_hostos_level(3)
        self.assertEqual(result["status"], "synchronized")
        self.assertEqual(result["access_name"], "ROOT")
        self.assertEqual([item[:2] for item in calls], [
            ("PUT", "/api/config"),
            ("POST", "/api/agent/stop"),
            ("POST", "/api/agent/start"),
        ])
        self.assertEqual(calls[0][2]["values"]["interfaces:host.os.access_level"], 3)
        self.assertTrue(calls[0][2]["values"]["interfaces:host.os.enabled"])
        self.assertTrue(all(item[3] == "secret" for item in calls))

    def test_hostos_control_requires_token_and_valid_level(self):
        adapter = JawlWebAdapter("http://127.0.0.1:8770")
        with self.assertRaises(JawlWebUnavailable):
            adapter.set_hostos_level(3)
        tokened = JawlWebAdapter("http://127.0.0.1:8770", token="secret")
        with self.assertRaises(ValueError):
            tokened.set_hostos_level(True)

    def test_structured_memory_uses_native_jawl_routes(self):
        calls = []
        responses = {
            ("GET", "/api/memory?kind=fact&limit=3"): {
                "ok": True, "native": True, "memory": {"memories": [{"memory_key": "user.lang"}]}
            },
            ("POST", "/api/memory"): {
                "ok": True, "native": True, "memory": {"is_success": True, "message": "stored"}
            },
        }

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            payload = json.loads(request.data.decode("utf-8")) if request.data else None
            calls.append((request.method, path, payload))
            return _Response(responses[(request.method, path)])

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        result = adapter.structured_memory("fact", 3)
        self.assertEqual(result["memory"]["memories"][0]["memory_key"], "user.lang")
        adapter.remember_memory(kind="fact", subject="user", predicate="lang", value="ru")
        self.assertEqual(calls[1][2]["operation"], "remember")

    def test_autonomy_journal_uses_bounded_native_projection(self):
        calls = []

        def opener(request, timeout):
            del timeout
            calls.append(request.full_url)
            return _Response({
                "ok": True,
                "native": True,
                "journal": {
                    "source": "jawl.action_journal",
                    "plans": [{"plan_id": "p1", "state": "completed"}],
                },
            })

        adapter = JawlWebAdapter(
            "http://127.0.0.1:8770", token="secret", opener=opener
        )
        result = adapter.autonomy_journal(limit=3, state="completed")
        self.assertEqual(result["plans"][0]["plan_id"], "p1")
        self.assertEqual(calls, ["http://127.0.0.1:8770/api/agent/journal?limit=3&state=completed"])
        with self.assertRaises(ValueError):
            adapter.autonomy_journal(limit=0)

    def test_structured_memory_rejects_native_skill_failure(self):
        def opener(request, timeout):
            del timeout
            return _Response({
                "ok": True,
                "native": True,
                "memory": {"is_success": False, "message": "duplicate key"},
            })

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        with self.assertRaises(JawlWebUnavailable):
            adapter.remember_memory(
                kind="fact", subject="user", predicate="lang", value="ru"
            )

    def test_native_hostos_skill_is_forwarded_without_local_execution(self):
        def opener(request, timeout):
            del timeout
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.full_url, "http://127.0.0.1:8770/api/hostos/skill")
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["skill"], "HostOSWriter.write_file")
            return _Response({"ok": True, "native": True, "result": {"is_success": True}})

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        result = adapter.execute_hostos_skill(
            "HostOSWriter.write_file", {"filepath": "x", "content": "y"}
        )
        self.assertEqual(result["status"], "native")

    def test_native_debug_skill_is_forwarded_without_local_execution(self):
        def opener(request, timeout):
            del timeout
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.full_url, "http://127.0.0.1:8770/api/debug/skill")
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["skill"], "DebugBroker.search_operations")
            return _Response({"ok": True, "native": True, "result": {"is_success": True}})

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        result = adapter.execute_debug_skill(
            "DebugBroker.search_operations", {"query": "x64dbg"}
        )
        self.assertEqual(result["status"], "native")

    def test_native_skill_catalog_uses_current_jawl_registry(self):
        def opener(request, timeout):
            del timeout
            self.assertEqual(
                request.full_url,
                "http://127.0.0.1:8770/api/skills/catalog?limit=4&prefix=HostOS&prefix=DebugBroker",
            )
            return _Response({
                "ok": True,
                "native": True,
                "catalog": {
                    "schema_version": 1,
                    "prefixes": ["HostOS", "DebugBroker"],
                    "skills": [{"name": "HostOSReader.read_file_range", "available": True}],
                },
            })

        adapter = JawlWebAdapter("http://127.0.0.1:8770", opener=opener)
        result = adapter.native_skill_catalog(("HostOS", "DebugBroker"), limit=4)
        assert result["skills"][0]["name"] == "HostOSReader.read_file_range"

    def test_stop_agent_returns_bounded_native_stop_result(self):
        def opener(request, timeout):
            del timeout
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.full_url, "http://127.0.0.1:8770/api/agent/stop")
            return _Response({"ok": True, "forced": True, "pid": 999, "secret": "hidden"})

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        self.assertEqual(adapter.stop_agent(), {"status": "stopped", "forced": True})

    def test_start_agent_returns_bounded_native_start_result(self):
        def opener(request, timeout):
            del timeout
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.full_url, "http://127.0.0.1:8770/api/agent/start")
            return _Response({"ok": True, "pid": 42, "secret": "hidden"})

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        self.assertEqual(adapter.start_agent(), {"status": "started", "pid": 42})

    def test_restart_agent_uses_stop_then_start(self):
        calls = []

        def opener(request, timeout):
            del timeout
            calls.append(request.full_url)
            if request.full_url.endswith("/api/agent/status"):
                return _Response({"ok": True, "running": True, "starting": False})
            if request.full_url.endswith("/api/agent/stop"):
                return _Response({"ok": True, "forced": False})
            self.assertTrue(request.full_url.endswith("/api/agent/start"))
            return _Response({"ok": True, "pid": 42})

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        self.assertEqual(adapter.restart_agent()["status"], "restarted")
        self.assertEqual(calls, [
            "http://127.0.0.1:8770/api/agent/stop",
            "http://127.0.0.1:8770/api/agent/start",
            "http://127.0.0.1:8770/api/agent/status",
        ])

    def test_restart_agent_can_wait_for_structured_memory(self):
        calls = []

        def opener(request, timeout):
            del timeout
            calls.append(request.full_url)
            if request.full_url.endswith("/api/agent/status"):
                return _Response({"ok": True, "running": True, "starting": False})
            if request.full_url.endswith("/api/agent/stop"):
                return _Response({"ok": True, "forced": False})
            if request.full_url.endswith("/api/agent/start"):
                return _Response({"ok": True, "pid": 42})
            if request.full_url.endswith("/api/db/stats"):
                return _Response({"ok": True})
            if request.full_url.endswith("/api/drives"):
                return _Response({"ok": True, "drives": []})
            self.assertTrue(request.full_url.endswith("/api/memory?limit=50"))
            return _Response({"ok": True, "native": True, "memory": {"memories": []}})

        adapter = JawlWebAdapter("http://127.0.0.1:8770", token="secret", opener=opener)
        result = adapter.restart_agent(wait_for_memory=True)
        self.assertTrue(result["agent_ready"])
        self.assertEqual(calls[-1], "http://127.0.0.1:8770/api/memory?limit=50")

    def test_chat_post_and_sse_are_correlated_by_sequence(self):
        stream = _SseResponse()
        posted = threading.Event()

        def opener(request, timeout):
            del timeout
            if request.full_url.endswith("/api/chat/stream"):
                return stream
            self.assertEqual(request.full_url, "http://127.0.0.1:8770/api/chat")
            posted.set()
            stream.lines.put(('data: {"messages": [{"seq": 1, "sender": "Agent", "text": "старое"}, {"seq": 3, "sender": "Agent", "text": "актуальный ответ"}], "status": {"state": "online"}}\n').encode("utf-8"))
            stream.lines.put(b"\n")
            return _Response({"ok": True, "message": {"seq": 2, "sender": "User"}})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", opener=opener, chat_timeout_seconds=2,
        )
        self.assertEqual(adapter.respond("Привет"), "актуальный ответ")
        self.assertTrue(posted.is_set())
        self.assertEqual(adapter.last_chat_status, "connected")

    def test_chat_cancellation_closes_pending_stream(self):
        stream = _SseResponse()
        posted = threading.Event()
        cancel = threading.Event()
        result = {}

        def opener(request, timeout):
            del timeout
            if request.full_url.endswith("/api/chat/stream"):
                return stream
            posted.set()
            return _Response({"ok": True, "message": {"seq": 1, "sender": "User"}})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", opener=opener, chat_timeout_seconds=2,
        )

        def call():
            try:
                adapter.respond("Отмени меня", cancel_event=cancel)
            except Exception as exc:  # noqa: BLE001 - assertion below checks exact type
                result["error"] = exc

        thread = threading.Thread(target=call)
        thread.start()
        self.assertTrue(posted.wait(1))
        cancel.set()
        thread.join(timeout=2)
        self.assertIsInstance(result.get("error"), JawlTurnCancelled)
        self.assertEqual(adapter.last_chat_status, "cancelled")

    def test_chat_cancellation_tolerates_http_reader_close_race(self):
        stream = _BrokenOnCloseSseResponse()
        cancel = threading.Event()

        def opener(request, timeout):
            del timeout
            if request.full_url.endswith("/api/chat/stream"):
                return stream
            cancel.set()
            return _Response({"ok": True, "message": {"seq": 1, "sender": "User"}})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", opener=opener, chat_timeout_seconds=2,
        )
        with self.assertRaises(JawlTurnCancelled):
            adapter.respond("РћС‚РјРµРЅРё РјРµРЅСЏ", cancel_event=cancel)
        self.assertEqual(adapter.last_chat_status, "cancelled")

    def test_chat_filters_internal_markup_before_return(self):
        stream = _SseResponse()

        def opener(request, timeout):
            del timeout
            if request.full_url.endswith("/api/chat/stream"):
                return stream
            stream.lines.put(
                (
                    'data: {"messages": [{"seq": 2, "sender": "Agent", '
                    '"text": "<think>secret</think><final>visible</final>"}], '
                    '"status": {"state": "online"}}\n'
                ).encode("utf-8")
            )
            stream.lines.put(b"\n")
            return _Response({"ok": True, "message": {"seq": 1, "sender": "User"}})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", opener=opener, chat_timeout_seconds=2,
        )
        self.assertEqual(adapter.respond("Тест"), "visible")


    def test_native_gateway_returns_only_matching_typed_final_event(self):
        stream = _SseResponse()
        calls = []

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            calls.append(path)
            if path == "/api/companion/stream":
                return stream
            self.assertEqual(path, "/api/companion/turn")
            request_payload = json.loads(request.data.decode("utf-8"))
            turn_id = request_payload["turn_id"]
            response = {
                "schema_version": 1,
                "response_id": "resp-native-1",
                "turn_id": turn_id,
                "text": "Ответ из JAWL",
                "speak": True,
                "emotion": {"id": "attentive", "intensity": 0.45, "confidence": 0.8},
                "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
                "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
                "actions": [],
                "interruptible": True,
                "proactive": False,
            }
            stream.lines.put(
                (
                    "data: "
                    + json.dumps({
                        "events": [{
                            "schema_version": 1,
                            "event_seq": 2,
                            "turn_id": turn_id,
                            "type": "assistant.final",
                            "payload": {"response": response},
                        }]
                    })
                    + "\n"
                ).encode("utf-8")
            )
            stream.lines.put(b"\n")
            return _Response({"ok": True, "turn_id": turn_id})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770",
            native_gateway=True,
            chat_timeout_seconds=2,
            opener=opener,
        )
        self.assertEqual(adapter.respond("Привет"), "Ответ из JAWL")
        self.assertEqual(calls[:2], ["/api/companion/stream", "/api/companion/turn"])

    def test_native_gateway_gap_cursor_advances_to_latest(self):
        gap_line = (
            "data: "
            + json.dumps({
                "events": [],
                "cursor": {
                    "schema_version": 1,
                    "after": 0,
                    "oldest_event_seq": 100,
                    "latest_event_seq": 105,
                    "gap": True,
                },
            })
            + "\n"
        ).encode("utf-8")
        first = _EofSseResponse([gap_line, b"\n"])
        second = _SseResponse()
        calls = []

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            calls.append(path)
            if path.startswith("/api/companion/stream"):
                return first if len(calls) == 1 else second
            self.assertEqual(path, "/api/companion/turn")
            turn_id = json.loads(request.data.decode("utf-8"))["turn_id"]
            response = {
                "schema_version": 1,
                "response_id": "resp-native-gap",
                "turn_id": turn_id,
                "text": "Ответ после gap",
                "speak": True,
                "emotion": {"id": "attentive", "intensity": 0.45, "confidence": 0.8},
                "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
                "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
                "actions": [],
                "interruptible": True,
                "proactive": False,
            }
            second.lines.put(
                (
                    "data: "
                    + json.dumps({
                        "events": [{
                            "schema_version": 1,
                            "event_seq": 106,
                            "turn_id": turn_id,
                            "type": "assistant.final",
                            "payload": {"response": response},
                        }],
                        "cursor": {"schema_version": 1, "after": 106, "gap": False},
                    })
                    + "\n"
                ).encode("utf-8")
            )
            second.lines.put(b"\n")
            return _Response({"ok": True, "turn_id": turn_id})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770",
            native_gateway=True,
            chat_timeout_seconds=3,
            opener=opener,
        )
        self.assertEqual(adapter.respond("Привет"), "Ответ после gap")
        self.assertEqual(calls[0], "/api/companion/stream")
        self.assertEqual(calls[1], "/api/companion/turn")
        self.assertIn("after=105", calls[2])

    def test_native_gateway_forwards_safe_assistant_deltas(self):
        stream = _SseResponse()

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            if path == "/api/companion/stream":
                return stream
            payload = json.loads(request.data.decode("utf-8"))
            turn_id = payload["turn_id"]
            response = {
                "schema_version": 1,
                "response_id": "resp-native-stream-1",
                "turn_id": turn_id,
                "text": "Первая часть. Вторая часть.",
                "speak": True,
                "emotion": {"id": "attentive", "intensity": 0.45, "confidence": 0.8},
                "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
                "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
                "actions": [],
                "interruptible": True,
                "proactive": False,
            }
            stream.lines.put(("data: " + json.dumps({"events": [
                {"schema_version": 1, "event_seq": 2, "turn_id": turn_id,
                 "type": "assistant.delta", "payload": {"text": "Первая часть. "}},
                {"schema_version": 1, "event_seq": 3, "turn_id": turn_id,
                 "type": "assistant.delta", "payload": {"text": "Вторая часть."}},
                {"schema_version": 1, "event_seq": 4, "turn_id": turn_id,
                 "type": "assistant.final", "payload": {"response": response}},
            ]}) + "\n").encode("utf-8"))
            stream.lines.put(b"\n")
            return _Response({"ok": True, "turn_id": turn_id})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", native_gateway=True,
            chat_timeout_seconds=2, opener=opener,
        )
        events = list(adapter.stream_envelope("Привет"))
        self.assertEqual([event["type"] for event in events], ["delta", "delta", "final"])
        self.assertEqual("".join(event["text"] for event in events[:-1]), "Первая часть. Вторая часть.")
        self.assertEqual(events[-1]["response"]["text"], "Первая часть. Вторая часть.")

    def test_native_gateway_accepts_initial_evicted_history_gap(self):
        stream = _SseResponse()

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            if path == "/api/companion/stream":
                return stream
            payload = json.loads(request.data.decode("utf-8"))
            response = {
                "schema_version": 1, "response_id": "resp-gap",
                "turn_id": payload["turn_id"], "text": "Ответ после gap",
                "speak": True,
                "emotion": {"id": "attentive", "intensity": 0.4, "confidence": 0.9},
                "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
                "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
                "actions": [], "interruptible": True, "proactive": False,
            }
            stream.lines.put(("data: " + json.dumps({
                "events": [], "cursor": {"after": 20, "latest": 20, "gap": True},
            }) + "\n").encode("utf-8"))
            stream.lines.put(b"\n")
            stream.lines.put(("data: " + json.dumps({
                "events": [{"schema_version": 1, "event_seq": 21,
                            "turn_id": payload["turn_id"], "type": "assistant.final",
                            "payload": {"response": response}}],
                "cursor": {"after": 21, "gap": False},
            }) + "\n").encode("utf-8"))
            stream.lines.put(b"\n")
            return _Response({"ok": True, "turn_id": payload["turn_id"]})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", native_gateway=True,
            chat_timeout_seconds=2, opener=opener,
        )
        self.assertEqual(adapter.respond("gap-safe"), "Ответ после gap")

    def test_native_gateway_cancels_turn_after_terminal_timeout(self):
        stream = _SseResponse()
        calls = []

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            calls.append(path)
            if path == "/api/companion/stream":
                return stream
            payload = json.loads(request.data.decode("utf-8"))
            return _Response({"ok": True, "turn_id": payload["turn_id"]})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770", native_gateway=True,
            chat_timeout_seconds=0.2, opener=opener,
        )
        with self.assertRaises(JawlWebUnavailable):
            adapter.respond("timeout-safe")
        self.assertEqual(calls.count("/api/companion/turn"), 1)
        self.assertEqual(calls.count("/api/companion/cancel"), 1)

    def test_native_gateway_reconnects_from_last_cursor_without_resubmitting_turn(self):
        first = _SseResponse()
        second = _SseResponse()
        streams = [first, second]
        calls = []
        turn_id_holder = {}

        first.lines.put((
            "data: " + json.dumps({"events": [{
                "schema_version": 1,
                "event_seq": 5,
                "turn_id": "other-turn",
                "type": "turn.started",
                "payload": {},
            }], "cursor": {"after": 5}}) + "\n"
        ).encode("utf-8"))
        first.lines.put(b"\n")

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            calls.append(path)
            if path.startswith("/api/companion/stream"):
                stream = streams.pop(0)
                if stream is second:
                    response = {
                        "schema_version": 1,
                        "response_id": "resp-reconnect",
                        "turn_id": turn_id_holder["turn_id"],
                        "text": "reconnected",
                        "speak": True,
                        "emotion": {"id": "attentive", "intensity": 0.4, "confidence": 0.9},
                        "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
                        "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
                        "actions": [],
                        "interruptible": True,
                        "proactive": False,
                    }
                    stream.lines.put((
                        "data: " + json.dumps({"events": [{
                            "schema_version": 1,
                            "event_seq": 6,
                            "turn_id": turn_id_holder["turn_id"],
                            "type": "assistant.final",
                            "payload": {"response": response},
                        }], "cursor": {"after": 6}}) + "\n"
                    ).encode("utf-8"))
                    stream.lines.put(b"\n")
                return stream
            self.assertEqual(path, "/api/companion/turn")
            turn_id_holder["turn_id"] = json.loads(request.data.decode("utf-8"))["turn_id"]
            first.close()
            return _Response({"ok": True, "turn_id": turn_id_holder["turn_id"]})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770",
            native_gateway=True,
            chat_timeout_seconds=2,
            opener=opener,
        )
        self.assertEqual(adapter.respond("resume"), "reconnected")
        self.assertEqual(len([path for path in calls if path == "/api/companion/turn"]), 1)
        self.assertIn("after=5", calls[2])

    def test_native_gateway_forwards_local_cancellation(self):
        stream = _SseResponse()
        cancel = threading.Event()
        calls = []

        def opener(request, timeout):
            del timeout
            path = request.full_url.removeprefix("http://127.0.0.1:8770")
            calls.append(path)
            if path == "/api/companion/stream":
                return stream
            if path == "/api/companion/turn":
                cancel.set()
                payload = json.loads(request.data.decode("utf-8"))
                return _Response({"ok": True, "turn_id": payload["turn_id"]})
            self.assertEqual(path, "/api/companion/cancel")
            payload = json.loads(request.data.decode("utf-8"))
            return _Response({"ok": True, "turn_id": payload["turn_id"]})

        adapter = JawlWebChatAdapter(
            "http://127.0.0.1:8770",
            native_gateway=True,
            chat_timeout_seconds=2,
            opener=opener,
        )
        with self.assertRaises(JawlTurnCancelled):
            adapter.respond("Отмени", cancel_event=cancel)
        self.assertIn("/api/companion/cancel", calls)


if __name__ == "__main__":
    unittest.main()
