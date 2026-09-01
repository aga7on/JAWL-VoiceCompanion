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
            frontend = response.read()
            self.assertIn(b"JAWL VoiceCompanion", frontend)
            self.assertIn(b"ambient-audio-toggle", frontend)
            self.assertIn(b"ambient-memory-enabled", frontend)
        with urlopen(self.base + "/avatar?source=obs", timeout=2) as response:
            self.assertIn(b"JAWL Avatar", response.read())

    def test_doctor_reports_mock_text_mode_without_secrets(self):
        status, doctor = self.get_json("/api/doctor")
        self.assertEqual(status, 200)
        self.assertEqual(doctor["schema_version"], 1)
        self.assertEqual(doctor["status"], "degraded")
        self.assertTrue(doctor["text_mode_available"])
        checks = {item["id"]: item for item in doctor["checks"]}
        self.assertEqual(checks["jawl"]["status"], "mock")
        self.assertEqual(checks["hostos"]["status"], "dry_run")
        self.assertNotIn("G:\\", json.dumps(doctor))

    def test_session_endpoint_exposes_local_bootstrap_tokens(self):
        status, session = self.get_json("/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["session_token"])
        self.assertTrue(session["csrf_token"])

    def test_vision_status_and_dry_run_look_are_available(self):
        status, vision = self.get_json("/api/vision/status")
        self.assertEqual(status, 200)
        self.assertFalse(vision["configured"])
        self.assertIn("attention", vision)
        self.post_json("/api/hostos/level", {"level": 1})
        status, result = self.post_json("/api/vision/look", {"prompt": "Что видно?"})
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"]["status"], "degraded")
        self.assertNotIn("image", result["result"])

    def test_attention_dnd_requires_browser_session(self):
        status, attention = self.get_json("/api/attention")
        self.assertEqual(status, 200)
        self.assertFalse(attention["dnd"])
        _, changed = self.post_json("/api/attention", {"dnd": True})
        self.assertTrue(changed["attention"]["dnd"])
        request = Request(
            self.base + "/api/attention",
            data=b'{"dnd": false}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

    def test_ambient_memory_requires_browser_session(self):
        request = Request(self.base + "/api/ambient-memory")
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

    def test_ambient_audio_requires_browser_session_and_reports_unconfigured(self):
        request = Request(self.base + "/api/ambient-audio")
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        request = Request(self.base + "/api/ambient-audio", headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertFalse(status["configured"])
        self.assertEqual(status["status"], "not_configured")

    def test_ambient_memory_is_off_until_explicitly_enabled(self):
        request = Request(self.base + "/api/ambient-memory", headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            initial = json.loads(response.read().decode("utf-8"))
        self.assertFalse(initial["state"]["enabled"])
        _, enabled = self.post_json("/api/ambient-memory/config", {"enabled": True})
        self.assertTrue(enabled["state"]["enabled"])
        _, disabled = self.post_json("/api/ambient-memory/config", {"enabled": False})
        self.assertFalse(disabled["state"]["enabled"])

    def test_voice_status_is_explicit_when_sidecar_is_not_configured(self):
        status, voice = self.get_json("/api/voice/status")
        self.assertEqual(status, 200)
        self.assertFalse(voice["configured"])
        self.assertEqual(voice["status"], "not_configured")

    def test_chat_and_level_change_work(self):
        status, response = self.post_json("/api/chat", {"text": "Привет"})
        self.assertEqual(status, 200)
        self.assertEqual(response["schema_version"], 1)
        status, changed = self.post_json("/api/hostos/level", {"level": 2})
        self.assertEqual(status, 200)
        self.assertEqual(changed["policy"]["active_name"], "OPERATOR")

    def test_hostos_registry_is_visible_and_requests_use_server_policy(self):
        status, tools = self.get_json("/api/hostos/tools")
        self.assertEqual(status, 200)
        self.assertTrue(any(item["name"] == "desktop.act" for item in tools["tools"]))
        self.assertTrue(any(item["name"] == "screen.observe" for item in tools["tools"]))
        status, result = self.post_json(
            "/api/hostos/execute",
            {"request": {"tool": "desktop.act", "risk": "observe", "requested_access_level": 3}},
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"]["status"], "denied")

    def test_browser_approval_queue_is_server_side_and_one_shot(self):
        self.post_json("/api/hostos/level", {"level": 3})
        request_payload = {
            "request": {"tool": "shell.exec", "risk": "observe", "arguments": {"argv": ["echo", "hello"]}}
        }
        status, pending = self.post_json("/api/hostos/approvals/request", request_payload)
        self.assertEqual(status, 200)
        approval_id = pending["result"]["approval_id"]
        status, approved = self.post_json(f"/api/hostos/approvals/{approval_id}/approve", {})
        self.assertEqual(status, 200)
        self.assertEqual(approved["result"]["status"], "approved")
        status, executed = self.post_json(
            "/api/hostos/execute",
            {**request_payload, "approval_id": approval_id},
        )
        self.assertEqual(status, 200)
        self.assertEqual(executed["result"]["status"], "degraded")
        status, replay = self.post_json(
            "/api/hostos/execute",
            {**request_payload, "approval_id": approval_id},
        )
        self.assertEqual(status, 200)
        self.assertEqual(replay["result"]["status"], "approval_required")

    def test_invalid_level_is_rejected(self):
        request = Request(
            self.base + "/api/hostos/level",
            data=b'{"level": 99}',
            headers={"Content-Type": "application/json", **self.session_headers},
            method="POST",
        )
        try:
            urlopen(request, timeout=2)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, 400)
        else:
            self.fail("invalid level should return HTTP 400")

    def test_state_change_without_session_is_rejected(self):
        request = Request(
            self.base + "/api/hostos/level",
            data=b'{"level": 2}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(request, timeout=2)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, 403)
        else:
            self.fail("missing session should return HTTP 403")

    def test_approval_list_without_session_is_rejected(self):
        try:
            urlopen(self.base + "/api/hostos/approvals", timeout=2)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, 403)
        else:
            self.fail("approval list should return HTTP 403 without a session")

    def test_jawl_inspection_without_session_is_rejected(self):
        try:
            urlopen(self.base + "/api/jawl/persona", timeout=2)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, 403)
        else:
            self.fail("JAWL persona inspection should return HTTP 403 without a session")

    def test_audit_without_session_is_rejected(self):
        try:
            urlopen(self.base + "/api/audit", timeout=2)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, 403)
        else:
            self.fail("audit should return HTTP 403 without a session")


if __name__ == "__main__":
    unittest.main()
