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
    def _report(self, gateway, *, live=False, configured=False, avatar=False):
        return build_doctor_report(
            gateway=gateway,
            hostos=SimpleNamespace(dry_run=not live),
            vision=SimpleNamespace(status=lambda: {
                "configured": configured, "screen_enabled": configured,
            }),
            voice_mem=_Provider("ready") if configured else None,
            tts=_Provider("ok") if configured else None,
            avatar_assets=SimpleNamespace(config=lambda: {"ready": avatar}) if avatar else None,
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
            live=True, configured=True, avatar=True,
        )
        self.assertEqual(report["status"], "degraded")
        checks = {item["id"]: item for item in report["checks"]}
        self.assertTrue(checks["jawl"]["ready"])
        self.assertTrue(checks["tts"]["ready"])
        self.assertEqual(checks["vision"]["status"], "configured")
        self.assertFalse(checks["vision"]["ready"])
        self.assertFalse(checks["asr"]["ready"])

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


    def test_configured_jawl_is_not_a_connected_chat(self):
        report = self._report(TextGateway(responder=_Responder("configured")))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["text_mode_available"])

    def test_provider_without_probe_or_with_negative_flags_is_not_ready(self):
        self.assertEqual(_health(object())["status"], "configured")
        for payload in ({"status": "ok", "ready": False}, {"status": "ready", "ok": "true"}, None):
            with self.subTest(payload=payload):
                self.assertEqual(_health(SimpleNamespace(health=lambda: payload))["status"], "degraded")

    def test_ambient_capture_must_be_running_without_error(self):
        for running, error, expected in ((True, None, True), (False, None, False), (True, "device_lost", False)):
            with self.subTest(running=running, error=error):
                report = build_doctor_report(
                    gateway=TextGateway(), hostos=SimpleNamespace(dry_run=True),
                    vision=SimpleNamespace(status=lambda: {}),
                    ambient_audio=SimpleNamespace(state=lambda: {
                        "configured": True, "capture": {"running": running, "last_error": error},
                    }),
                )
                check = next(item for item in report["checks"] if item["id"] == "ambient_audio")
                self.assertEqual(check["ready"], expected)


if __name__ == "__main__":
    unittest.main()
