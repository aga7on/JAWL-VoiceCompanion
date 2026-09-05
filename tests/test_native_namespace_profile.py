import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_native_namespace_profile", ROOT / "scripts" / "run_native_namespace_profile.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NativeNamespaceProfileUnitTests(unittest.TestCase):
    def test_url_guard_rejects_remote_and_query_urls(self):
        with self.assertRaises(ValueError):
            MODULE._loopback_url("http://example.com:8773")
        with self.assertRaises(ValueError):
            MODULE._loopback_url("http://127.0.0.1:8773/?token=leak")
        self.assertEqual(
            MODULE._loopback_url("http://127.0.0.1:8773/"),
            "http://127.0.0.1:8773",
        )

    def test_catalog_validation_counts_all_native_namespaces(self):
        skills = []
        for prefix, count in (("HostOS", 2), ("HostTerminalMessages", 2), ("DebugBroker", 2)):
            for index in range(count):
                skills.append(
                    {
                        "name": f"{prefix}.skill_{index}",
                        "signature": "skill()",
                        "required_access_level": 1,
                        "available": index == 0,
                        "custom": False,
                    }
                )
        summary = MODULE._validate_catalog(
            {
                "ok": True,
                "native": True,
                "catalog": {"schema_version": 1, "prefixes": list(MODULE.NAMESPACE_PREFIXES), "skills": skills},
            }
        )
        self.assertEqual(summary["total"], 6)
        self.assertEqual(summary["counts"], {"HostOS": 2, "HostTerminal": 2, "DebugBroker": 2})
        self.assertEqual(summary["available"]["DebugBroker"], 1)

    def test_catalog_validation_rejects_duplicate_or_missing_namespace(self):
        entry = {
            "name": "HostOS.reader",
            "signature": "reader()",
            "required_access_level": 0,
            "available": True,
            "custom": False,
        }
        with self.assertRaises(MODULE.ProfileFailure):
            MODULE._validate_catalog(
                {"ok": True, "native": True, "catalog": {"schema_version": 1, "skills": [entry, entry]}}
            )

    def test_skill_route_keeps_debug_broker_on_its_native_route(self):
        self.assertEqual(MODULE._skill_route("DebugBroker.list_providers"), "/api/debug/skill")
        self.assertEqual(MODULE._skill_route("HostTerminalMessages.read_terminal_history"), "/api/hostos/skill")
        with self.assertRaises(ValueError):
            MODULE._skill_route("Companion.fake_skill")


if __name__ == "__main__":
    unittest.main()
