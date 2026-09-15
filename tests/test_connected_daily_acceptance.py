import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from run_connected_daily_acceptance import jawl_health_ready, loopback_url  # noqa: E402


class ConnectedDailyAcceptanceTests(unittest.TestCase):
    def test_jawl_ready_allows_degraded_optional_adapters(self):
        self.assertTrue(
            jawl_health_ready(
                {
                    "status": "degraded",
                    "components": {
                        "jawl": "connected",
                        "jawl_web": "online",
                        "voicemem": "not_connected",
                        "tts": "not_connected",
                    },
                }
            )
        )

    def test_jawl_ready_requires_control_plane(self):
        self.assertFalse(
            jawl_health_ready(
                {"status": "degraded", "components": {"jawl": "offline", "jawl_web": "online"}}
            )
        )
        self.assertFalse(
            jawl_health_ready(
                {"status": "degraded", "components": {"jawl": "connected", "jawl_web": "offline"}}
            )
        )

    def test_loopback_url_rejects_remote_and_query(self):
        self.assertEqual(loopback_url("http://127.0.0.1:2407/"), "http://127.0.0.1:2407")
        with self.assertRaises(ValueError):
            loopback_url("https://example.invalid:2407")
        with self.assertRaises(ValueError):
            loopback_url("http://127.0.0.1:2407/?token=secret")


if __name__ == "__main__":
    unittest.main()
