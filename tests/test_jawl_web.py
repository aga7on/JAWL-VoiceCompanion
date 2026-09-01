import json
import sys
import threading
import unittest
from queue import Empty, Queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled  # noqa: E402
from jawl_voicecompanion.jawl_web import JawlWebAdapter, JawlWebChatAdapter  # noqa: E402


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

    def test_remote_url_is_rejected_before_token_can_leave_machine(self):
        with self.assertRaises(ValueError):
            JawlWebAdapter("https://example.invalid", token="secret")

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


if __name__ == "__main__":
    unittest.main()
