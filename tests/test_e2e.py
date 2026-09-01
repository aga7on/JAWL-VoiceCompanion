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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.avatar import AvatarAssetStore  # noqa: E402
from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge, AmbientAudioService  # noqa: E402
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
from jawl_voicecompanion.hostos_policy import HostOSPolicy  # noqa: E402
from jawl_voicecompanion.hostos_tools import HostOSExecutor  # noqa: E402
from jawl_voicecompanion.jawl_adapter import JawlTerminalAdapter  # noqa: E402
from jawl_voicecompanion.jawl_web import JawlWebAdapter, JawlWebChatAdapter  # noqa: E402
from jawl_voicecompanion.models import AccessLevel  # noqa: E402
from jawl_voicecompanion.system_audio import SystemAudioLoopback  # noqa: E402
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


class _JawlWebHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler API
        payloads = {
            "/api/agent/status": {"running": True, "pid": 1234},
            "/api/tick": {"phase": "wake", "step": 7, "model": "e2e-model"},
            "/api/db/stats": {
                "ok": True,
                "sql": {"exists": True, "counts": {"notes": 4, "personality_traits": 2}, "ticks": 7},
                "vector": {"knowledge": 3},
                "graph": {"nodes": 5},
            },
            "/api/drives": {
                "ok": True,
                "dynamicReduction": True,
                "drives": [{
                    "name": "curiosity", "type": "fundamental",
                    "description": "bounded drive", "secret": "must-not-cross",
                }],
            },
            "/api/config": {
                "ok": True,
                "values": {
                    "settings:identity.agent_name": "Луна",
                    "settings:llm.language": "ru",
                    "settings:system.heartbeat_interval": 30,
                    "env:LLM_API_KEY_1": "must-not-leak",
                },
            },
        }
        body = json.dumps(payloads.get(self.path, {"error": "not found"}), ensure_ascii=False).encode("utf-8")
        self.send_response(200 if self.path in payloads else 404)
        self.send_header("Content-Type", "application/json")
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


class _AmbientVoiceMem:
    def __init__(self):
        self.calls = 0

    def feed_audio(self, _pcm16, *, sample_rate, session_id):
        self.calls += 1
        if self.calls != 1 or sample_rate != 16000:
            return []
        return [{
            "type": "USER_PARTIAL",
            "payload": {"text": "частичный системный звук"},
        }, {
            "type": "VOICE_TURN",
            "event_id": "ambient-loopback-e2e",
            "session_id": session_id,
            "payload": {"text": "В игре объявлен важный квест", "confidence": 0.9},
        }]

    def end_audio(self, *, session_id):
        return []


class _AmbientStream:
    def __init__(self, callback):
        self.callback = callback

    def start_stream(self):
        return None

    def stop_stream(self):
        return None

    def close(self):
        return None


class _AmbientPyAudio:
    def __init__(self):
        self.stream = None

    def get_host_api_info_by_type(self, _api):
        return {"defaultOutputDevice": 1}

    def get_device_info_by_index(self, index):
        if index == 1:
            return {"name": "Speakers", "isLoopbackDevice": False}
        return {
            "index": index,
            "name": "Speakers [Loopback]",
            "isLoopbackDevice": True,
            "maxInputChannels": 2,
            "defaultSampleRate": 48000,
        }

    def get_loopback_device_info_generator(self):
        yield self.get_device_info_by_index(7)

    def open(self, **kwargs):
        self.stream = _AmbientStream(kwargs["stream_callback"])
        return self.stream

    def terminate(self):
        return None


class _AmbientBackend:
    paWASAPI = 1
    paInt16 = 2
    paContinue = 0

    def __init__(self):
        self.last = None

    def PyAudio(self):
        self.last = _AmbientPyAudio()
        return self.last


class _JawlHandler(socketserver.StreamRequestHandler):
    messages = []

    def handle(self):
        if self.rfile.readline() != b"JAWL_HANDSHAKE\n":
            return
        message = json.loads(self.rfile.readline().decode("utf-8"))
        _JawlHandler.messages.append(message)
        if message["text"] == "no broadcast":
            time.sleep(0.25)
            return
        answer = {"text": f"JAWL E2E: {message['text']}"}
        self.wfile.write((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))


class _JawlChatWebHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    condition = threading.Condition()
    write_lock = threading.Lock()
    active_streams = set()
    messages = []
    sequence = 0
    available = True

    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path != "/api/chat/stream":
            self.send_error(404)
            return
        if not _JawlChatWebHandler.available:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            with _JawlChatWebHandler.condition:
                _JawlChatWebHandler.active_streams.add(self)
            self._write_event([])
            while True:
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                with _JawlChatWebHandler.condition:
                    _JawlChatWebHandler.condition.wait(0.05)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError, ValueError):
            self.close_connection = True
            return
        finally:
            with _JawlChatWebHandler.condition:
                _JawlChatWebHandler.active_streams.discard(self)

    def do_POST(self):  # noqa: N802 - stdlib handler API
        if self.path != "/api/chat":
            self.send_error(404)
            return
        if not _JawlChatWebHandler.available:
            self.send_error(503)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        text = payload.get("text", "")
        with _JawlChatWebHandler.condition:
            _JawlChatWebHandler.sequence += 1
            user = {"seq": _JawlChatWebHandler.sequence, "sender": "User", "text": text}
            _JawlChatWebHandler.messages.append(user)
            _JawlChatWebHandler.condition.notify_all()
        if text != "no broadcast":
            with _JawlChatWebHandler.condition:
                _JawlChatWebHandler.sequence += 1
                agent = {
                    "seq": _JawlChatWebHandler.sequence,
                    "sender": "Agent",
                    "text": (
                        "<think>hidden reasoning</think><final>JAWL WEB E2E: sanitized</final>"
                        if text == "hidden markup"
                        else f"JAWL WEB E2E: {text}"
                    ),
                }
                _JawlChatWebHandler.messages.append(agent)
                streams = list(_JawlChatWebHandler.active_streams)
                _JawlChatWebHandler.condition.notify_all()
            for stream in streams:
                try:
                    stream._write_event([agent])
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError, ValueError):
                    pass
        body = json.dumps({"ok": True, "message": user}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_event(self, messages):
        body = json.dumps({"messages": messages, "status": {"state": "online"}}, ensure_ascii=False)
        with _JawlChatWebHandler.write_lock:
            self.wfile.write((f"data: {body}\n\n").encode("utf-8"))
            self.wfile.flush()

    def log_message(self, format, *args):
        return


class LocalE2ETests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = ThreadingHTTPServer(("127.0.0.1", 0), _VisionHandler)
        _VisionHandler.requests = []
        threading.Thread(target=self.provider.serve_forever, daemon=True).start()
        self.tts_provider = ThreadingHTTPServer(("127.0.0.1", 0), _TTSHandler)
        _TTSHandler.requests = []
        threading.Thread(target=self.tts_provider.serve_forever, daemon=True).start()
        self.jawl_web_provider = ThreadingHTTPServer(("127.0.0.1", 0), _JawlWebHandler)
        threading.Thread(target=self.jawl_web_provider.serve_forever, daemon=True).start()
        self.jawl_chat_provider = ThreadingHTTPServer(("127.0.0.1", 0), _JawlChatWebHandler)
        _JawlChatWebHandler.messages = []
        _JawlChatWebHandler.sequence = 0
        _JawlChatWebHandler.active_streams = set()
        _JawlChatWebHandler.available = True
        threading.Thread(target=self.jawl_chat_provider.serve_forever, daemon=True).start()
        self.jawl = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _JawlHandler)
        _JawlHandler.messages = []
        self.jawl_port_file = Path(self.temp.name) / "terminal.port"
        self.jawl_port_file.write_text(str(self.jawl.server_address[1]), encoding="utf-8")
        self.jawl_adapter = JawlTerminalAdapter(self.jawl_port_file, timeout=2)
        self.jawl_chat_adapter = JawlWebChatAdapter(
            f"http://127.0.0.1:{self.jawl_chat_provider.server_port}",
            timeout_seconds=2,
            chat_timeout_seconds=2,
        )
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
            jawl_web=JawlWebAdapter(
                f"http://127.0.0.1:{self.jawl_web_provider.server_port}", timeout_seconds=2,
            ),
        )
        self.voice_mem = VoiceMemProcessClient(
            sys.executable,
            args=("--test-stub",),
            timeout_seconds=2,
        )
        self.tts = TTSService(CozyVoiceHttpClient(
            f"http://127.0.0.1:{self.tts_provider.server_port}", timeout_seconds=2,
        ))
        self.ambient_memory = AmbientMemoryBuffer(enabled=True)
        self.ambient_bridge = AmbientAudioASRBridge(_AmbientVoiceMem(), self.ambient_memory)
        self.ambient_audio = AmbientAudioService(
            self.ambient_bridge,
            capture=SystemAudioLoopback(self.ambient_bridge.consume, backend=_AmbientBackend()),
        )
        self.avatar_root = Path(self.temp.name) / "live2d"
        self.jawl_event_dir = Path(self.temp.name) / "jawl-events"
        self.avatar_root.mkdir()
        self.avatar_model = (
            '{"FileReferences":{"Moc":"companion.moc3",'
            '"Textures":["textures/body.png"],"Motions":{"Idle":[]}}}'
        )
        (self.avatar_root / "model3.json").write_text(self.avatar_model, encoding="utf-8")
        (self.avatar_root / "companion.moc3").write_bytes(b"moc")
        (self.avatar_root / "textures").mkdir()
        (self.avatar_root / "textures" / "body.png").write_bytes(b"png")
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
            jawl_event_dir=self.jawl_event_dir,
            ambient_memory=self.ambient_memory,
            ambient_audio=self.ambient_audio,
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
        self.jawl_web_provider.shutdown()
        self.jawl_web_provider.server_close()
        self.jawl_chat_provider.shutdown()
        self.jawl_chat_provider.server_close()
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
        _, doctor = self.get_json("/api/doctor")
        doctor_checks = {item["id"]: item for item in doctor["checks"]}
        self.assertEqual(doctor["status"], "ready")
        self.assertTrue(doctor_checks["jawl"]["ready"])
        self.assertTrue(doctor_checks["voicemem"]["ready"])
        self.assertTrue(doctor_checks["tts"]["ready"])
        self.assertTrue(doctor_checks["vision"]["ready"])
        self.assertTrue(doctor_checks["avatar"]["ready"])
        self.assertTrue(doctor_checks["hostos"]["ready"])
        self.assertNotIn("must-not-cross", json.dumps(doctor, ensure_ascii=False))
        with urlopen(self.base + "/", timeout=3) as response:
            self.assertIn(b"attention-dnd", response.read())
        with urlopen(self.base + "/avatar", timeout=3) as response:
            self.assertIn(b"JAWL Avatar", response.read())
        _, avatar_config = self.get_json("/api/avatar/config")
        self.assertTrue(avatar_config["enabled"])
        self.assertTrue(avatar_config["ready"])
        self.assertEqual(avatar_config["validation"]["missing"], [])
        with urlopen(self.base + "/avatar-assets/model3.json", timeout=3) as response:
            self.assertEqual(response.read().decode("utf-8"), self.avatar_model)

        status, chat = self.post_json("/api/chat", {"text": "проверка e2e"})
        self.assertEqual(status, 200)
        self.assertEqual(chat["text"], "JAWL E2E: проверка e2e")
        self.assertEqual(_JawlHandler.messages, [{"text": "проверка e2e"}])
        self.assertEqual(self.jawl_adapter.last_status, "connected")
        status, state = self.get_json("/api/state")
        self.assertEqual(state["last_turn"]["response"]["text"], chat["text"])

        self.jawl_adapter.timeout = 0.1
        _, degraded = self.post_json("/api/chat", {"text": "no broadcast"})
        self.assertIn("fallback", degraded["text"])
        self.assertEqual(self.jawl_adapter.status(), "no_broadcast")
        self.jawl_adapter.timeout = 2

        self.gateway.responder = self.jawl_chat_adapter
        self.gateway.brain_name = "jawl_web_chat"
        _, web_chat = self.post_json("/api/chat", {"text": "web-correlated"})
        self.assertEqual(web_chat["text"], "JAWL WEB E2E: web-correlated")
        self.assertEqual(self.jawl_chat_adapter.chat_status(), "connected")
        _, connected_health = self.get_json("/api/health")
        self.assertEqual(connected_health["components"]["jawl"], "connected")

        _, sanitized = self.post_json("/api/chat", {"text": "hidden markup"})
        self.assertEqual(sanitized["text"], "JAWL WEB E2E: sanitized")
        self.assertNotIn("hidden reasoning", json.dumps(sanitized, ensure_ascii=False))

        _JawlChatWebHandler.available = False
        _, offline = self.post_json("/api/chat", {"text": "upstream offline"})
        self.assertIn("fallback", offline["text"])
        self.assertEqual(self.jawl_chat_adapter.chat_status(), "offline")
        _JawlChatWebHandler.available = True
        _, recovered = self.post_json("/api/chat", {"text": "web-recovered"})
        self.assertEqual(recovered["text"], "JAWL WEB E2E: web-recovered")
        self.assertEqual(self.jawl_chat_adapter.chat_status(), "connected")

        self.jawl_chat_adapter.chat_timeout_seconds = 1
        _, web_degraded = self.post_json("/api/chat", {"text": "no broadcast"})
        self.assertIn("fallback", web_degraded["text"])
        self.assertEqual(self.jawl_chat_adapter.chat_status(), "no_broadcast")
        _, degraded_health = self.get_json("/api/health")
        self.assertEqual(degraded_health["components"]["jawl"], "no_broadcast")
        self.jawl_chat_adapter.chat_timeout_seconds = 2

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
        _, audit = self.get_json("/api/audit")
        self.assertTrue(audit["events"])
        self.assertTrue(any(event["type"] == "ACCESS_LEVEL_CHANGED" for event in audit["events"]))
        self.assertNotIn("e2e-ok", json.dumps(audit, ensure_ascii=False))

    def test_jawl_web_memory_and_persona_are_visible_without_secrets(self):
        _, health = self.get_json("/api/health")
        self.assertEqual(health["components"]["jawl_web"], "online")
        _, status = self.get_json("/api/jawl/status")
        self.assertEqual(status, {"configured": True, "status": "online"})

        _, memory = self.get_json("/api/jawl/memory")
        self.assertEqual(memory["database"]["sql"]["counts"]["notes"], 4)
        self.assertEqual(memory["drives"]["drives"][0]["name"], "curiosity")
        self.assertNotIn("must-not-cross", json.dumps(memory, ensure_ascii=False))

        _, persona = self.get_json("/api/jawl/persona")
        self.assertEqual(persona["settings"]["settings:identity.agent_name"], "Луна")
        self.assertNotIn("must-not-leak", json.dumps(persona, ensure_ascii=False))

        _, overview = self.get_json("/api/jawl/overview")
        self.assertEqual(overview["status"], "ok")
        self.assertEqual(overview["sources"]["tick"]["step"], 7)
        self.assertNotIn("must-not-cross", json.dumps(overview, ensure_ascii=False))

    def test_ambient_memory_is_delayed_bounded_and_visible(self):
        now = time.time()
        self.server.ambient_memory.ingest_system_audio(
            "В игре появился важный квест.",
            confidence=0.9,
            event_id="ambient-audio-e2e",
            now=now,
        )
        self.server.ambient_memory.ingest_visual(
            "На экране видна цель квеста.",
            confidence=0.8,
            event_id="ambient-screen-e2e",
            now=now + 1,
        )
        _, before = self.get_json("/api/ambient-memory")
        self.assertEqual(before["state"]["observation_count"], 2)
        self.assertEqual(before["state"]["episode_count"], 0)
        self.assertFalse(before["observations"][0]["payload"]["raw_audio_persisted"])
        self.assertFalse(before["observations"][1]["payload"]["raw_frame_persisted"])

        _, triaged = self.post_json("/api/ambient-memory/triage", {})
        self.assertEqual(triaged["status"], "processed")
        self.assertEqual(len(triaged["episodes"]), 1)
        episode = triaged["episodes"][0]
        self.assertEqual(episode["payload"]["source"], "mixed")
        self.assertEqual(episode["payload"]["importance"], "promote_candidate")
        self.assertFalse(episode["payload"]["raw_audio_persisted"])
        self.assertFalse(episode["payload"]["raw_frame_persisted"])
        _, after = self.get_json("/api/ambient-memory")
        self.assertEqual(after["state"]["episode_count"], 1)
        self.assertEqual(after["episodes"][0]["payload"]["source_event_ids"], [
            "ambient-audio-e2e", "ambient-screen-e2e",
        ])
        self.post_json("/api/ambient-memory/clear", {})
        _, cleared = self.get_json("/api/ambient-memory")
        self.assertEqual(cleared["state"]["observation_count"], 0)
        self.assertEqual(cleared["state"]["episode_count"], 0)

    def test_system_audio_loopback_reaches_ambient_memory_without_user_turn(self):
        bridge = AmbientAudioASRBridge(_AmbientVoiceMem(), self.server.ambient_memory)
        capture = SystemAudioLoopback(
            bridge.consume,
            backend=_AmbientBackend(),
            queue_size=2,
        )
        capture.start()
        capture.backend.last.stream.callback(b"\x01\x00" * 1600, 48000, {}, None)
        deadline = time.monotonic() + 2
        while self.server.ambient_memory.state()["observation_count"] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        capture.stop()
        _, ambient = self.get_json("/api/ambient-memory")
        self.assertEqual(ambient["state"]["observation_count"], 1)
        self.assertEqual(ambient["observations"][0]["event_id"], "ambient-loopback-e2e")
        self.assertEqual(ambient["observations"][0]["payload"]["stream"], "system_audio")
        _, state = self.get_json("/api/state")
        self.assertIsNone(state["last_turn"])
        _, triaged = self.post_json("/api/ambient-memory/triage", {})
        self.assertEqual(triaged["status"], "processed")
        self.assertEqual(triaged["episodes"][0]["payload"]["source"], "system_audio")

    def test_ambient_audio_requires_explicit_browser_lifecycle(self):
        _, initial = self.get_json("/api/ambient-audio")
        self.assertTrue(initial["configured"])
        self.assertTrue(initial["enabled"])
        self.assertFalse(initial["capture"]["running"])
        self.server.ambient_memory.set_enabled(False)
        request = Request(
            self.base + "/api/ambient-audio/start",
            data=b"{}",
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 409)
        context.exception.close()
        self.server.ambient_memory.set_enabled(True)
        _, started = self.post_json("/api/ambient-audio/start", {})
        self.assertTrue(started["ok"])
        self.assertTrue(started["state"]["capture"]["running"])
        _, stopped = self.post_json("/api/ambient-audio/stop", {})
        self.assertFalse(stopped["state"]["capture"]["running"])
        self.assertEqual(stopped["state"]["flush"]["status"], "flushed")

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
        self.server.attention.configure(min_significance=1)
        deadline = time.monotonic() + 3
        while not watcher.events() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(watcher.events())
        self.assertEqual(watcher.events()[0]["type"], "SCREEN_DELTA")
        self.assertNotIn("image", watcher.events()[0])
        _, event_log = self.get_json("/api/vision/events")
        self.assertEqual(event_log["events"][0]["type"], "SCREEN_DELTA")
        _, intents = self.get_json("/api/vision/intents")
        self.assertEqual(intents["intents"][0]["type"], "SPEAK_INTENT")
        event_files = list(self.jawl_event_dir.glob("*.json"))
        self.assertEqual(len(event_files), 1)
        jawl_event = json.loads(event_files[0].read_text(encoding="utf-8"))
        self.assertEqual(jawl_event["payload"]["event_type"], "SCREEN_DELTA")
        self.assertNotIn("image", json.dumps(jawl_event, ensure_ascii=False))
        _, attention = self.post_json("/api/attention", {"dnd": True, "budget_per_hour": 3})
        self.assertTrue(attention["attention"]["dnd"])
        self.assertEqual(attention["attention"]["budget_per_hour"], 3)
        _, vision_status = self.get_json("/api/vision/status")
        self.assertTrue(vision_status["attention"]["dnd"])
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
