import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.llm import OpenAICompatibleChatClient  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode("utf-8")


class _StreamResponse:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self.lines)


class LLMTests(unittest.TestCase):
    def test_client_normalizes_endpoint_and_removes_hidden_reasoning(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return _Response({
                "choices": [{"message": {"content": "<think>secret</think><final>Готово.</final>"}}],
            })

        client = OpenAICompatibleChatClient(
            "http://127.0.0.1:8000/v1",
            "z-ai/glm-5.3-free",
            api_key="test-key",
            opener=opener,
        )
        self.assertEqual(client.respond("Проверь контур"), "Готово.")
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-key")
        body = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(body["model"], "z-ai/glm-5.3-free")
        self.assertEqual(body["messages"][-1]["content"], "Проверь контур")

    def test_optional_user_agent_is_sent_and_rejects_header_injection(self):
        requests = []

        def opener(request, timeout):
            del timeout
            requests.append(request)
            return _Response({"choices": [{"message": {"content": "ok"}}]})

        client = OpenAICompatibleChatClient(
            "http://127.0.0.1:8000/v1", "big-pickle", user_agent="OpenCode/1.18.11", opener=opener,
        )
        self.assertEqual(client.respond("ping"), "ok")
        self.assertEqual(requests[0].get_header("User-agent"), "OpenCode/1.18.11")
        with self.assertRaises(ValueError):
            OpenAICompatibleChatClient("http://127.0.0.1:8000/v1", "model", user_agent="bad\nvalue")

    def test_client_health_uses_models_endpoint(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url, "http://127.0.0.1:8000/v1/models")
            return _Response({"data": []})

        result = OpenAICompatibleChatClient("http://127.0.0.1:8000/v1", "glm", opener=opener).health()
        self.assertEqual(result["status"], "online")

    def test_cancelled_request_is_not_sent(self):
        called = []

        def opener(request, timeout):
            called.append(True)
            return _Response({})

        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(Exception, "cancelled"):
            OpenAICompatibleChatClient("http://127.0.0.1:8000/v1", "glm", opener=opener).respond(
                "тест", cancel_event=cancel,
            )
        self.assertEqual(called, [])

    def test_stream_yields_safe_deltas_and_keeps_reasoning_hidden(self):
        requests = []

        def opener(request, timeout):
            del timeout
            requests.append(json.loads(request.data.decode("utf-8")))
            return _StreamResponse([
                'data: {"choices":[{"delta":{"content":"<think>secret"}}]}\n',
                'data: {"choices":[{"delta":{"content":" reasoning</think>"}}]}\n',
                'data: {"choices":[{"delta":{"content":"<final>Привет"}}]}\n',
                'data: {"choices":[{"delta":{"content":" мир.</final>"}}]}\n',
                "data: [DONE]\n",
            ])

        client = OpenAICompatibleChatClient("http://127.0.0.1:8000/v1", "glm", opener=opener)
        chunks = list(client.stream("тест"))
        self.assertEqual("".join(chunks), "Привет мир.")
        self.assertTrue(all("secret" not in chunk for chunk in chunks))
        self.assertTrue(requests[0]["stream"])


if __name__ == "__main__":
    unittest.main()
