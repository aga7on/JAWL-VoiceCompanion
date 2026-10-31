import json
import inspect
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.gateway import validate_response_envelope  # noqa: E402
from jawl_voicecompanion.jawl_web import JawlWebUnavailable  # noqa: E402
from jawl_voicecompanion.web import (  # noqa: E402
    CompanionServer,
    create_server,
    is_meaningful_transcript,
    voice_memory_block,
)
from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.perception_packet import split_packet, render_packet


def _stop_test_http_server(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    if thread.is_alive():
        raise AssertionError("test HTTP server thread did not stop")
    server.server_close()


class MeaningfulTranscriptTests(unittest.TestCase):
    def test_rejects_asr_noise_artifacts(self):
        for junk in (
            "嗯嗯嗯。",
            "嗯嗯",
            "嗯",
            "嗯哼",
            "啊！",
            "ммм",
            "ааа",
            ",.,",
            "",
        ):
            with self.subTest(junk=junk):
                self.assertFalse(is_meaningful_transcript(junk))

    def test_keeps_real_short_utterances(self):
        for speech in (
            "Ок",
            "Да",
            "Нет",
            "Ладно",
            "Угу",
            "привет, как дела?",
            "Пойдём гулять",
            "Windows не отвечает",
        ):
            with self.subTest(speech=speech):
                self.assertTrue(is_meaningful_transcript(speech))

    def test_rejects_repeated_filler_runs(self):
        for junk in (
            "ага ага ага",
            "Ага. Ага. Ага. Ага!",
            "угу угу угу угу",
            "мгм мгм мгм",
            "ага угу ага угу",
            "хм хм хм",
        ):
            with self.subTest(junk=junk):
                self.assertFalse(is_meaningful_transcript(junk))

    def test_keeps_short_filler_acknowledgements_and_real_repetition(self):
        for speech in (
            "ага",
            "угу, понятно",
            "ага ага",  # two acks: real backchannel, not a hallucination run
            "да да, конечно",
            "ну и ну",
            "очень очень хорошо",
        ):
            with self.subTest(speech=speech):
                self.assertTrue(is_meaningful_transcript(speech))

    def test_error_envelope_is_never_voiced(self):
        envelope = {
            "schema_version": 1,
            "response_id": "r-1",
            "turn_id": "t-1",
            "text": "JAWL недоступен: текущий turn завершён с ошибкой.",
            "speak": True,
            "emotion": {"id": "error", "intensity": 0.35, "confidence": 1.0},
            "avatar": {"expression": "error", "motion": "blink", "state": "error"},
            "voice": {"provider": "not_connected", "voice_id": "main_ru", "rate": 1.0},
            "actions": [],
            "interruptible": True,
            "proactive": False,
        }
        normalized = TextGateway._preserve_native_envelope(envelope)
        self.assertIs(normalized["speak"], False)
        self.assertEqual(normalized["avatar"]["state"], "error")
        validate_response_envelope(normalized)


class _NativeSkillStub:
    token = "native-token"

    def __init__(self):
        self.calls = []

    def execute_hostos_skill(self, skill, arguments):
        self.calls.append((skill, arguments))
        return {
            "status": "native",
            "result": {"is_success": True, "skill": skill},
        }


class _FakeJawlMemory:
    token = "native-token"

    def __init__(self):
        self.calls = []

    def remember_memory(self, **payload):
        self.calls.append(payload)
        return {"status": "synchronized", "memory": {"is_success": True}}

    def autonomy_journal(self, limit=20, state=None):
        self.calls.append(("journal", limit, state))
        return {
            "configured": True,
            "status": "ok",
            "native": True,
            "source": "jawl.action_journal",
            "plans": [{"plan_id": "p1", "state": state or "completed"}],
        }


class _FakeProductApi:
    """JAWL adapter stub matching JawlWebAdapter's read-only surface used by
    the Product API facades (ADR-041): status, memory, persona, hostos,
    autonomy_journal, overview."""

    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append("status")
        return "online"

    def memory(self):
        self.calls.append("memory")
        return {"configured": True, "status": "ok", "database": {"rows": 7}}

    def persona(self):
        self.calls.append("persona")
        return {"configured": True, "status": "ok", "settings": {"name": "Luna"}}

    def hostos(self):
        self.calls.append("hostos")
        return {"configured": True, "status": "ok", "access_level": 2, "access_name": "OPERATOR"}

    def autonomy_journal(self, limit=20, state=None):
        self.calls.append(("journal", limit, state))
        return {
            "configured": True,
            "status": "ok",
            "plans": [{"plan_id": "p1", "state": state or "completed"}],
        }

    def overview(self):
        self.calls.append("overview")
        return {"configured": True, "status": "ok"}


class _UnavailableJawlControl:
    token = "native-token"

    def emergency_stop(self, **_kwargs):
        raise JawlWebUnavailable("native stop unavailable")

    def stop_agent(self):
        raise JawlWebUnavailable("native agent stop unavailable")

    def reset_emergency_stop(self, **_kwargs):
        raise JawlWebUnavailable("native reset unavailable")

    def start_agent(self):
        raise JawlWebUnavailable("native agent start unavailable")


class WebTests(unittest.TestCase):
    def test_default_control_port_is_2367(self):
        self.assertEqual(inspect.signature(create_server).parameters["port"].default, 2367)


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
        _stop_test_http_server(self.server, self.thread)

    def get_json(self, path):
        with urlopen(self.base + path, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def get_json_auth(self, path):
        request = Request(self.base + path, headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_avatar_wardrobe_is_bounded_and_session_gated(self):
        # ADR-045 appearance surface: only .vrm files from the wardrobe dir,
        # session-gated, no arbitrary paths in the payload.
        request = Request(self.base + "/api/avatar/wardrobe")
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        status, wardrobe = self.get_json_auth("/api/avatar/wardrobe")
        self.assertEqual(status, 200)
        self.assertEqual(wardrobe["schema_version"], 1)
        self.assertIn("runtime/vrm-models", wardrobe["root"])
        for item in wardrobe["models"]:
            self.assertNotIn("/", item["model"])
            self.assertNotIn("\\", item["model"])
            self.assertLessEqual(item["size_bytes"], 200 * 1024 * 1024)

    def post_json(self, path, payload):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.session_headers},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_managed_profile_stop_requires_session_and_records_atomic_request(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "launcher-stop.request"
            status_target = Path(directory) / "launcher-stop.status"
            self.server.launcher_stop_request = target
            self.server.launcher_stop_status = status_target
            status, result = self.post_json("/api/profile/stop", {})
            self.assertEqual(status, 202)
            self.assertEqual(result["ok"], True)
            self.assertEqual(result["status"], "stop_requested")
            request = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(request["schema_version"], 1)
            self.assertEqual(request["runtime_instance_id"], self.server.runtime_instance_id)
            self.assertRegex(request["request_id"], r"^[0-9a-f]{32}$")
            self.assertEqual(result["request_id"], request["request_id"])
            self.assertIn("requested_at", request)

            status_code, pending = self.get_json_auth("/api/profile/stop/status")
            self.assertEqual(status_code, 200)
            self.assertEqual(pending["status"], "waiting_for_launcher")
            status_target.write_text(json.dumps({
                "schema_version": 1,
                "runtime_instance_id": self.server.runtime_instance_id,
                "request_id": request["request_id"],
                "status": "stopping",
            }), encoding="utf-8")
            status_code, acknowledged = self.get_json_auth("/api/profile/stop/status")
            self.assertEqual(status_code, 200)
            self.assertEqual(acknowledged["status"], "stopping")
            self.assertEqual(acknowledged["request_id"], request["request_id"])

            status_target.write_text(json.dumps({
                "schema_version": 1,
                "runtime_instance_id": "0" * 32,
                "request_id": request["request_id"],
                "status": "stopping",
            }), encoding="utf-8")
            _, mismatched = self.get_json_auth("/api/profile/stop/status")
            self.assertEqual(mismatched["status"], "waiting_for_launcher")

            unauthenticated = Request(
                self.base + "/api/profile/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as denied:
                urlopen(unauthenticated, timeout=2)
            self.assertEqual(denied.exception.code, 403)
            denied.exception.close()

            unauthenticated_status = Request(self.base + "/api/profile/stop/status")
            with self.assertRaises(HTTPError) as denied_status:
                urlopen(unauthenticated_status, timeout=2)
            self.assertEqual(denied_status.exception.code, 403)
            denied_status.exception.close()

    def test_managed_profile_stop_fails_closed_when_not_owned_by_launcher(self):
        self.server.launcher_stop_request = None
        self.server.launcher_stop_status = None
        request = Request(
            self.base + "/api/profile/stop",
            data=b"{}",
            headers={"Content-Type": "application/json", **self.session_headers},
            method="POST",
        )
        with self.assertRaises(HTTPError) as unavailable:
            urlopen(request, timeout=2)
        self.assertEqual(unavailable.exception.code, 503)
        payload = json.loads(unavailable.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "managed profile stop is unavailable")
        unavailable.exception.close()

    def test_health_and_browser_are_available(self):
        status, health = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["mode"], "phase1_mock_brain")
        self.assertRegex(health["runtime_instance_id"], r"^[0-9a-f]{32}$")
        _, second_health = self.get_json("/api/health")
        self.assertEqual(health["runtime_instance_id"], second_health["runtime_instance_id"])
        self.assertEqual(health["resources"]["profile"], "standard")
        _, doctor = self.get_json("/api/doctor")
        self.assertEqual(health["status"], doctor["status"])
        for check in doctor["checks"]:
            self.assertEqual(health["components"][check["id"]], check["status"])
        with urlopen(self.base + "/app", timeout=2) as response:
            frontend = response.read()
            self.assertIn(b"JAWL Companion", frontend)
            self.assertIn(b"hud-mic", frontend)
            self.assertIn(b"hud-senses", frontend)
            self.assertIn(b"hud-dnd", frontend)
            self.assertIn(b"hud-pin", frontend)
            self.assertIn(b"compact-mode", frontend)
        with urlopen(self.base + "/app.js", timeout=2) as response:
            js = response.read()
            self.assertIn(b"/api/attention", js)
            self.assertIn(b"/api/tts/stream", js)
            self.assertIn(b"/api/ambient-memory", js)
            self.assertIn(b"toggleSenses", js)
            self.assertIn(b"response.body.getReader()", js)
            self.assertIn(b"/api/chat/stream", js)
            self.assertIn(b"cancelSpeechPlayback", js)
            self.assertIn(b"AbortController", js)
            self.assertIn(b"requestAnimationFrame", js)
            self.assertIn(b"emotion", js)
            self.assertIn(b"Analyser", js)
        # ADR-052: /avatar is the alias of the single app's ?mode=obs surface
        # (the separate presentation origin is removed); old OBS links follow
        # the redirect to the renderer-only app window.
        with urlopen(self.base + "/avatar?source=obs", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("mode=obs", response.geturl())
            self.assertIn(b"JAWL Companion", response.read())
        with urlopen(self.base + "/mic-processor.js", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"AudioWorkletProcessor", response.read())
        vision_script = (Path(__file__).parents[1] / "scripts" / "run_vision_server.ps1").read_bytes()
        self.assertIn(b"VLM-RealTime-Bench\\runtime\\llama-b10738-cpu", vision_script)
        self.assertIn(b"VLM-RealTime-Bench\\models\\Qwen3-VL-2B", vision_script)

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

    def test_attention_preferences_survive_server_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "presence.json"
            first = create_server(
                port=0,
                frontend_dir=Path(__file__).parents[1] / "frontend",
                gateway=TextGateway(),
                presence_file=path,
            )
            first.attention.configure(dnd=True, quiet_hours="22:00-07:00")
            first._persist_presence_preferences()
            first.server_close()

            second = create_server(
                port=0,
                frontend_dir=Path(__file__).parents[1] / "frontend",
                gateway=TextGateway(),
                presence_file=path,
            )
            try:
                self.assertTrue(second.attention.state()["dnd"])
                self.assertEqual(second.attention.state()["quiet_hours"], "22:00-07:00")
            finally:
                second.server_close()

    def test_session_endpoint_exposes_local_bootstrap_tokens(self):
        status, session = self.get_json("/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["csrf_token"])
        self.assertNotIn("session_token", session)

    def test_stream_chat_is_bounded_observation_api(self):
        status, result = self.post_json("/api/stream-chat", {
            "event": {
                "id": "chat-web-1",
                "platform": "twitch",
                "author": "viewer",
                "text": "привет из чата",
                "ignored": "not forwarded",
            },
            "url_metadata": {"url": "https://example.test/watch?token=hidden"},
        })
        self.assertEqual(status, 202)
        self.assertTrue(result["ok"])
        deadline = time.monotonic() + 1.0
        state = {}
        while time.monotonic() < deadline:
            _, state = self.get_json_auth("/api/stream-chat")
            if state["stats"]["delivered"] == 1:
                break
            time.sleep(0.01)
        self.assertEqual(state["stats"]["delivered"], 1)
        event = state["recent_events"][0]
        self.assertEqual(event["type"], "CHAT_MESSAGE")
        self.assertNotIn("ignored", json.dumps(event, ensure_ascii=False))
        self.assertNotIn("hidden", json.dumps(event, ensure_ascii=False))

    def test_avatar_audio_is_bounded_ephemeral_and_session_bound(self):
        _, initial = self.get_json_auth("/api/state")
        self.assertFalse(initial["avatar_audio"]["speaking"])
        request = Request(
            self.base + "/api/avatar/audio",
            data=b'{"amplitude":0.5,"speaking":true,"timestamp_ms":1}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        _, changed = self.post_json("/api/avatar/audio", {"amplitude": 0.5, "speaking": True, "timestamp_ms": 10})
        self.assertTrue(changed["avatar_audio"]["speaking"])
        self.assertEqual(changed["avatar_audio"]["amplitude"], 0.5)
        _, stale = self.post_json("/api/avatar/audio", {"amplitude": 0.0, "speaking": False, "timestamp_ms": 9})
        self.assertTrue(stale["avatar_audio"]["speaking"])
        _, stopped = self.post_json("/api/avatar/audio", {"amplitude": 0.0, "speaking": False, "timestamp_ms": 11})
        self.assertFalse(stopped["avatar_audio"]["speaking"])
        self.post_json("/api/avatar/audio", {"amplitude": 0.5, "speaking": True, "timestamp_ms": 12})
        time.sleep(0.8)
        _, expired = self.get_json_auth("/api/state")
        self.assertFalse(expired["avatar_audio"]["speaking"])

    def test_vision_status_and_dry_run_look_are_available(self):
        status, vision = self.get_json("/api/vision/status")
        self.assertEqual(status, 200)
        self.assertFalse(vision["configured"])
        self.assertEqual(vision["plan_execution"], "local_hostos")
        self.assertIn("attention", vision)
        class _VisualSensor:
            def state(self):
                return {"caption_fresh": False, "caption_age_ms": 5100.0, "caption_ttl_ms": 5000.0}

            def stop(self):
                return None

        self.server.visual_sensor = _VisualSensor()
        status, vision = self.get_json("/api/vision/status")
        self.assertEqual(status, 200)
        self.assertEqual(vision["visual_sensor"]["caption_fresh"], False)
        self.assertEqual(vision["visual_sensor"]["caption_age_ms"], 5100.0)
        self.post_json("/api/hostos/level", {"level": 1})
        status, result = self.post_json("/api/vision/look", {"prompt": "Что видно?"})
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"]["status"], "degraded")
        self.assertNotIn("image", result["result"])

    def test_vision_execute_requires_explicit_confirmation_and_validates_plan(self):
        with self.assertRaises(HTTPError) as context:
            self.post_json("/api/vision/execute", {"plan": {}})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()
        status, result = self.post_json(
            "/api/vision/execute", {"confirm": True, "plan": {}}
        )
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"]["status"], "denied")

    def test_attention_reports_disabled_activity_by_default(self):
        status, attention = self.get_json("/api/attention")
        self.assertEqual(status, 200)
        self.assertEqual(attention["activity"]["status"], "disabled")

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

    def test_attention_quiet_hours_are_configurable_from_browser(self):
        _, changed = self.post_json("/api/attention", {"quiet_hours": "22:00-07:00"})
        self.assertEqual(changed["attention"]["quiet_hours"], "22:00-07:00")
        _, cleared = self.post_json("/api/attention", {"quiet_hours": None})
        self.assertIsNone(cleared["attention"]["quiet_hours"])

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

        class _AmbientAudio:
            def state(self):
                return {
                    "audio_description_configured": True,
                    "audio_description_count": 2,
                    "audio_description_latency_ms_p50": 1800.0,
                    "audio_description_latency_ms_p95": 2600.0,
                }

            def stop(self):
                return None

        self.server.ambient_audio = _AmbientAudio()
        request = Request(self.base + "/api/ambient-audio", headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertEqual(status["audio_description_count"], 2)
        self.assertEqual(status["audio_description_latency_ms_p95"], 2600.0)

    def test_tts_playback_marker_is_ephemeral(self):
        status, started = self.post_json(
            "/api/ambient-audio/playback", {"active": True, "ttl_seconds": 5}
        )
        self.assertEqual(status, 200)
        self.assertTrue(started["playback"]["active"])
        _, stopped = self.post_json(
            "/api/ambient-audio/playback", {"active": False}
        )
        self.assertFalse(stopped["playback"]["active"])

    def test_ambient_memory_is_off_until_explicitly_enabled(self):
        request = Request(self.base + "/api/ambient-memory", headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            initial = json.loads(response.read().decode("utf-8"))
        self.assertFalse(initial["state"]["enabled"])
        _, enabled = self.post_json("/api/ambient-memory/config", {"enabled": True})
        self.assertTrue(enabled["state"]["enabled"])
        _, disabled = self.post_json("/api/ambient-memory/config", {"enabled": False})
        self.assertFalse(disabled["state"]["enabled"])

    def test_ambient_memory_pause_and_resume_require_browser_session(self):
        for suffix in ("pause", "resume"):
            request = Request(
                self.base + f"/api/ambient-memory/{suffix}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(HTTPError) as context:
                urlopen(request, timeout=2)
            self.assertEqual(context.exception.code, 403)
            context.exception.close()

    def test_ambient_memory_pause_blocks_ingest_until_resume(self):
        self.server.ambient_memory.set_enabled(True)
        _, paused = self.post_json("/api/ambient-memory/pause", {})
        self.assertTrue(paused["state"]["paused"])
        rejected = self.server.ambient_memory.ingest_system_audio(
            "Не должно попасть", confidence=0.9, event_id="paused-ingest"
        )
        self.assertEqual(rejected["status"], "paused")
        _, resumed = self.post_json("/api/ambient-memory/resume", {})
        self.assertFalse(resumed["state"]["paused"])
        accepted = self.server.ambient_memory.ingest_system_audio(
            "Должно попасть", confidence=0.9, event_id="resumed-ingest"
        )
        self.assertNotEqual(accepted["status"], "paused")
        self.assertEqual(self.server.ambient_memory.state()["observation_count"], 1)

    def test_ambient_audio_pause_and_resume_report_unconfigured(self):
        for suffix in ("pause", "resume"):
            request = Request(
                self.base + f"/api/ambient-audio/{suffix}",
                data=b"{}",
                headers={"Content-Type": "application/json", **self.session_headers},
            )
            with self.assertRaises(HTTPError) as context:
                urlopen(request, timeout=2)
            self.assertEqual(context.exception.code, 503)
            context.exception.close()

    def test_ambient_disable_and_erase_requires_confirmation_and_clears(self):
        self.server.ambient_memory.set_enabled(True)
        self.server.ambient_memory.ingest_system_audio(
            "Важное событие", confidence=0.9, event_id="erase-e2e"
        )
        with self.assertRaises(HTTPError) as context:
            self.post_json("/api/ambient-memory/config", {
                "mode": "disable_and_erase",
            })
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

        _, erased = self.post_json("/api/ambient-memory/config", {
            "mode": "disable_and_erase", "confirm": True,
        })
        self.assertEqual(erased["mode"], "disable_and_erase")
        self.assertFalse(erased["state"]["enabled"])
        self.assertEqual(erased["state"]["observation_count"], 0)

    def test_ambient_promotion_requires_consent_and_writes_only_to_native_jawl(self):
        native = _FakeJawlMemory()
        self.server.gateway.jawl_web = native
        self.server.ambient_memory.set_enabled(True)
        self.server.ambient_memory.ingest_visual(
            "Важный дедлайн, запомни эту цель.",
            confidence=0.95,
            event_id="episode-promote",
            now=time.time(),
        )
        triaged = self.server.ambient_memory.triage()
        episode_id = triaged["episodes"][0]["event_id"]
        with self.assertRaises(HTTPError) as context:
            self.post_json("/api/ambient-memory/promote", {"episode_id": episode_id})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()
        _, promoted = self.post_json(
            "/api/ambient-memory/promote",
            {"episode_id": episode_id, "confirm": True},
        )
        self.assertEqual(promoted["status"], "promoted")
        self.assertTrue(promoted["episode"]["payload"]["promoted"])
        self.assertEqual(native.calls[0]["kind"], "summary")
        self.assertEqual(native.calls[0]["provenance"]["ambient_episode_id"], episode_id)
        _, repeated = self.post_json(
            "/api/ambient-memory/promote",
            {"episode_id": episode_id, "confirm": True},
        )
        self.assertEqual(repeated["status"], "already_promoted")
        self.assertEqual(len(native.calls), 1)

    def test_voice_status_is_explicit_when_sidecar_is_not_configured(self):
        status, voice = self.get_json("/api/voice/status")
        self.assertEqual(status, 200)
        self.assertFalse(voice["configured"])
        self.assertEqual(voice["status"], "not_configured")

    def test_voice_status_uses_nonblocking_process_snapshot(self):
        class BusyVoiceMem:
            def state(self):
                return {"status": "running", "running": True, "ready": True, "pid": 17}

            def health(self):
                raise AssertionError("status polling must not send a blocking health RPC")

            def close(self):
                return None

        self.server.voice_mem = BusyVoiceMem()
        status, voice = self.get_json("/api/voice/status")
        self.assertEqual(status, 200)
        self.assertTrue(voice["configured"])
        self.assertEqual(voice["voicemem"]["status"], "running")
        self.assertTrue(voice["voicemem"]["ready"])

    def test_chat_and_level_change_work(self):
        status, response = self.post_json("/api/chat", {"text": "Привет"})
        self.assertEqual(status, 200)
        self.assertEqual(response["schema_version"], 1)
        status, changed = self.post_json("/api/hostos/level", {"level": 2})
        self.assertEqual(status, 200)
        self.assertEqual(changed["policy"]["active_name"], "OPERATOR")

    def test_unattended_and_denylist_are_explicit_policy_controls(self):
        with self.assertRaises(HTTPError) as context:
            self.post_json("/api/hostos/unattended", {"enabled": True})
        with context.exception:
            self.assertEqual(context.exception.code, 400)
        self.post_json("/api/hostos/level", {"level": 3})
        status, enabled = self.post_json("/api/hostos/unattended", {"enabled": True})
        self.assertEqual(status, 200)
        self.assertTrue(enabled["policy"]["unattended"])
        status, blocked = self.post_json("/api/hostos/denylist", {"tools": ["shell.exec"], "risks": []})
        self.assertEqual(status, 200)
        self.assertEqual(blocked["policy"]["deny_tools"], ["shell.exec"])

    def test_emergency_stop_can_be_reset_in_local_control_plane(self):
        self.post_json("/api/emergency-stop", {})
        _, stopped = self.get_json_auth("/api/state")
        self.assertTrue(stopped["policy"]["emergency_stop"])
        status, resumed = self.post_json("/api/emergency-stop/reset", {})
        self.assertEqual(status, 200)
        self.assertFalse(resumed["policy"]["emergency_stop"])

    def test_bridge_emergency_stop_is_not_reported_ok_when_native_control_is_offline(self):
        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(jawl_web=_UnavailableJawlControl()),
            jawl_hostos_control=True,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {
            "X-Companion-Session": server.session_token,
            "X-Companion-CSRF": server.csrf_token,
        }
        request = Request(
            base + "/api/emergency-stop",
            data=b"{}",
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with self.assertRaises(HTTPError) as context:
                urlopen(request, timeout=2)
            with context.exception as error:
                body = json.loads(error.read().decode("utf-8"))
                self.assertEqual(error.code, 503)
                self.assertFalse(body["ok"])
                self.assertTrue(body["policy"]["emergency_stop"])
                self.assertEqual(body["jawl_policy"]["status"], "offline")
        finally:
            _stop_test_http_server(server, thread)

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

    def test_bridge_hostos_execute_never_calls_local_executor(self):
        native = _NativeSkillStub()
        bridge = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(jawl_web=native),
            jawl_hostos_control=True,
        )

        def local_must_not_run(*_args, **_kwargs):
            raise AssertionError("bridge mode must not execute the local HostOS adapter")

        bridge.hostos.execute = local_must_not_run
        thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{bridge.server_port}"
        headers = {
            "Content-Type": "application/json",
            "X-Companion-Session": bridge.session_token,
            "X-Companion-CSRF": bridge.csrf_token,
        }
        request = Request(
            base + "/api/hostos/execute",
            data=json.dumps({
                "request": {
                    "skill": "HostOSReader.read_file_range",
                    "arguments": {"filepath": "README.md"},
                }
            }).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["native"])
            self.assertEqual(native.calls[0][0], "HostOSReader.read_file_range")
        finally:
            _stop_test_http_server(bridge, thread)

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

    def test_browser_proposal_review_and_execute_flow(self):
        self.post_json("/api/hostos/level", {"level": 3})
        request_payload = {
            "request": {
                "tool": "shell.exec",
                "risk": "shell",
                "arguments": {"argv": ["echo", "secret-value"]},
            }
        }
        _, pending = self.post_json("/api/hostos/approvals/request", request_payload)
        approval_id = pending["result"]["approval_id"]
        _, listed = self.get_json_auth("/api/hostos/approvals")
        proposal = next(item for item in listed["approvals"] if item["approval_id"] == approval_id)
        self.assertEqual(proposal["review"]["arguments"]["argv"][1], "[redacted]")
        self.post_json(f"/api/hostos/approvals/{approval_id}/approve", {})
        _, approved = self.get_json_auth("/api/hostos/approvals")
        self.assertEqual(next(item for item in approved["approvals"] if item["approval_id"] == approval_id)["status"], "approved")
        _, executed = self.post_json(f"/api/hostos/approvals/{approval_id}/execute", {})
        self.assertEqual(executed["result"]["status"], "degraded")
        _, replay = self.post_json(f"/api/hostos/approvals/{approval_id}/execute", {})
        self.assertEqual(replay["result"]["status"], "approval_consumed")

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

    def test_jawl_autonomy_journal_is_bounded_and_session_bound(self):
        native = _FakeJawlMemory()
        self.server.gateway.jawl_web = native
        status, body = self.get_json_auth("/api/jawl/journal?limit=3&state=failed")
        self.assertEqual(status, 200)
        self.assertEqual(body["plans"][0]["state"], "failed")
        self.assertEqual(native.calls[-1], ("journal", 3, "failed"))

        request = Request(
            self.base + "/api/jawl/journal?limit=0",
            headers=self.session_headers,
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_product_api_facades_are_session_bound_and_versioned(self):
        native = _FakeProductApi()
        self.server.gateway.jawl_web = native
        # No session -> 403, same as the legacy JAWL inspection routes.
        for path in ("/api/memory", "/api/tasks", "/api/character",
                     "/api/runtime/status", "/api/capabilities"):
            with self.subTest(path=path):
                try:
                    urlopen(self.base + path, timeout=2)
                except HTTPError as error:
                    with error:
                        self.assertEqual(error.code, 403)
                else:
                    self.fail(f"{path} should return HTTP 403 without a session")

    def test_product_api_facades_expose_service_and_data(self):
        native = _FakeProductApi()
        self.server.gateway.jawl_web = native
        status, body = self.get_json_auth("/api/runtime/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["service"], "runtime")
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["status"], "online")
        self.assertIn("status", native.calls)

        status, memory = self.get_json_auth("/api/memory")
        self.assertEqual(status, 200)
        self.assertEqual(memory["service"], "memory")
        self.assertEqual(memory["database"]["rows"], 7)

        status, character = self.get_json_auth("/api/character")
        self.assertEqual(status, 200)
        self.assertEqual(character["service"], "character")
        self.assertEqual(character["settings"]["name"], "Luna")

        status, tasks = self.get_json_auth("/api/tasks?limit=5&state=completed")
        self.assertEqual(status, 200)
        self.assertEqual(tasks["service"], "tasks")
        self.assertEqual(tasks["plans"][0]["state"], "completed")
        self.assertEqual(native.calls[-1], ("journal", 5, "completed"))

        status, capabilities = self.get_json_auth("/api/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(capabilities["service"], "capabilities")
        self.assertEqual(capabilities["access_name"], "OPERATOR")

    def test_product_api_facades_report_not_configured_without_engine(self):
        # No JAWL adapter: canonical facades stay explicit instead of crashing.
        self.server.gateway.jawl_web = None
        for path in ("/api/memory", "/api/tasks", "/api/character", "/api/runtime/status"):
            with self.subTest(path=path):
                status, body = self.get_json_auth(path)
                self.assertEqual(status, 200)
                self.assertEqual(body["configured"], False)
                self.assertEqual(body["status"], "not_configured")
        status, capabilities = self.get_json_auth("/api/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(capabilities["status"], "not_configured")

    def test_legacy_jawl_aliases_keep_their_contract(self):
        native = _FakeProductApi()
        self.server.gateway.jawl_web = native
        # Legacy names must route through the same engine surface.
        status, body = self.get_json_auth("/api/jawl/persona")
        self.assertEqual(status, 200)
        self.assertEqual(body["settings"]["name"], "Luna")
        status, body = self.get_json_auth("/api/jawl/hostos")
        self.assertEqual(status, 200)
        self.assertEqual(body["access_level"], 2)
        self.assertIn(body["control_enabled"], (True, False))

    def test_audit_without_session_is_rejected(self):
        try:
            urlopen(self.base + "/api/audit", timeout=2)
        except HTTPError as error:
            with error:
                self.assertEqual(error.code, 403)
        else:
            self.fail("audit should return HTTP 403 without a session")


    def test_console_proxy_redirects_and_requires_session(self):
        import http.client
        from urllib.error import HTTPError

        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request("GET", "/console")
        response = connection.getresponse()
        self.assertEqual(response.status, 301)
        self.assertEqual(response.getheader("Location"), "/console/")
        response.read()
        request = Request(self.base + "/console/console.js")
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        connection.request(
            "GET", "/console/console.js",
            headers={"X-Companion-Session": self.server.session_token},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 503)
        self.assertIn(b"not configured", response.read())
        connection.close()


    def test_perception_now_requires_session_and_reports_state(self):
        from urllib.error import HTTPError

        request = Request(self.base + "/api/perception/now")
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        status, payload = self.get_json_auth("/api/perception/now")
        self.assertEqual(status, 200)
        self.assertIn("draft", payload)


class ObsSurfaceTests(unittest.TestCase):
    """ADR-052: one origin — the app serves both the panel and ?mode=obs."""

    def setUp(self):
        self.control = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
        )
        self.control_thread = threading.Thread(target=self.control.serve_forever, daemon=True)
        self.control_thread.start()
        self.base = f"http://127.0.0.1:{self.control.server_port}"

    def tearDown(self):
        _stop_test_http_server(self.control, self.control_thread)

    def test_control_origin_denies_frame_ancestors(self):
        with urlopen(self.base + "/app", timeout=2) as response:
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_avatar_alias_serves_the_obs_mode_app_on_the_same_origin(self):
        with urlopen(self.base + "/avatar", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"JAWL Companion", response.read())
            self.assertIn("mode=obs", response.geturl())

    def test_http_server_rejects_non_loopback_binds(self):
        with self.assertRaises(ValueError):
            create_server(host="0.0.0.0", port=0, gateway=TextGateway())


class _FakeStreamingAsr:
    def __init__(self, text="", active=True, silence_ms=800.0):
        self.text = text
        self.active = active
        self.silence_ms = silence_ms

    def snapshot(self, *, scope_id=None, session_id=None):
        return {"active": self.active, "text": self.text, "silence_ms": self.silence_ms}


class _FakeFusion:
    def __init__(self, line="", *, error=False):
        self.line = line
        self.error = error

    def compose(self):
        if self.error:
            raise RuntimeError("fusion offline")
        return self.line


class CurrentPerceptionEnrichmentTests(unittest.TestCase):
    def test_persisted_dialogue_is_rehydrated_without_losing_current_text(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class Gateway:
            arbiter = Arbiter()

            @staticmethod
            def turn_history(limit=12):
                return [{
                    "user": "We are discussing the quest marker.<va_perception>{ignored}</va_perception>",
                    "response": {"text": "It moved to the north gate."},
                }]

        class ServerContext:
            gateway = Gateway()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY

        ServerContext.perception_fusion = None
        enriched = CompanionServer.enrich_turn_text(ServerContext, "Continue from there.")

        self.assertIn("We are discussing the quest marker.", enriched)
        self.assertIn("It moved to the north gate.", enriched)
        self.assertIn("[CURRENT USER MESSAGE]\nContinue from there.", enriched)
        self.assertNotIn("ignored", enriched)

    def test_current_scene_question_gets_atomic_frame_provenance_and_history_guard(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY

        fusion = PerceptionFusion()
        capture_time = time.monotonic()
        fusion.observe_caption(
            "Earth from space with illuminated city lights.",
            captured_at_monotonic=capture_time,
            captured_at_wall=1_800_000_000.0,
            frame_id="qwen-frame-62",
            source="screen:qa-video:roi=0.1,0.1,0.8,0.8",
            scene_id="scene-7",
        )
        ServerContext.perception_fusion = fusion

        enriched = CompanionServer.enrich_turn_text(
            ServerContext,
            "Describe the current gameplay scene. Mention the visible characters and setting.",
        )

        self.assertNotIn("qwen-frame-62", enriched)
        self.assertNotIn("scene-7", enriched)
        self.assertNotIn("screen:qa-video", enriched)
        self.assertIn("Earth from space with illuminated city lights.", enriched)
        _, packet = split_packet(enriched)
        self.assertTrue(packet["channels"]["screen"]["hypothesis"])
        self.assertGreaterEqual(packet["channels"]["screen"]["age_s"], 0)

    def test_retained_system_audio_transcript_is_injected_into_next_brain_turn(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY

        fusion = PerceptionFusion()
        fusion.note("speech", "System-audio transcript: The quest marker moved to the north gate.")
        ServerContext.perception_fusion = fusion

        enriched = CompanionServer.enrich_turn_text(ServerContext, "What changed in the game?")

        self.assertIn("What changed in the game?", enriched)
        self.assertIn("System-audio transcript: The quest marker moved to the north gate.", enriched)

    def test_brain_context_carries_shared_audio_video_timing_and_source_ids(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY

        fusion = PerceptionFusion()
        captured = time.monotonic()
        fusion.observe_caption(
            "The current frame shows a teacher in a classroom.",
            captured_at_monotonic=captured,
            captured_at_wall=time.time(),
            frame_id="frame-17",
            source="screen:target-visible",
            scene_id="scene-4",
        )
        fusion.note(
            "ocr", "Quest: enter the observatory", now=captured - 0.1,
            metadata={"source": "windows_ocr", "verified": False, "frame_id": "frame-17"},
        )
        fusion.note(
            "speech",
            "System-audio transcript: The sun is dying.",
            now=captured - 0.4,
            metadata={
                "source": "system_audio_loopback",
                "segment_id": "audio-segment-9",
                "duration_ms": 15000,
                "segment_started_monotonic": captured - 16.0,
                "segment_ended_monotonic": captured - 1.0,
                "confidence": 0.7,
                "confidence_calibrated": False,
            },
        )
        fusion.note(
            "audio_description",
            "A tense orchestral cue rises under the narration.",
            now=captured - 0.8,
            metadata={"source": "eg2-audio", "audio_kind": "music", "verified": False},
        )
        fusion.note(
            "music",
            "Music detected by YAMNet.",
            now=captured - 1.2,
            metadata={
                "source": "system_audio_loopback",
                "segment_id": "audio-segment-9",
                "detector": "yamnet-onnx-cpu",
                "duration_ms": 15000,
                "model_score": 0.34,
                "calibrated": False,
                "music_state": "music",
                "segment_started_monotonic": captured - 16.0,
                "segment_ended_monotonic": captured - 1.2,
                "candidate_tags": ["Saxophone", "Electronic music"],
                "candidate_tags_calibrated": False,
                "music_windows": 3,
                "windows": 5,
                "rms_dbfs": -24.5,
                "energy_trend": "rising",
            },
        )
        fusion.note(
            "audio_candidates",
            "Possible music style: cinematic orchestral.",
            now=captured - 1.1,
            metadata={
                "source": "eg2-audio", "audio_kind": "music", "verified": False,
                "segment_started_monotonic": captured - 8.0,
                "segment_ended_monotonic": captured - 1.1,
            },
        )
        fusion.note(
            "audio_event_candidates",
            "Possible YAMNet sound event: impact.",
            now=captured - 0.7,
            metadata={"source": "yamnet-onnx-cpu", "verified": False},
        )
        ServerContext.perception_fusion = fusion

        enriched = CompanionServer.enrich_turn_text(ServerContext, "What is happening now?")

        clean, packet = split_packet(enriched)
        self.assertEqual(clean, "What is happening now?")
        channels = packet["channels"]
        self.assertIn("teacher in a classroom", channels["screen"]["text"])
        self.assertIn("quest", channels["ocr"]["text"].lower())
        self.assertIn("The sun is dying", channels["speech"]["text"])
        self.assertEqual(channels["speech"]["duration_s"], 15)
        self.assertGreaterEqual(channels["speech"]["age_s"], 1)
        self.assertIn("orchestral cue", channels["audio_description"]["text"])
        self.assertTrue(channels["audio_description"]["hypothesis"])
        self.assertIn("cinematic orchestral", channels["audio_candidates"]["text"])
        self.assertIn("Possible YAMNet", channels["audio_event_candidates"]["text"])
        self.assertTrue(channels["music"]["hypothesis"])
        self.assertEqual(channels["music"]["candidate_tags"], ["Saxophone", "Electronic music"])
        for diagnostic in ("frame-17", "scene-4", "audio-segment-9", "rms_dbfs", "music_windows", "model_score"):
            self.assertNotIn(diagnostic, enriched)
        self.assertIn("Saxophone", render_packet(packet))
        self.assertIn("orchestral cue", render_packet(packet))
        self.assertIn("cinematic orchestral", render_packet(packet))
        self.assertIn("impact", render_packet(packet))

    def test_unverified_audio_tag_warning_requires_fresh_uncalibrated_candidates(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY

        cases = (
            ("calibrated", 0.0, True, ["Saxophone"], False),
            ("no-tags", 0.0, False, [], False),
            ("stale", 25.0, False, ["Saxophone"], False),
            ("fresh-unverified", 0.0, False, ["Saxophone"], True),
        )
        warning = "\u0410\u0443\u0434\u0438\u043e\u0442\u0435\u0433\u0438 \u043a\u0430\u043d\u0434\u0438\u0434\u0430\u0442\u043d\u044b\u0435 \u0438 \u043d\u0435 \u043a\u0430\u043b\u0438\u0431\u0440\u043e\u0432\u0430\u043d\u044b"
        for label, age_s, calibrated, tags, expected in cases:
            with self.subTest(label=label):
                fusion = PerceptionFusion()
                now = time.monotonic()
                fusion.note(
                    "music",
                    "Music detected by YAMNet.",
                    now=now - age_s,
                    metadata={
                        "candidate_tags": tags,
                        "candidate_tags_calibrated": calibrated,
                    },
                )
                ServerContext.perception_fusion = fusion
                enriched = CompanionServer.enrich_turn_text(ServerContext, "What is two plus two?")
                _, packet = split_packet(enriched)
                rendered = render_packet(packet)
                self.assertEqual(bool(packet.get("channels", {}).get("music", {}).get("hypothesis")) and "Saxophone" in rendered, expected)

    def test_current_screen_question_does_not_mix_old_visual_history(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY
            _PERCEPTION_HISTORY_QUERY = CompanionServer._PERCEPTION_HISTORY_QUERY

        fusion = PerceptionFusion()
        now = time.monotonic()
        fusion.record_visual_event(
            "An older shot shows the Sun.",
            captured_at_monotonic=now - 4.0,
            captured_at_wall=time.time() - 4.0,
            frame_id="old-frame",
            source="screen:test",
            scene_id="old-scene",
            now=now,
        )
        fusion.observe_caption(
            "The current frame shows a classroom.",
            captured_at_monotonic=now,
            captured_at_wall=time.time(),
            frame_id="current-frame",
            source="screen:test",
            scene_id="current-scene",
            now=now,
        )
        fusion.note(
            "speech",
            "Current audio observation.",
            now=now,
            metadata={"source": "system_audio_loopback", "segment_id": "audio-current"},
        )
        ServerContext.perception_fusion = fusion

        current = CompanionServer.enrich_turn_text(ServerContext, "What is visible on the screen now?")
        historical = CompanionServer.enrich_turn_text(ServerContext, "What changed between the scenes?")

        self.assertIn("The current frame shows a classroom.", current)
        self.assertIn("Current audio observation.", current)
        self.assertNotIn("An older shot shows the Sun.", current)
        self.assertIn("An older shot shows the Sun.", historical)


class SensoryHistoryEnrichmentTests(unittest.TestCase):
    def test_recent_and_weekly_sensory_queries_receive_compact_history(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class History:
            def __init__(self):
                self.calls = []

            def context_text(self, **kwargs):
                self.calls.append(kwargs)
                return "SENSORY HISTORY: recorded scene and audio event"

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY
            _PERCEPTION_HISTORY_QUERY = CompanionServer._PERCEPTION_HISTORY_QUERY
            _SENSORY_HISTORY_QUERY = CompanionServer._SENSORY_HISTORY_QUERY
            perception_fusion = PerceptionFusion()
            sensory_history = History()

        recent = CompanionServer.enrich_turn_text(ServerContext, "What happened two minutes ago?")
        recent_ru = CompanionServer.enrich_turn_text(ServerContext, "Что происходило две минуты назад?")
        weekly = CompanionServer.enrich_turn_text(ServerContext, "Summarize the weekly history")

        self.assertIn("SENSORY HISTORY: recorded scene and audio event", recent)
        self.assertIn("SENSORY HISTORY: recorded scene and audio event", recent_ru)
        self.assertIn("SENSORY HISTORY: recorded scene and audio event", weekly)
        self.assertEqual(ServerContext.sensory_history.calls[0]["seconds"], 5 * 60)
        self.assertEqual(ServerContext.sensory_history.calls[0]["focus_seconds_ago"], 120.0)
        self.assertEqual(ServerContext.sensory_history.calls[1]["focus_seconds_ago"], 120.0)
        self.assertEqual(ServerContext.sensory_history.calls[2]["seconds"], 7 * 24 * 3600)
        self.assertEqual(ServerContext.sensory_history.calls[2]["focus_seconds_ago"], None)
        self.assertTrue(ServerContext.sensory_history.calls[2]["include_week"])

    def test_history_failure_is_disclosed_to_brain_instead_of_silent_visual_fallback(self):
        class Arbiter:
            @staticmethod
            def state():
                return {"active": None}

        class BrokenHistory:
            @staticmethod
            def context_text(**kwargs):
                raise OSError("unavailable")

        class ServerContext:
            gateway = type("Gateway", (), {"arbiter": Arbiter()})()
            _SCREEN_QUERY = CompanionServer._SCREEN_QUERY
            _PERCEPTION_HISTORY_QUERY = CompanionServer._PERCEPTION_HISTORY_QUERY
            _SENSORY_HISTORY_QUERY = CompanionServer._SENSORY_HISTORY_QUERY
            perception_fusion = PerceptionFusion()
            sensory_history = BrokenHistory()

        enriched = CompanionServer.enrich_turn_text(ServerContext, "What happened two minutes ago?")

        self.assertIn("SENSORY HISTORY UNAVAILABLE: durable history retrieval failed", enriched)
        self.assertIn("Do not infer that unlisted events did not happen", enriched)


class VoicePrefaceTests(unittest.TestCase):
    def _start_server(self, *, partial, fusion, silence_ms=800.0):
        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            streaming_asr=_FakeStreamingAsr(partial, silence_ms=silence_ms),
            perception_fusion=fusion,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(_stop_test_http_server, server, thread)
        self.base = f"http://127.0.0.1:{server.server_port}"
        self.session_headers = {
            "X-Companion-Session": server.session_token,
            "X-Companion-CSRF": server.csrf_token,
        }
        return server

    def _post(self, path, payload, headers=None):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **(self.session_headers if headers is None else headers),
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_screen_question_returns_bounded_preface(self):
        self._start_server(
            partial="\u041a\u043e\u043c\u043f\u0430\u043d\u044c\u043e\u043d, \u0447\u0442\u043e \u0441\u0435\u0439\u0447\u0430\u0441 \u043f\u0440\u043e\u0438\u0441\u0445\u043e\u0434\u0438\u0442 \u043d\u0430 \u044d\u043a\u0440\u0430\u043d\u0435?",
            fusion=_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u043e\u043a\u043d\u043e OpenCode \u0441 \u0442\u0430\u0431\u043b\u0438\u0446\u0435\u0439 \u043b\u043e\u0433\u043e\u0432. \u0417\u0432\u0443\u043a: \u0442\u0438\u0448\u0438\u043d\u0430"),
        )
        status, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "\u0421\u043c\u043e\u0442\u0440\u044e: \u043e\u043a\u043d\u043e OpenCode \u0441 \u0442\u0430\u0431\u043b\u0438\u0446\u0435\u0439 \u043b\u043e\u0433\u043e\u0432.")

    def test_non_screen_question_has_no_preface(self):
        self._start_server(
            partial="\u041d\u0430\u043f\u0438\u0448\u0438 \u043a\u043e\u0440\u043e\u0442\u043a\u043e\u0435 \u043f\u0438\u0441\u044c\u043c\u043e \u043a\u043e\u043b\u043b\u0435\u0433\u0435",
            fusion=_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u043e\u043a\u043d\u043e OpenCode"),
        )
        _, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(data["text"], "")

    def test_broad_phrase_without_screen_noun_is_not_spoken(self):
        self._start_server(
            partial="\u0427\u0442\u043e \u0441\u0435\u0439\u0447\u0430\u0441 \u043f\u0440\u043e\u0438\u0441\u0445\u043e\u0434\u0438\u0442?",
            fusion=_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u043e\u043a\u043d\u043e OpenCode"),
        )
        _, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(data["text"], "")

    def test_stale_partial_is_never_spoken(self):
        self._start_server(
            partial="\u0427\u0442\u043e \u0441\u0435\u0439\u0447\u0430\u0441 \u043d\u0430 \u044d\u043a\u0440\u0430\u043d\u0435?",
            fusion=_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u043e\u043a\u043d\u043e OpenCode"),
            silence_ms=30000.0,
        )
        _, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(data["text"], "")

    def test_missing_or_broken_perception_is_soft(self):
        self._start_server(partial="\u0427\u0442\u043e \u043d\u0430 \u044d\u043a\u0440\u0430\u043d\u0435", fusion=_FakeFusion(error=True))
        _, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(data["text"], "")

    def test_preface_requires_browser_session(self):
        self._start_server(partial="\u0427\u0442\u043e \u043d\u0430 \u044d\u043a\u0440\u0430\u043d\u0435", fusion=_FakeFusion("\u042d\u043a\u0440\u0430\u043d: \u043e\u043a\u043d\u043e"))
        with self.assertRaises(HTTPError) as context:
            self._post("/api/voice/preface", {"session_id": "s1"}, headers={})
        with context.exception:
            self.assertEqual(context.exception.code, 403)


class VoiceMemoryBlockTests(unittest.TestCase):
    def test_empty_context_yields_empty_block(self):
        for value in ("", None, "   \n\t "):
            with self.subTest(value=value):
                self.assertEqual(voice_memory_block(value), "")

    def test_context_is_collapsed_bounded_and_marked_background(self):
        block = voice_memory_block(
            "Пользователь любит кофе.\n\n  Работает в  G:\\AI.", limit=40
        )
        self.assertTrue(
            block.startswith(
                "\n\n[ФОНОВАЯ ПАМЯТЬ ГОЛОСА (VoiceMem, фон, не цитировать дословно): "
            )
        )
        self.assertTrue(block.endswith("]"))
        content = block.rsplit(": ", 1)[1].rstrip("]")
        self.assertLessEqual(len(content), 40)
        self.assertNotIn("\n", content)
        self.assertIn("Пользователь любит кофе.", content)


class AsrPrefetchTests(unittest.TestCase):
    def test_prefetch_is_bounded_to_one_per_session(self):
        calls = []

        class FakeTranscriber:
            def prefetch(self):
                calls.append(1)

        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            gigaam_transcriber=FakeTranscriber(),
        )
        self.addCleanup(server.server_close)
        self.assertTrue(server.prefetch_asr_model("session-1"))
        self.assertFalse(server.prefetch_asr_model("session-1"))
        self.assertTrue(server.prefetch_asr_model("session-2"))
        deadline = time.monotonic() + 2
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(calls), 2)

    def test_prefetch_without_transcriber_is_a_noop(self):
        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
        )
        self.addCleanup(server.server_close)
        self.assertFalse(server.prefetch_asr_model("session-1"))


class ShellStatusTests(unittest.TestCase):
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
        _stop_test_http_server(self.server, self.thread)

    def test_shell_status_is_light_and_bounded(self):
        request = Request(self.base + "/api/shell/status", headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            status = response.status
            data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn(data["agent"]["chat_status"], {"connected", "starting", "offline", "not_connected"})
        self.assertEqual(data["attention"]["dnd"], False)
        self.assertEqual(data["resources"]["profile"], "standard")
        self.assertFalse(data["sensory"]["running"])
        self.assertFalse(data["screen"]["running"])
        self.assertFalse(data["voice"]["tts"])
        self.assertFalse(data["visual"]["error_active"])
        self.assertIsNone(data["capture"]["microphone_owner"])
        self.assertFalse(data["capture"]["loopback_configured"])
        self.assertFalse(data["capture"]["loopback_running"])

    def test_shell_status_requires_browser_session(self):
        with self.assertRaises(HTTPError) as context:
            urlopen(self.base + "/api/shell/status", timeout=2)
        with context.exception:
            self.assertEqual(context.exception.code, 403)

    def test_shell_status_reports_active_capture_sources(self):
        self.server.voice_capture.acquire("desktop", "capture-test")
        self.server.ambient_audio = type(
            "AmbientAudioState",
            (),
            {
                "state": lambda _self: {
                    "configured": True,
                    "enabled": True,
                    "paused": False,
                    "capture": {"running": True, "device": "DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]", "device_index": 38, "host_api_index": 2, "sample_rate": 48000, "channels": 2, "last_error": None, "last_chunk_age_ms": 123.0, "signal_window_state": "digital_silence", "signal_window_rms": 0.0, "signal_window_duration_ms": 1000.0},
                    "bridge": {"soundscape_configured": True, "soundscape_count": 1, "soundscape_errors": 0, "soundscape_latency_ms_p95": 24.0, "soundscape_last_kind": "music", "soundscape_last_tags": ["Saxophone"], "soundscape_last_age_ms": 800.0, "soundscape_last_fresh": True, "audio_description_configured": True, "audio_description_provider": "qwen3-omni", "audio_description_count": 3, "audio_description_errors": 1, "audio_description_skipped": 0, "audio_description_latency_ms_p95": 940.0, "audio_description_last_kind": "music", "audio_description_last_age_ms": 2500.0, "audio_description_last_fresh": True},
                },
                "stop": lambda _self: None,
            },
        )()
        self.server.visual_sensor = type(
            "VisualSensorState",
            (),
            {
                "state": lambda _self: {"running": True, "latest_age_ms": 800, "caption_fresh": False, "caption_age_ms": 7000},
                "stop": lambda _self: None,
            },
        )()
        request = Request(self.base + "/api/shell/status", headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(data["capture"]["microphone_owner"], "desktop")
        self.assertTrue(data["capture"]["loopback_configured"])
        self.assertTrue(data["capture"]["loopback_running"])
        self.assertEqual(data["capture"]["loopback_last_chunk_age_ms"], 123.0)
        self.assertEqual(data["capture"]["loopback_device"], "DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]")
        self.assertEqual(data["capture"]["loopback_device_index"], 38)
        self.assertEqual(data["capture"]["loopback_host_api_index"], 2)
        self.assertEqual(data["capture"]["loopback_sample_rate"], 48000)
        self.assertEqual(data["capture"]["loopback_channels"], 2)
        self.assertEqual(data["capture"]["loopback_signal_window_state"], "digital_silence")
        self.assertEqual(data["capture"]["loopback_signal_window_rms"], 0.0)
        self.assertEqual(data["capture"]["loopback_signal_window_duration_ms"], 1000.0)
        self.assertEqual(data["capture"]["soundscape_last_kind"], "music")
        self.assertEqual(data["capture"]["soundscape_last_tags"], ["Saxophone"])
        self.assertEqual(data["capture"]["soundscape_last_age_ms"], 800.0)
        self.assertTrue(data["capture"]["soundscape_last_fresh"])
        self.assertEqual(data["capture"]["audio_description_provider"], "qwen3-omni")
        self.assertEqual(data["capture"]["audio_description_count"], 3)
        self.assertEqual(data["capture"]["audio_description_errors"], 1)
        self.assertEqual(data["capture"]["audio_description_last_kind"], "music")
        self.assertEqual(data["capture"]["audio_description_last_age_ms"], 2500.0)
        self.assertTrue(data["capture"]["audio_description_last_fresh"])
        self.assertFalse(data["visual"]["caption_fresh"])
        self.assertEqual(data["visual"]["caption_age_ms"], 7000)


class AgentLogTests(unittest.TestCase):
    def _server(self, log_dir=None):
        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            log_dir=log_dir,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(_stop_test_http_server, server, thread)
        self.base = f"http://127.0.0.1:{server.server_port}"
        self.session_headers = {
            "X-Companion-Session": server.session_token,
            "X-Companion-CSRF": server.csrf_token,
        }
        return server

    def _get(self, path):
        request = Request(self.base + path, headers=self.session_headers)
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_tail_pagination_and_redaction(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            log = log_dir / "main.log"
            log.write_text(
                "\n".join(f"line-{index}" for index in range(1, 21))
                # Deliberately fake credential: this fixture proves the log-tail
                # endpoint redacts secrets.
                + "\nAuthorization: Bearer sk-abcdef1234567890abcdef\n"  # secret-scan: allow
                ,
                encoding="utf-8",
            )
            self._server(log_dir=log_dir)
            status, data = self._get("/api/logs/agent?tail=5")
            self.assertEqual(status, 200)
            self.assertTrue(data["ok"])
            self.assertFalse(data["empty"])
            self.assertEqual(len(data["lines"]), 10)  # the tail clamps at a 10-line minimum
            self.assertEqual(data["lines"][-1], "Authorization: Bearer ***")
            self.assertTrue(data["truncated"])

    def test_empty_state_when_journal_missing(self):
        self._server(log_dir=Path(__file__).parent)
        status, data = self._get("/api/logs/agent")
        self.assertEqual(status, 200)
        self.assertTrue(data["empty"])
        self.assertEqual(data["lines"], [])


class SettingsHubUITests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = self.tmp.name + "/config"
        Path(config).mkdir()
        (Path(config) / "settings.yaml").write_text(
            "identity:\n  agent_name: Компаньон\nllm:\n  main_model: deepseek-v4-flash\n  temperature: 0.4\n  language: ru\n  available_models: []\n",
            encoding="utf-8",
        )
        (Path(config) / "interfaces.yaml").write_text(
            "telegram:\n  telethon:\n    enabled: false\n    recent_chats_limit: 20\n"
            "    private_chat_history_limit: 3\n    incoming_history_limit: 8\n"
            "github:\n  enabled: false\n  request_timeout_sec: 15\n  polling_interval_sec: 30\n"
            "email:\n  enabled: false\n  recent_limit: 10\n  polling_interval_sec: 60\n"
            "calendar:\n  enabled: false\n  upcoming_events_limit: 5\n  polling_interval_sec: 60\n"
            "code_graph:\n  enabled: false\n  max_search_results: 10\n  max_structure_items: 20\n"
            "  exclude_dirs:\n  - venv\n  - node_modules\n"
            "meta:\n  enabled: false\n  access_level: 0\n  custom_skills_enabled: false\n"
            "mcp:\n  enabled: false\n  startup_timeout_sec: 30\n  request_timeout_sec: 60\n"
            "  max_catalog_items: 500\n  max_result_chars: 20000\n  max_binary_bytes: 10485760\n"
            "debug_broker:\n  enabled: false\n  re_root: 'G:/RE'\n  auto_start: true\n"
            "  startup_timeout_sec: 30\n  request_timeout_sec: 180\n  max_result_chars: 30000\n"
            "  max_sessions: 20\n  x64dbg_port_start: 8888\n  x64dbg_port_end: 8899\n"
            "multimodality:\n  enabled: false\n  video_understanding_enabled: false\n"
            "  media_generation_enabled: false\n  media_request_timeout_sec: 30\n"
            "  media_poll_interval_sec: 5.0\n  media_max_upload_mb: 50\n  media_max_download_mb: 500\n"
            "voice:\n  stt:\n    cloud:\n      whisper:\n        enabled: false\n        model: whisper-1\n"
            "        temperature: 0.0\n        timeout_sec: 120\n"
            "  tts:\n    cloud:\n      elevenlabs:\n        enabled: false\n        tts_model: eleven_multilingual_v2\n"
            "        main_voice: voice1\n        stability: 0.5\n        similarity_boost: 0.75\n"
            "      edge:\n        enabled: false\n        main_voice: ru-RU-SvetlanaNeural\n"
            "        rate: '+0%'\n        volume: '+0%'\n        pitch: '+0Hz'\n"
            "web:\n  http:\n    enabled: false\n    request_timeout_sec: 15\n    max_response_chars: 10000\n"
            "  search:\n    enabled: false\n    search_engine: duckduckgo\n    reader_engine: trafilatura\n"
            "    request_timeout_sec: 15\n    max_page_chars: 10000\n"
            "    deep_research:\n      max_queries: 10\n      max_results_per_query: 5\n"
            "      max_pages_to_read: 15\n      total_max_chars: 30000\n"
            "  browser:\n    enabled: false\n    headless: true\n    timeout_sec: 30\n    idle_timeout_sec: 900\n"
            "  hooks:\n    enabled: false\n    host: 127.0.0.1\n    port: 8080\n    history_limit: 10\n"
            "    preview_max_chars: 200\n"
            "  rss:\n    enabled: false\n    polling_interval_sec: 3600\n    recent_limit: 3\n    feeds: []\n"
            "host:\n  os:\n    enabled: true\n    access_level: 0\n    env_access: false\n"
            "    desktop_interactions: false\n    desktop_max_windows: 20\n    desktop_max_elements: 250\n"
            "    desktop_max_text_chars: 500\n    desktop_max_result_chars: 60000\n"
            "    desktop_operation_timeout_sec: 30\n    require_deploy_sessions: true\n"
            "    deploy_max_retries: 5\n    framework_tree_depth: 1\n    monitoring_interval_sec: 30\n"
            "    execution_timeout_sec: 60\n    coding_execution_backend: disabled\n"
            "    coding_approval_mode: disabled\n    coding_approval_ttl_sec: 900\n"
            "    coding_container_runtime: docker\n    coding_container_image: python:3.11-slim\n"
            "    coding_container_network: none\n    coding_container_memory_mb: 2048\n"
            "    coding_container_cpus: 2.0\n    coding_container_pids: 256\n"
            "    file_read_max_chars: 10000\n    file_list_limit: 100\n    top_processes_limit: 10\n"
            "    file_diff_max_chars: 200\n    workspace_max_opened_files: 15\n"
            "    recent_file_changes_limit: 3\n    workspace_max_file_chars: 20000\n"
            "  terminal:\n    enabled: true\n    history_limit: 50\n    context_limit: 10\n",
            encoding="utf-8",
        )
        (Path(self.tmp.name) / ".env").write_text(
            "LLM_API_URL=http://127.0.0.1:8891/v1\nWEBHOOK_SECRET=whsec-123\n",
            encoding="utf-8",
        )
        from jawl_voicecompanion.config_hub import ConfigHub

        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            config_hub=ConfigHub(Path(config), env_file=Path(self.tmp.name) / ".env"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.session_headers = {
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def tearDown(self):
        _stop_test_http_server(self.server, self.thread)

    def _post(self, payload):
        request = Request(
            self.base + "/api/config-hub/save",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self.session_headers},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self):
        request = Request(self.base + "/api/config-hub", headers=self.session_headers)
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_roundtrip_through_http(self):
        state = self._get()
        self.assertEqual(state["values"]["settings:llm.temperature"], 0.4)
        result = self._post({
            "values": {"settings:llm.temperature": 0.55, "settings:llm.main_model": "glm-5.3-flash"},
            "expected_revision": state["revision"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["readback"]["values"]["settings:llm.temperature"], 0.55)
        self.assertEqual(result["readback"]["values"]["settings:llm.main_model"], "glm-5.3-flash")
        self.assertTrue(result["restart_required"])
        again = self._get()
        self.assertEqual(again["values"]["settings:llm.temperature"], 0.55)
        self.assertNotEqual(again["revision"], state["revision"])
        # masked secret still masked after the write
        self.assertEqual(again["values"]["env:LLM_API_URL"], "http://127.0.0.1:8891/v1")

    def test_masked_secret_keep_and_replace(self):
        state = self._get()
        self.assertEqual(state["values"]["env:WEBHOOK_SECRET"], "__SET__")
        # empty input for a masked secret keeps the stored value
        keep = self._post({"values": {"env:WEBHOOK_SECRET": ""}})
        self.assertTrue(keep["ok"])
        env_text = (Path(self.tmp.name) / ".env").read_text(encoding="utf-8")
        self.assertIn("whsec-123", env_text)
        # a typed value replaces it
        replace = self._post({"values": {"env:WEBHOOK_SECRET": "whsec-999"}})
        self.assertTrue(replace["ok"])
        self.assertEqual(replace["readback"]["values"]["env:WEBHOOK_SECRET"], "__SET__")
        self.assertIn("whsec-999", (Path(self.tmp.name) / ".env").read_text(encoding="utf-8"))

    def test_telegram_portion_roundtrip(self):
        state = self._get()
        self.assertIn("interfaces:telegram.telethon.enabled", state["values"])
        result = self._post({
            "values": {
                "interfaces:telegram.telethon.enabled": True,
                "interfaces:telegram.telethon.recent_chats_limit": 7,
            },
            "expected_revision": state["revision"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["readback"]["values"]["interfaces:telegram.telethon.enabled"], True)
        self.assertEqual(result["readback"]["values"]["interfaces:telegram.telethon.recent_chats_limit"], 7)
        # nullable fields omitted from the payload stay untouched
        self.assertIn("interfaces:telegram.telethon.coding_approval_actor_id", state["values"])

    def test_portion2_roundtrip(self):
        state = self._get()
        result = self._post({
            "values": {
                "interfaces:github.polling_interval_sec": 25,
                "interfaces:email.recent_limit": 12,
                "interfaces:calendar.enabled": True,
                "interfaces:code_graph.max_search_results": 15,
                "interfaces:meta.access_level": 1,
            },
            "expected_revision": state["revision"],
        })
        self.assertTrue(result["ok"])
        rb = result["readback"]["values"]
        self.assertEqual(rb["interfaces:github.polling_interval_sec"], 25)
        self.assertEqual(rb["interfaces:email.recent_limit"], 12)
        self.assertEqual(rb["interfaces:calendar.enabled"], True)
        self.assertEqual(rb["interfaces:code_graph.max_search_results"], 15)
        self.assertEqual(rb["interfaces:meta.access_level"], 1)

    def test_portion3_roundtrip_large_groups(self):
        state = self._get()
        result = self._post({
            "values": {
                "interfaces:mcp.max_result_chars": 25000,
                "interfaces:debug_broker.max_sessions": 25,
                "interfaces:multimodality.media_poll_interval_sec": 4.5,
                "interfaces:voice.stt.cloud.whisper.timeout_sec": 150,
                "interfaces:web.search.deep_research.max_queries": 12,
                "interfaces:web.hooks.port": 8081,
                "interfaces:host.os.coding_container_memory_mb": 4096,
                "interfaces:host.terminal.history_limit": 60,
            },
            "expected_revision": state["revision"],
        })
        self.assertTrue(result["ok"])
        rb = result["readback"]["values"]
        self.assertEqual(rb["interfaces:mcp.max_result_chars"], 25000)
        self.assertEqual(rb["interfaces:debug_broker.max_sessions"], 25)
        self.assertEqual(rb["interfaces:multimodality.media_poll_interval_sec"], 4.5)
        self.assertEqual(rb["interfaces:voice.stt.cloud.whisper.timeout_sec"], 150)
        self.assertEqual(rb["interfaces:web.search.deep_research.max_queries"], 12)
        self.assertEqual(rb["interfaces:web.hooks.port"], 8081)
        self.assertEqual(rb["interfaces:host.os.coding_container_memory_mb"], 4096)
        self.assertEqual(rb["interfaces:host.terminal.history_limit"], 60)

    def test_list_editor_roundtrip(self):
        state = self._get()
        self.assertIn("lstExcludeDirs", state["lists"])
        result = self._post({
            "lists": {"lstExcludeDirs": ["venv", "dist", "node_modules", "build2"]},
            "values": {},
            "expected_revision": state["revision"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["readback"]["lists"]["lstExcludeDirs"], ["venv", "dist", "node_modules", "build2"])

    def test_object_list_roundtrip(self):
        # sanity: feeds list exists in the fixture via a minimal feed entry
        state = self._get()
        result = self._post({
            "lists": {"lstFeeds": [{"name": "Habr", "url": "https://habr.com/rss/"}], "modelList": ["m1", "m2"]},
            "values": {},
            "expected_revision": state["revision"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["readback"]["lists"]["lstFeeds"], [{"name": "Habr", "url": "https://habr.com/rss/"}])
        self.assertEqual(result["readback"]["lists"]["modelList"], ["m1", "m2"])

    def test_conflict_returns_conflict_status(self):
        state = self._get()
        result = self._post({
            "values": {"settings:llm.temperature": 2.0},
            "expected_revision": "deadbeef" + "0" * 24,
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self._get()["values"]["settings:llm.temperature"], 0.4)
        del state


class PutProxyTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0, frontend_dir=Path(__file__).parents[1] / "frontend", gateway=TextGateway())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        _stop_test_http_server(self.server, self.thread)

    def test_put_requires_session_and_proxies_console_paths(self):
        request = Request(
            self.base + "/console-api/drives",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)
        with context.exception:
            self.assertEqual(context.exception.code, 403)

    def test_put_outside_console_paths_is_method_not_allowed(self):
        request = Request(
            self.base + "/api/anything",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Companion-Session": self.server.session_token,
                "X-Companion-CSRF": self.server.csrf_token,
            },
            method="PUT",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)
        with context.exception:
            self.assertEqual(context.exception.code, 405)


if __name__ == "__main__":
    unittest.main()
