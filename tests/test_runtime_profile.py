import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.runtime_profile import RuntimeProfile  # noqa: E402


def _profile():
    return {
        "schema_version": 1,
        "profile_id": "test-profile",
        "paths": {
            "config": "config", "data": "runtime/data", "logs": "runtime/logs",
            "cache": "runtime/cache", "sandbox": "runtime/sandbox",
        },
        "ports": {"control": 2367, "presentation": 8766, "reserved": [8765]},
        "components": {"jawl": {"enabled": False, "version": "pending"}},
        "consent": {
            "microphone": False, "system_audio": False, "screen": False,
            "unattended": False, "social_publish": False,
        },
    }


class RuntimeProfileTests(unittest.TestCase):
    def test_valid_profile_is_bounded_and_resolves_inside_root(self):
        profile = RuntimeProfile.from_mapping(_profile())
        with tempfile.TemporaryDirectory() as root:
            paths = profile.resolved_paths(Path(root))
            self.assertEqual(paths["sandbox"], (Path(root) / "runtime/sandbox").resolve())
        summary = profile.summary()
        self.assertNotIn("absolute", str(summary))
        self.assertEqual(summary["ports"], {"control": 2367, "presentation": 8766})

    def test_rejects_traversal_absolute_paths_and_port_collisions(self):
        for value in ("../outside", str(Path.cwd().anchor)):
            raw = _profile()
            raw["paths"]["data"] = value
            with self.assertRaises(ValueError):
                RuntimeProfile.from_mapping(raw)
        raw = _profile()
        raw["ports"]["control"] = 8765
        with self.assertRaises(ValueError):
            RuntimeProfile.from_mapping(raw)

    def test_rejects_unknown_and_secret_fields(self):
        raw = _profile()
        raw["unexpected"] = True
        with self.assertRaises(ValueError):
            RuntimeProfile.from_mapping(raw)
        raw = _profile()
        raw["components"]["jawl"]["api_key"] = "must-not-be-here"
        with self.assertRaises(ValueError):
            RuntimeProfile.from_mapping(raw)

    def test_loads_example_without_writing_or_starting_services(self):
        path = Path(__file__).parents[1] / "config" / "profile.example.json"
        profile = RuntimeProfile.load(path)
        self.assertEqual(profile.profile_id, "integrated-attended")
        self.assertFalse(profile.consent["unattended"])


if __name__ == "__main__":
    unittest.main()
