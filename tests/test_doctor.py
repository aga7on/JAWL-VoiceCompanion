import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.doctor import build_doctor_report  # noqa: E402
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
        )

    def test_mock_mode_is_explicit_but_text_mode_remains_available(self):
        report = self._report(TextGateway())
        checks = {item["id"]: item for item in report["checks"]}
        self.assertEqual(report["status"], "degraded")
        self.assertTrue(report["text_mode_available"])
        self.assertEqual(checks["jawl"]["status"], "mock")
        self.assertFalse(checks["jawl"]["required"])

    def test_configured_dependencies_can_report_ready(self):
        report = self._report(
            TextGateway(responder=_Responder("connected"), brain_name="jawl_web_chat"),
            live=True, configured=True, avatar=True,
        )
        self.assertEqual(report["status"], "ready")
        self.assertTrue(all(item["ready"] for item in report["checks"]))

    def test_required_offline_jawl_blocks_report(self):
        report = self._report(
            TextGateway(responder=_Responder("offline"), brain_name="jawl_web_chat")
        )
        self.assertEqual(report["status"], "blocked")
        jawl = next(item for item in report["checks"] if item["id"] == "jawl")
        self.assertTrue(jawl["required"])
        self.assertFalse(jawl["ready"])
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
        self.assertTrue(checks["ambient_audio"]["ready"])
        self.assertNotIn("G:\\", str(report))


if __name__ == "__main__":
    unittest.main()
