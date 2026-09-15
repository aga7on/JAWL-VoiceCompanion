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
    create_presentation_server,
    create_server,
    is_meaningful_transcript,
)


class MeaningfulTranscriptTests(unittest.TestCase):
    def test_rejects_asr_noise_artifacts(self):
        for junk in (
            "嗯嗯嗯。",
            "嗯嗯",
            "嗯",
            "嗯哼",
            "Transcribe the audio exactly as spoken.",
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
    def test_default_ports_keep_control_and_presentation_separate(self):
        self.assertEqual(inspect.signature(create_server).parameters["port"].default, 2367)
        self.assertEqual(inspect.signature(create_presentation_server).parameters["port"].default, 8766)

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

    def get_json_auth(self, path):
        request = Request(self.base + path, headers=self.session_headers)
        with urlopen(request, timeout=2) as response:
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
        self.assertRegex(health["runtime_instance_id"], r"^[0-9a-f]{32}$")
        _, second_health = self.get_json("/api/health")
        self.assertEqual(health["runtime_instance_id"], second_health["runtime_instance_id"])
        self.assertEqual(health["resources"]["profile"], "standard")
        with urlopen(self.base + "/", timeout=2) as response:
            frontend = response.read()
            self.assertIn(b"JAWL VoiceCompanion", frontend)
            self.assertIn(b"ambient-audio-toggle", frontend)
            self.assertIn(b"ambient-memory-enabled", frontend)
            self.assertIn(b"ambient-triage", frontend)
            self.assertIn(b"ambient-clear", frontend)
            self.assertIn(b"ambient-disable-erase", frontend)
            self.assertIn(b"quiet-hours", frontend)
            self.assertIn(b"unattended", frontend)
            self.assertIn(b"save-denylist", frontend)
            self.assertIn(b"/api/tts/cancel", frontend)
            self.assertIn(b"/api/tts/stream", frontend)
            self.assertIn(b"/api/ambient-audio/playback", frontend)
            self.assertIn(b"ReadableStream", frontend)
            self.assertIn(b"decodeAudioData", frontend)
            self.assertIn(b"/api/chat/stream", frontend)
            self.assertIn(b"streamChat", frontend)
            self.assertIn(b"pushSpeechDelta", frontend)
            self.assertIn(b"finishSpeechSession", frontend)
            self.assertIn(b"discard_deltas", frontend)
            self.assertIn(b"closest('.message')", frontend)
            self.assertIn(b"AbortController", frontend)
            self.assertIn(b"bargeInTriggered", frontend)
            self.assertIn(b"speechPlaybackActive", frontend)
            self.assertIn(b"(currentAudio || speechPlaybackActive)", frontend)
            self.assertIn(b"prefaceVoiceTurn", frontend)
            self.assertIn(b"speakProvisional", frontend)
            self.assertIn(b"/api/voice/preface", frontend)
            self.assertIn(b"runtime_instance_id", frontend)
            self.assertIn("Контур перезапущен; старое аудио остановлено.".encode("utf-8"), frontend)
            self.assertIn(b"hands-free", frontend)
            self.assertIn(b"updateVoiceVad", frontend)
            self.assertIn(b"mic-gate", frontend)
            self.assertIn(b"mic-calibrate", frontend)
            self.assertIn(b"passThroughMicGate", frontend)
            self.assertIn(b"autoGainControl: false", frontend)
            self.assertIn(b"requestAnimationFrame", frontend)
            self.assertIn(b"tts-voice", frontend)
            self.assertIn(b"tts-speed", frontend)
            self.assertIn(b"emotion", frontend)
            self.assertIn(b"/api/jawl/journal?limit=10", frontend)
            self.assertIn(b"jawl-journal", frontend)
            self.assertIn(b"voice: ttsVoice.value.trim()", frontend)
            self.assertIn(b"Analyser", frontend)
            self.assertIn(b"/api/avatar/audio", frontend)
            self.assertIn(b"dispatchLocalSlashCommand", frontend)
            self.assertIn(b"/goal", frontend)
            self.assertIn(b"/tab home|voice|perception|memory|access|system", frontend)
            self.assertIn(b"/api/hostos/approvals/", frontend)
            self.assertIn(b"/execute", frontend)
            self.assertIn("Выполнить предложение".encode("utf-8"), frontend)
        with urlopen(self.base + "/avatar?source=obs", timeout=2) as response:
            self.assertIn(b"JAWL Avatar", response.read())
        with urlopen(self.base + "/mic-processor.js", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"AudioWorkletProcessor", response.read())
        vision_script = (Path(__file__).parents[1] / "scripts" / "run_vision_server.ps1").read_bytes()
        asr_script = (Path(__file__).parents[1] / "scripts" / "run_asr_server.ps1").read_bytes()
        self.assertIn(b"VLM-RealTime-Bench\\runtime\\llama-b10738-cpu", vision_script)
        self.assertIn(b"VLM-RealTime-Bench\\models\\Qwen3-VL-2B", vision_script)
        self.assertIn(b"VLM-RealTime-Bench\\runtime\\llama-b10738-cpu", asr_script)
        self.assertIn(b"VLM-RealTime-Bench\\models\\qwen3-asr", asr_script)

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
        self.server.ambient_memory.ingest_system_audio(
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
            body = json.loads(context.exception.read().decode("utf-8"))
            self.assertEqual(context.exception.code, 503)
            self.assertFalse(body["ok"])
            self.assertTrue(body["policy"]["emergency_stop"])
            self.assertEqual(body["jawl_policy"]["status"], "offline")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

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
            bridge.shutdown()
            bridge.server_close()
            thread.join(timeout=2)

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


class PresentationWebTests(unittest.TestCase):
    def setUp(self):
        self.control = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            legacy_presentation=False,
        )
        self.presentation = create_presentation_server(self.control, port=0)
        self.control_thread = threading.Thread(target=self.control.serve_forever, daemon=True)
        self.presentation_thread = threading.Thread(target=self.presentation.serve_forever, daemon=True)
        self.control_thread.start()
        self.presentation_thread.start()
        self.base = f"http://127.0.0.1:{self.presentation.server_port}"

    def tearDown(self):
        self.presentation.shutdown()
        self.presentation.server_close()
        self.control.shutdown()
        self.control.server_close()
        self.presentation_thread.join(timeout=2)
        self.control_thread.join(timeout=2)

    def test_presentation_origin_has_only_bounded_read_only_state(self):
        with urlopen(self.base + "/api/presentation/state", timeout=2) as response:
            state = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            # The avatar page is the OBS source and may be embedded only by
            # loopback control origins; framing stays denied everywhere else.
            self.assertIn(
                "frame-ancestors http://127.0.0.1:* http://localhost:*",
                response.headers["Content-Security-Policy"],
            )
            self.assertNotIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(state["schema_version"], 1)
        self.assertIn("avatar", state)
        self.assertIn("subtitle", state)
        self.assertIn("avatar_audio", state)
        for secret_field in ("session_token", "csrf_token", "policy", "last_turn", "recent_turns"):
            self.assertNotIn(secret_field, state)

    def test_control_origin_denies_frame_ancestors(self):
        with urlopen(f"http://127.0.0.1:{self.control.server_port}/", timeout=2) as response:
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_presentation_origin_serves_avatar_but_cannot_mutate_control(self):
        with urlopen(self.base + "/avatar", timeout=2) as response:
            self.assertIn(b"JAWL Avatar", response.read())
        request = Request(
            self.base + "/api/presentation/state",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 405)
        context.exception.close()
        with self.assertRaises(HTTPError) as context:
            urlopen(f"http://127.0.0.1:{self.control.server_port}/avatar", timeout=2)
        self.assertEqual(context.exception.code, 404)
        context.exception.close()

    def test_remote_presentation_origin_requires_its_read_only_token(self):
        # Use the loopback test server but force the same handler policy as a
        # remote TLS bind; this avoids generating certificates in the unit
        # suite while exercising the actual authorization boundary.
        self.presentation.remote_access = True
        self.presentation.presentation_access_token = "presentation-test-token"
        with self.assertRaises(HTTPError) as context:
            urlopen(self.base + "/api/presentation/state", timeout=2)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        with urlopen(
            self.base + "/api/presentation/state?token=presentation-test-token",
            timeout=2,
        ) as response:
            state = json.loads(response.read().decode("utf-8"))
        self.assertEqual(state["schema_version"], 1)
        with urlopen(
            self.base + "/avatar?token=presentation-test-token",
            timeout=2,
        ) as response:
            self.assertIn(b"JAWL Avatar", response.read())

    def test_http_servers_reject_non_loopback_binds(self):
        with self.assertRaises(ValueError):
            create_server(host="0.0.0.0", port=0, gateway=TextGateway())
        with self.assertRaises(ValueError):
            create_presentation_server(self.control, host="0.0.0.0", port=0)

class _FakeStreamingAsr:
    def __init__(self, text="", active=True):
        self.text = text
        self.active = active

    def snapshot(self):
        return {"active": self.active, "text": self.text, "silence_ms": 800}


class _FakeFusion:
    def __init__(self, line="", *, error=False):
        self.line = line
        self.error = error

    def compose(self):
        if self.error:
            raise RuntimeError("fusion offline")
        return self.line


class VoicePrefaceTests(unittest.TestCase):
    def _start_server(self, *, partial, fusion):
        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            streaming_asr=_FakeStreamingAsr(partial),
            perception_fusion=fusion,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
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
            partial="Компаньон, что сейчас происходит на экране?",
            fusion=_FakeFusion("Экран: окно OpenCode с таблицей логов. Звук: тишина"),
        )
        status, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "Смотрю: окно OpenCode с таблицей логов.")

    def test_non_screen_question_has_no_preface(self):
        self._start_server(
            partial="Напиши короткое письмо коллеге",
            fusion=_FakeFusion("Экран: окно OpenCode"),
        )
        _, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(data["text"], "")

    def test_missing_or_broken_perception_is_soft(self):
        self._start_server(partial="что на экране", fusion=_FakeFusion(error=True))
        _, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(data["text"], "")

    def test_preface_requires_browser_session(self):
        self._start_server(partial="что на экране", fusion=_FakeFusion("Экран: окно"))
        with self.assertRaises(HTTPError) as context:
            self._post("/api/voice/preface", {"session_id": "s1"}, headers={})
        self.assertEqual(context.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
