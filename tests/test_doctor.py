import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.doctor import build_doctor_report, _health  # noqa: E402
from jawl_voicecompanion.gateway import TextGateway  # noqa: E402


class _Responder:
    def __init__(self, status):
        self._status = status

    def status(self):
        return self._status


class _Provider:
    def __init__(self, status):
        self._status = status

    def health(self):
        return {"status": self._status}


class DoctorTests(unittest.TestCase):
    def _report(self, gateway, *, live=False, configured=False):
        return build_doctor_report(
            gateway=gateway,
            hostos=SimpleNamespace(dry_run=not live),
            vision=SimpleNamespace(status=lambda: {
                "configured": configured, "screen_enabled": configured,
            }),
            voice_mem=_Provider("ready") if configured else None,
            tts=_Provider("ok") if configured else None,
            resource_governor=SimpleNamespace(state=lambda: {"profile": "standard", "gaming_mode": False}),
        )

    def test_mock_mode_is_explicit_but_text_mode_remains_available(self):
        report = self._report(TextGateway())
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(report["status"], "degraded")
        self.assertTrue(report["text_mode_available"])
        self.assertEqual(checks["jawl"]["status"], "mock")
        self.assertFalse(checks["jawl"]["required"])

    def test_configuration_does_not_prove_vision_or_missing_asr_ready(self):
        report = self._report(
            TextGateway(responder=_Responder("connected"), brain_name="jawl_web_chat"),
            live=True, configured=True,
        )
        self.assertEqual(report["status"], "degraded")
        checks = {item["id"]: item for item in report["checks"]}
        self.assertTrue(checks["jawl"]["ready"])
        self.assertTrue(checks["tts"]["ready"])
        self.assertEqual(checks["vision"]["status"], "configured")
        self.assertFalse(checks["vision"]["ready"])
        self.assertFalse(checks["asr"]["ready"])

    def test_live_qwen_visual_sensor_reports_ready_only_with_fresh_delivery(self):
        gateway = TextGateway(responder=_Responder("connected"), brain_name="jawl_web_chat")
        base = {
            "running": True, "captures": 10, "delivered": 8,
            "caption_fresh": True, "last_error": None,
        }
        report = build_doctor_report(
            gateway=gateway,
            hostos=SimpleNamespace(dry_run=True),
            vision=SimpleNamespace(status=lambda: {"configured": True, "screen_enabled": True}),
            visual_sensor=SimpleNamespace(state=lambda: dict(base)),
        )
        check = next(item for item in report["checks"] if item["id"] == "vision")
        self.assertEqual(check["status"], "online")
        self.assertTrue(check["ready"])

        base["caption_fresh"] = False
        report = build_doctor_report(
            gateway=gateway,
            hostos=SimpleNamespace(dry_run=True),
            vision=SimpleNamespace(status=lambda: {"configured": True, "screen_enabled": True}),
            visual_sensor=SimpleNamespace(state=lambda: dict(base)),
        )
        check = next(item for item in report["checks"] if item["id"] == "vision")
        self.assertEqual(check["status"], "degraded")
        self.assertFalse(check["ready"])

    def test_required_offline_jawl_blocks_report(self):
        report = self._report(
            TextGateway(responder=_Responder("offline"), brain_name="jawl_web_chat")
        )
        self.assertEqual(report["status"], "blocked")
        jawl = next(item for item in report["checks"] if item["id"] == "jawl")
        self.assertTrue(jawl["required"])
        self.assertFalse(jawl["ready"])
        self.assertFalse(report["text_mode_available"])
        self.assertNotIn("G:\\", str(report))

    def test_ambient_readiness_is_visible_without_exposing_paths(self):
        report = build_doctor_report(
            gateway=TextGateway(),
            hostos=SimpleNamespace(dry_run=True),
            vision=SimpleNamespace(status=lambda: {"configured": False, "screen_enabled": False}),
            ambient_memory=SimpleNamespace(state=lambda: {"enabled": True, "observation_count": 2}),
            ambient_audio=SimpleNamespace(state=lambda: {"configured": True, "capture": {"running": False}}),
        )
        checks = {item["id"]: item for item in report["checks"]}
        self.assertTrue(checks["ambient_memory"]["ready"])
        self.assertFalse(checks["ambient_audio"]["ready"])
        self.assertEqual(checks["ambient_audio"]["status"], "configured")
        self.assertNotIn("G:\\", str(report))


    def test_optional_off_is_neutral_and_does_not_degrade_the_runtime(self):
        report = self._report(
            TextGateway(responder=_Responder("connected"), brain_name="jawl_web_chat"),
            live=False, configured=False,
        )
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(report["status"], "ready")
        self.assertEqual(checks["hostos"]["status"], "dry_run")
        self.assertEqual(checks["hostos"]["state"], "ok")
        self.assertTrue(checks["hostos"]["ready"])
        self.assertEqual(checks["vision"]["state"], "off")
        self.assertEqual(checks["tts"]["state"], "off")
        self.assertIn("vision", report["optional_off"])
        self.assertIn("tts", report["optional_off"])
        self.assertNotIn("Validate the selected Vision profile", report["recommendations"])

    def test_configured_jawl_is_not_a_connected_chat(self):
        report = self._report(TextGateway(responder=_Responder("configured")))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["text_mode_available"])

    def test_provider_without_probe_or_with_negative_flags_is_not_ready(self):
        self.assertEqual(_health(object())["status"], "configured")
        for payload in ({"status": "ok", "ready": False}, {"status": "ready", "ok": "true"}, None):
            with self.subTest(payload=payload):
                self.assertEqual(_health(SimpleNamespace(health=lambda: payload))["status"], "degraded")

    def test_doctor_uses_cached_voicemem_state_instead_of_blocking_health_rpc(self):
        class BusyVoiceMem:
            def state(self):
                return {"status": "running", "running": True, "ready": True, "last_request_ok": True}

            def health(self):
                raise AssertionError("doctor must not queue a VoiceMem health RPC")

        report = build_doctor_report(
            gateway=TextGateway(responder=_Responder("connected"), brain_name="jawl_web_chat"),
            hostos=SimpleNamespace(dry_run=True),
            vision=SimpleNamespace(status=lambda: {"configured": False, "screen_enabled": False}),
            voice_mem=BusyVoiceMem(),
        )
        check = next(item for item in report["checks"] if item["id"] == "voicemem")
        self.assertEqual(check["status"], "ready")
        self.assertTrue(check["ready"])

    def test_ambient_capture_must_be_running_without_error(self):
        for running, error, expected in ((True, None, True), (False, None, False), (True, "device_lost", False)):
            with self.subTest(running=running, error=error):
                report = build_doctor_report(
                    gateway=TextGateway(), hostos=SimpleNamespace(dry_run=True),
                    vision=SimpleNamespace(status=lambda: {}),
                    ambient_audio=SimpleNamespace(state=lambda: {
                        "configured": True,
                        "capture": {
                            "running": running, "last_error": error,
                            "consumer_chunks": 1, "last_consumer_chunk_age_ms": 100,
                        },
                    }),
                )
                check = next(item for item in report["checks"] if item["id"] == "ambient_audio")
                self.assertEqual(check["ready"], expected)

    def test_ambient_capture_running_without_pcm_is_not_reported_ready(self):
        report = build_doctor_report(
            gateway=TextGateway(), hostos=SimpleNamespace(dry_run=True),
            vision=SimpleNamespace(status=lambda: {}),
            ambient_audio=SimpleNamespace(state=lambda: {
                "configured": True,
                "capture": {"running": True, "consumer_chunks": 0, "last_consumer_chunk_age_ms": None},
            }),
        )
        check = next(item for item in report["checks"] if item["id"] == "ambient_audio")
        self.assertEqual(check["status"], "waiting_for_samples")
        self.assertFalse(check["ready"])


if __name__ == "__main__":
    unittest.main()
