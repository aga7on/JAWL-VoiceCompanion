import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
NAMESPACE_SPEC = importlib.util.spec_from_file_location(
    "run_native_namespace_profile", ROOT / "scripts" / "run_native_namespace_profile.py"
)
NAMESPACE_MODULE = importlib.util.module_from_spec(NAMESPACE_SPEC)
assert NAMESPACE_SPEC.loader is not None
sys.modules[NAMESPACE_SPEC.name] = NAMESPACE_MODULE
NAMESPACE_SPEC.loader.exec_module(NAMESPACE_MODULE)

MATRIX_SPEC = importlib.util.spec_from_file_location(
    "run_native_catalog_matrix", ROOT / "scripts" / "run_native_catalog_matrix.py"
)
MATRIX_MODULE = importlib.util.module_from_spec(MATRIX_SPEC)
assert MATRIX_SPEC.loader is not None
sys.modules[MATRIX_SPEC.name] = MATRIX_MODULE
MATRIX_SPEC.loader.exec_module(MATRIX_MODULE)


class NativeCatalogMatrixUnitTests(unittest.TestCase):
    def test_levels_are_bounded_and_non_empty(self):
        self.assertEqual(MATRIX_MODULE._parse_levels("0, 1,2,3"), (0, 1, 2, 3))
        with self.assertRaises(ValueError):
            MATRIX_MODULE._parse_levels("")
        with self.assertRaises(ValueError):
            MATRIX_MODULE._parse_levels("0,4")

    def test_level_summary_requires_catalog_policy_alignment(self):
        catalog = {
            "total": 3,
            "counts": {"HostOS": 1, "HostTerminal": 1, "DebugBroker": 1},
            "available": {"HostOS": 1, "HostTerminal": 1, "DebugBroker": 1},
            "skills": [
                {"name": "HostOS.reader", "required_access_level": 0, "available": True},
                {"name": "HostTerminalMessages.read", "required_access_level": None, "available": True},
                {"name": "DebugBroker.snapshot", "required_access_level": 1, "available": True},
            ],
        }
        with self.assertRaises(MATRIX_MODULE.ProfileFailure):
            MATRIX_MODULE._level_summary(0, {"access_name": "SANDBOX"}, catalog)
        catalog["skills"][2]["available"] = False
        summary = MATRIX_MODULE._level_summary(0, {"access_name": "SANDBOX"}, catalog)
        self.assertTrue(summary["availability_matches_required_level"])


if __name__ == "__main__":
    unittest.main()
