import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from run_restart_soak import free_loopback_port, port_is_closed, request_json, run_profile  # noqa: E402


class RestartSoakTests(unittest.TestCase):
    def test_port_is_closed_rejects_unbound_port(self):
        port = free_loopback_port()
        self.assertTrue(port_is_closed(port))

    def test_request_json_rejects_non_object_payload(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps([1, 2, 3]).encode("utf-8")

        import run_restart_soak

        original = run_restart_soak.urlopen
        run_restart_soak.urlopen = lambda *_args, **_kwargs: Response()
        try:
            with self.assertRaises(ValueError):
                request_json("http://127.0.0.1:1", "/api/health", 0.1)
        finally:
            run_restart_soak.urlopen = original

    def test_profile_rejects_missing_runtime_without_writing_secrets(self):
        result = run_profile(SimpleNamespace(
            python=Path(sys.executable + ".missing"),
            cycles=1,
            probes=1,
            startup_timeout=0.2,
            shutdown_timeout=0.2,
        ))
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("token", json.dumps(result).casefold())


if __name__ == "__main__":
    unittest.main()
