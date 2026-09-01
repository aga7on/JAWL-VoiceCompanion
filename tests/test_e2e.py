import json
import base64
import io
import socketserver
import sys
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.avatar import AvatarAssetStore  # noqa: E402
from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.jawl_adapter import JawlTerminalAdapter  # noqa: E402
from jawl_voicecompanion.models import AccessLevel  # noqa: E402
from jawl_voicecompanion.tts import CozyVoiceHttpClient, TTSService  # noqa: E402
from jawl_voicecompanion.vision import OpenAICompatibleVisionClient  # noqa: E402
from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402


class _VisionHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        _VisionHandler.requests.append(json.loads(self.rfile.read(length).decode("utf-8")))
        body = json.dumps({"choices": [{"message": {"content": "На экране окно редактора."}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class _TTSHandler(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(404)
            return
        body = b'{"status":"ok","model":"e2e"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - stdlib handler API
        if self.path != "/tts":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        _TTSHandler.requests.append(payload)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\0\0" * max(1, len(payload.get("text", ""))))
        body = output.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class _FakeScreen:
    enabled = True

    def observe(self, *, include_image):
        return {
            "status": "verified",
            "captured_at": "2026-09-01T12:00:00+00:00",
            "source": "focused_window",
            "image": {
                "media_type": "image/jpeg",
                "data_base64": "YWJj",
                "width": 3,
                "height": 3,
                "bytes": 3,
            },
            "persisted": False,
        }


class _JawlHandler(socketserver.StreamRequestHandler):
    messages = []

    def handle(self):
        if self.rfile.readline() != b"JAWL_HANDSHAKE\n":
            return
        message = json.loads(self.rfile.readline().decode("utf-8"))
        _JawlHandler.messages.append(message)
        answer = {"text": f"JAWL E2E: {message['text']}"}
        self.wfile.write((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))


class LocalE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = ThreadingHTTPServer(("127.0.0.1", 0), _VisionHandler)
        _VisionHandler.requests = []
        threading.Thread(target=self.provider.serve_forever, daemon=True).start()
        self.tts_provider = ThreadingHTTPServer(("127.0.0.1", 0), _TTSHandler)
        _TTSHandler.requests = []
        threading.Thread(target=self.tts_provider.serve_forever, daemon=True).start()
        self.jawl = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _JawlHandler)
        _JawlHandler.messages = []
        self.jawl_port_file = Path(self.temp.name) / "terminal.port"
        self.jawl_port_file.write_text(str(self.jawl.server_address[1]), encoding="utf-8")
        self.jawl_adapter = JawlTerminalAdapter(self.jawl_port_file, timeout=2)
        threading.Thread(target=self.jawl.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{self.provider.server_port}/v1"
        self.client = OpenAICompatibleVisionClient(endpoint, "e2e-vlm")
        self.policy = HostOSPolicy()
        self.executor = HostOSExecutor(
            self.policy,
            Path(self.temp.name) / "sandbox",
            workspace_roots=(Path(self.temp.name),),
            host_roots=(Path(self.temp.name),),
            dry_run=False,
            screen_capture=_FakeScreen(),
        )
        self.gateway = TextGateway(
            policy=self.policy,
            responder=self.jawl_adapter,
            brain_name="e2e_brain",
        )
        self.voice_mem = VoiceMemProcessClient(
            sys.executable,
            args=("--test-stub",),
            timeout_seconds=2,
        )
        self.tts = TTSService(CozyVoiceHttpClient(
            f"http://127.0.0.1:{self.tts_provider.server_port}", timeout_seconds=2,
        ))
        self.avatar_root = Path(self.temp.name) / "live2d"
        self.avatar_root.mkdir()
        (self.avatar_root / "model3.json").write_text("{}", encoding="utf-8")
        (self.avatar_root / "live2d-runtime.js").write_text(
            "window.Live2DCompanionRuntime = {create: async () => ({})};", encoding="utf-8"
        )
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=self.gateway,
            hostos_executor=self.executor,
            vision_describer=self.client,
            screen_watch=True,
            screen_watch_interval=2,
            voice_mem=self.voice_mem,
            tts_service=self.tts,
            avatar_assets=AvatarAssetStore(self.avatar_root),
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.provider.shutdown()
        self.provider.server_close()
        self.tts_provider.shutdown()
        self.tts_provider.server_close()
        self.jawl.shutdown()
        self.jawl.server_close()
        self.temp.cleanup()

    def get_json(self, path):
        request = Request(self.base + path, headers=self.headers)
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post_json(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post_binary(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, response.read()

    def test_chat_avatar_approval_execution_and_emergency_stop(self):
        status, session = self.get_json("/api/session")
        self.assertEqual(status, 200)
        self.assertEqual(session["session_token"], self.server.session_token)
        with urlopen(self.base + "/avatar", timeout=3) as response:
            self.assertIn(b"JAWL Avatar", response.read())
        _, avatar_config = self.get_json("/api/avatar/config")
        self.assertTrue(avatar_config["enabled"])
        with urlopen(self.base + "/avatar-assets/model3.json", timeout=3) as response:
            self.assertEqual(response.read(), b"{}")

        status, chat = self.post_json("/api/chat", {"text": "проверка e2e"})
        self.assertEqual(status, 200)
        self.assertEqual(chat["text"], "JAWL E2E: проверка e2e")
        self.assertEqual(_JawlHandler.messages, [{"text": "проверка e2e"}])
        self.assertEqual(self.jawl_adapter.last_status, "connected")
        status, state = self.get_json("/api/state")
        self.assertEqual(state["last_turn"]["response"]["text"], chat["text"])

        _, tts_status = self.get_json("/api/tts/status")
        self.assertTrue(tts_status["configured"])
        self.assertEqual(tts_status["status"], "ok")
        _, audio = self.post_binary("/api/tts/synthesize", {"text": "Привет. Как дела?"})
        self.assertTrue(audio.startswith(b"RIFF"))
        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual(wav.getframerate(), 22050)
            self.assertGreater(wav.getnframes(), 0)
        self.assertEqual([item["text"] for item in _TTSHandler.requests], ["Привет.", "Как дела?"])

        self.post_json("/api/hostos/level", {"level": int(AccessLevel.ROOT)})
        request = {
            "request": {
                "tool": "shell.exec",
                "risk": "observe",
                "arguments": {"argv": [sys.executable, "-c", "print('e2e-ok')"]},
            }
        }
        _, pending = self.post_json("/api/hostos/approvals/request", request)
        approval_id = pending["result"]["approval_id"]
        _, approved = self.post_json(f"/api/hostos/approvals/{approval_id}/approve", {})
        self.assertEqual(approved["result"]["status"], "approved")
        _, executed = self.post_json("/api/hostos/execute", {**request, "approval_id": approval_id})
        self.assertEqual(executed["result"]["status"], "verified")
        self.assertIn("e2e-ok", executed["result"]["result"]["stdout"])
        _, replay = self.post_json("/api/hostos/execute", {**request, "approval_id": approval_id})
        self.assertEqual(replay["result"]["status"], "approval_required")

        self.post_json("/api/emergency-stop", {})
        _, stopped = self.post_json("/api/hostos/execute", request)
        self.assertEqual(stopped["result"]["status"], "denied")
        self.assertEqual(stopped["result"]["reason"], "emergency_stop_active")

    def test_voicemem_sidecar_final_reaches_http_chat_state(self):
        _, status = self.get_json("/api/voice/status")
        self.assertTrue(status["configured"])
        self.assertEqual(status["status"], "ready")
        _, partial = self.post_json("/api/voice/partial", {
            "session_id": "voice-s1", "text": "покажи", "ended": False,
        })
        self.assertTrue(partial["events"], partial)
        self.assertEqual(partial["events"][0]["type"], "USER_PARTIAL")
        self.assertEqual(partial["responses"], [])
        _, final = self.post_json("/api/voice/partial", {
            "session_id": "voice-s1", "text": "покажи редактор", "ended": True,
        })
        self.assertEqual([event["type"] for event in final["events"]], ["USER_PARTIAL", "VOICE_TURN"])
        self.assertEqual(final["responses"][0]["text"], "JAWL E2E: покажи редактор")
        _, state = self.get_json("/api/state")
        self.assertEqual(state["last_turn"]["user"], "покажи редактор")

        _, audio = self.post_json("/api/voice/audio", {
            "session_id": "voice-audio-s1",
            "sample_rate": 16000,
            "channels": 1,
            "pcm16_base64": base64.b64encode(b"final!").decode("ascii"),
        })
        self.assertEqual([event["type"] for event in audio["events"]], ["USER_PARTIAL", "VOICE_TURN"])
        self.assertEqual(audio["responses"][0]["text"], "JAWL E2E: аудио e2e")
        _, state = self.get_json("/api/state")
        self.assertEqual(state["last_turn"]["user"], "аудио e2e")

        _, pending_audio = self.post_json("/api/voice/audio", {
            "session_id": "voice-audio-flush",
            "sample_rate": 16000,
            "channels": 1,
            "pcm16_base64": base64.b64encode(b"12").decode("ascii"),
        })
        self.assertEqual(pending_audio["responses"], [])
        _, flushed = self.post_json("/api/voice/end", {"session_id": "voice-audio-flush"})
        self.assertEqual([event["type"] for event in flushed["events"]], ["VOICE_TURN"])
        self.assertEqual(flushed["responses"][0]["text"], "JAWL E2E: аудио")

    def test_screen_capture_vlm_dedup_and_bounded_screen_delta(self):
        self.post_json("/api/hostos/level", {"level": int(AccessLevel.OBSERVER)})
        _, vision_status = self.get_json("/api/vision/status")
        self.assertTrue(vision_status["configured"])
        self.assertTrue(vision_status["screen_enabled"])

        watcher = self.server.screen_watcher
        self.assertIsNotNone(watcher)
        deadline = time.monotonic() + 3
        while not watcher.events() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(watcher.events())
        self.assertEqual(watcher.events()[0]["type"], "SCREEN_DELTA")
        self.assertNotIn("image", watcher.events()[0])
        _, event_log = self.get_json("/api/vision/events")
        self.assertEqual(event_log["events"][0]["type"], "SCREEN_DELTA")
        self.assertEqual(len(_VisionHandler.requests), 1)

        _, first = self.post_json("/api/vision/look", {"prompt": "Что видно?", "force": True})
        self.assertTrue(first["ok"])
        self.assertEqual(first["result"]["status"], "ok")
        self.assertEqual(first["result"]["description"], "На экране окно редактора.")
        self.assertNotIn("image", first["result"])
        self.assertEqual(len(_VisionHandler.requests), 2)

        _, second = self.post_json("/api/vision/look", {"prompt": "Что видно?"})
        self.assertEqual(second["result"]["status"], "unchanged")
        self.assertFalse(second["result"]["vlm_called"])
        self.assertEqual(len(_VisionHandler.requests), 2)

        self.assertNotIn("YWJj", json.dumps(self.gateway.audit()))


if __name__ == "__main__":
    unittest.main()
