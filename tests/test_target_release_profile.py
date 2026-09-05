import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]
NAMESPACE_SPEC = importlib.util.spec_from_file_location(
    "run_native_namespace_profile", ROOT / "scripts" / "run_native_namespace_profile.py"
)
NAMESPACE_MODULE = importlib.util.module_from_spec(NAMESPACE_SPEC)
assert NAMESPACE_SPEC.loader is not None
sys.modules[NAMESPACE_SPEC.name] = NAMESPACE_MODULE
NAMESPACE_SPEC.loader.exec_module(NAMESPACE_MODULE)

TARGET_SPEC = importlib.util.spec_from_file_location(
    "run_target_release_profile", ROOT / "scripts" / "run_target_release_profile.py"
)
TARGET_MODULE = importlib.util.module_from_spec(TARGET_SPEC)
assert TARGET_SPEC.loader is not None
sys.modules[TARGET_SPEC.name] = TARGET_MODULE
TARGET_SPEC.loader.exec_module(TARGET_MODULE)


class TargetReleaseProfileTests(unittest.TestCase):
    def test_dependency_parser_requires_name_and_loopback_url(self):
        self.assertEqual(
            TARGET_MODULE._dependency("asr=http://127.0.0.1:8984"),
            ("asr", "http://127.0.0.1:8984"),
        )
        with self.assertRaises(ValueError):
            TARGET_MODULE._dependency("http://127.0.0.1:8984")
        with self.assertRaises(ValueError):
            TARGET_MODULE._dependency("asr=http://example.com:8984")

    def test_presentation_forbidden_fields_are_explicit(self):
        self.assertIn("csrf_token", TARGET_MODULE.FORBIDDEN_PRESENTATION_FIELDS)
        self.assertIn("policy", TARGET_MODULE.FORBIDDEN_PRESENTATION_FIELDS)
        self.assertNotIn("subtitle", TARGET_MODULE.FORBIDDEN_PRESENTATION_FIELDS)

    def test_jawl_requirement_rejects_stopped_native_console(self):
        responses = [
            (200, {"ok": True, "running": False}),
            (200, {"ok": True, "native": True, "policy": {"access_level": 1}}),
        ]
        with mock.patch.object(TARGET_MODULE, "_request", side_effect=responses):
            with self.assertRaises(TARGET_MODULE.ProfileFailure):
                TARGET_MODULE._check_jawl("http://127.0.0.1:8773", "token", 1.0)

    def test_jawl_requirement_accepts_running_native_console(self):
        responses = [
            (200, {"ok": True, "running": True}),
            (
                200,
                {
                    "ok": True,
                    "native": True,
                    "policy": {"access_level": 1, "authority": "jawl"},
                },
            ),
        ]
        with mock.patch.object(TARGET_MODULE, "_request", side_effect=responses):
            result = TARGET_MODULE._check_jawl("http://127.0.0.1:8773", "token", 1.0)
        self.assertTrue(result["running"])
        self.assertTrue(result["native"])

    def test_dependency_requires_positive_noncontradictory_health(self):
        for payload in ({"status": "ok"}, {"ready": True}, {"ok": True, "status": "ready"}):
            with self.subTest(payload=payload):
                with mock.patch.object(TARGET_MODULE, "_request", return_value=(200, payload)):
                    self.assertTrue(TARGET_MODULE._check_required_dependency("tts", "http://127.0.0.1:1", 1)["ok"])
        for payload in (
            {}, {"configured": True}, {"status": "loading"}, {"status": "ok", "ready": False},
            {"ok": True, "status": "offline"}, {"ready": "true"}, {"ok": 1},
        ):
            with self.subTest(payload=payload):
                with mock.patch.object(TARGET_MODULE, "_request", return_value=(200, payload)):
                    with self.assertRaises(TARGET_MODULE.ProfileFailure):
                        TARGET_MODULE._check_required_dependency("tts", "http://127.0.0.1:1", 1)

    def test_dependency_rejects_error_http_even_with_ready_payload(self):
        with mock.patch.object(TARGET_MODULE, "_request", return_value=(503, {"status": "ok"})):
            with self.assertRaises(TARGET_MODULE.ProfileFailure):
                TARGET_MODULE._check_required_dependency("tts", "http://127.0.0.1:1", 1)

    def test_jawl_policy_must_report_success_and_canonical_authority(self):
        for overrides in (
            {"ok": False}, {"ok": "true"}, {"native": False},
            {"policy": {"authority": "companion", "access_level": 3}},
            {"policy": {"access_level": 3}},
            {"policy": {"authority": "jawl", "access_level": True}},
            {"policy": {"authority": "jawl", "access_level": 4}},
            {"policy": {"authority": "jawl", "access_level": "3"}},
        ):
            with self.subTest(overrides=overrides):
                payload = {"ok": True, "native": True, "policy": {"authority": "jawl", "access_level": 1}, **overrides}
                with mock.patch.object(TARGET_MODULE, "_request", side_effect=[
                    (200, {"ok": True, "running": True}), (200, payload),
                ]):
                    with self.assertRaises(TARGET_MODULE.ProfileFailure):
                        TARGET_MODULE._check_jawl("http://127.0.0.1:1", "", 1)


if __name__ == "__main__":
    unittest.main()
