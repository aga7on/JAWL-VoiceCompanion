import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_native_policy_profile", ROOT / "scripts" / "run_native_policy_profile.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NativePolicyProfileUnitTests(unittest.TestCase):
    def test_url_guard_rejects_remote_and_query_urls(self):
        with self.assertRaises(ValueError):
            MODULE._loopback_url("http://example.com:8773")
        with self.assertRaises(ValueError):
            MODULE._loopback_url("http://127.0.0.1:8773/?token=leak")
        self.assertEqual(
            MODULE._loopback_url("http://127.0.0.1:8773/"),
            "http://127.0.0.1:8773",
        )

    def test_levels_are_bounded_and_non_empty(self):
        self.assertEqual(MODULE._parse_levels("0, 1,2,3"), (0, 1, 2, 3))
        with self.assertRaises(ValueError):
            MODULE._parse_levels("")
        with self.assertRaises(ValueError):
            MODULE._parse_levels("0,4")

    def test_early_failure_restores_initial_access_level(self):
        state = {"level": 3}
        set_levels = []
        policy_calls = [0]

        def fake_request(_base_url, path, **_kwargs):
            if path == "/api/agent/status":
                return 200, {"running": True, "starting": False, "stopping": False}
            if path == "/api/hostos/policy":
                policy_calls[0] += 1
                if policy_calls[0] == 1:
                    return 503, {}
                return 200, {
                    "native": True,
                    "policy": {
                        "access_level": state["level"],
                        "emergency_stop": {"active": False},
                        "unattended": {"enabled": False, "lease_present": False},
                    },
                }
            raise AssertionError(f"unexpected request: {path}")

        def fake_set_level(_base_url, *, token, level):
            del token
            state["level"] = level
            set_levels.append(level)
            return {"access_level": level}

        def fake_native_skill(_base_url, *, token, skill, arguments):
            del token
            if skill != "HostOSReader.read_file_range":
                raise AssertionError(f"unexpected skill: {skill}")
            is_sandbox = arguments["filepath"] == "sandbox-fixture.txt"
            return {"is_success": is_sandbox, "message": "probe"}

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "policy.json"
            argv = [
                "run_native_policy_profile.py",
                "--live",
                "--url",
                "http://127.0.0.1:8773",
                "--levels",
                "0,1",
                "--sandbox-path",
                "sandbox-fixture.txt",
                "--outside-read-path",
                "outside.txt",
                "--report",
                str(report_path),
            ]
            with mock.patch.object(MODULE, "_request", side_effect=fake_request), mock.patch.object(
                MODULE, "_set_level", side_effect=fake_set_level
            ), mock.patch.object(MODULE, "_native_skill", side_effect=fake_native_skill), mock.patch.object(
                sys, "argv", argv
            ):
                result = MODULE.main()

            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertEqual(set_levels, [0, 1, 3])
        self.assertEqual(report["initial_access_level"], 3)
        self.assertEqual(report["final_access_level"], 3)
        self.assertFalse(report["pass"])
        self.assertTrue(
            any(
                failure.startswith("policy expectation mismatch at level 1")
                for failure in report["failures"]
            )
        )


if __name__ == "__main__":
    unittest.main()
