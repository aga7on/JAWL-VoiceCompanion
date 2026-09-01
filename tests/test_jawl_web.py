import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_web import JawlWebAdapter  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


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


if __name__ == "__main__":
    unittest.main()
