import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
NAMESPACE_SPEC = importlib.util.spec_from_file_location(
    "run_native_namespace_profile", ROOT / "scripts" / "run_native_namespace_profile.py"
)
NAMESPACE_MODULE = importlib.util.module_from_spec(NAMESPACE_SPEC)
assert NAMESPACE_SPEC.loader is not None
sys.modules[NAMESPACE_SPEC.name] = NAMESPACE_MODULE
NAMESPACE_SPEC.loader.exec_module(NAMESPACE_MODULE)

ACTION_SPEC = importlib.util.spec_from_file_location(
    "run_native_action_profile", ROOT / "scripts" / "run_native_action_profile.py"
)
ACTION_MODULE = importlib.util.module_from_spec(ACTION_SPEC)
assert ACTION_SPEC.loader is not None
sys.modules[ACTION_SPEC.name] = ACTION_MODULE
ACTION_SPEC.loader.exec_module(ACTION_MODULE)


class NativeActionProfileUnitTests(unittest.TestCase):
    def test_marker_must_be_new_and_inside_sandbox(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "nested" / "marker.txt"
            marker.parent.mkdir()
            marker.write_text("existing", encoding="utf-8")
            with self.assertRaises(ACTION_MODULE.ProfileFailure):
                ACTION_MODULE._validate_paths(marker, root)
            marker.unlink()
            with self.assertRaises(ACTION_MODULE.ProfileFailure):
                ACTION_MODULE._validate_paths(marker, root)
            marker.parent.rmdir()
            self.assertEqual(ACTION_MODULE._validate_paths(marker, root), marker.parent)
            outside = root.parent / "outside-marker.txt"
            with self.assertRaises(ValueError):
                outside.relative_to(root)
            with self.assertRaises(ACTION_MODULE.ProfileFailure):
                ACTION_MODULE._validate_paths(outside, root)

    def test_native_action_routes_are_hostos(self):
        for skill in (
            "HostOSWriter.write_file",
            "HostOSMetadata.set_file_description",
            "HostOSMonitoring.track_directory",
            "HostOSMonitoring.untrack_directory",
            "HostOSWriter.delete_file",
        ):
            self.assertEqual(NAMESPACE_MODULE._skill_route(skill), "/api/hostos/skill")


if __name__ == "__main__":
    unittest.main()
