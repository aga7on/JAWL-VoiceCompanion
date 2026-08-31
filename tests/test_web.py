import json
import sys
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402


class WebTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0, frontend_dir=Path(__file__).parents[1] / "frontend", gateway=TextGateway())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.session_headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path):
        with urlopen(self.base + path, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post_json(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.session_headers},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_browser_are_available(self):
        status, health = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["mode"], "phase1_mock_brain")
        with urlopen(self.base + "/", timeout=2) as response:
            self.assertIn(b"JAWL VoiceCompanion", response.read())

    def test_session_endpoint_exposes_local_bootstrap_tokens(self):
        status, session = self.get_json("/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["session_token"])
        self.assertTrue(session["csrf_token"])

    def test_chat_and_level_change_work(self):
        status, response = self.post_json("/api/chat", {"text": "Привет"})
        self.assertEqual(status, 200)
        self.assertEqual(response["schema_version"], 1)
        status, changed = self.post_json("/api/hostos/level", {"level": 2})
        self.assertEqual(status, 200)
        self.assertEqual(changed["policy"]["active_name"], "OPERATOR")

    def test_invalid_level_is_rejected(self):
        request = Request(
            self.base + "/api/hostos/level",
            data=b'{"level": 99}',
            headers={"Content-Type": "application/json", **self.session_headers},
            method="POST",
        )
        with self.assertRaises(Exception) as context:
            urlopen(request, timeout=2)
        self.assertIn("400", str(context.exception))

    def test_state_change_without_session_is_rejected(self):
        request = Request(
            self.base + "/api/hostos/level",
            data=b'{"level": 2}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
