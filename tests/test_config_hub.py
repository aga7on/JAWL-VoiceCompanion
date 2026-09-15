import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.config_hub import ConfigHub  # noqa: E402


SETTINGS = """identity:
  agent_name: Компаньон
llm:
  main_model: deepseek-v4-flash
  temperature: 0.4
system:
  heartbeat_interval: 5.0
"""

INTERFACES = """web:
  enabled: true
  port: 8770
voice:
  enabled: true
"""

ENV = """LLM_API_URL=http://127.0.0.1:8891/v1
LLM_API_KEY_1=sk-secret-value
WEBHOOK_SECRET=whsec-123
"""


def _prepare(tmp: Path) -> Path:
    config = tmp / "config"
    config.mkdir()
    (config / "settings.yaml").write_text(SETTINGS, encoding="utf-8")
    (config / "interfaces.yaml").write_text(INTERFACES, encoding="utf-8")
    (tmp / ".env").write_text(ENV, encoding="utf-8")
    return config


class ConfigHubTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = _prepare(Path(self.tmp.name))
        self.hub = ConfigHub(self.config, env_file=Path(self.tmp.name) / ".env")

    def test_read_masks_secrets_and_reports_revision(self):
        state = self.hub.read()
        self.assertTrue(state["ok"])
        self.assertEqual(state["values"]["env:WEBHOOK_SECRET"], "__SET__")
        self.assertEqual(state["lists"]["keyList"], ["__SET__"])
        self.assertEqual(state["values"]["env:LLM_API_URL"], "http://127.0.0.1:8891/v1")
        self.assertTrue(state["revision"])
        self.assertNotIn("sk-secret-value", str(state))
        self.assertNotIn("whsec-123", str(state))

    def test_write_roundtrip_and_readback(self):
        before = self.hub.read()
        result = self.hub.write(
            {"values": {"settings:llm.temperature": 0.7}},
            expected_revision=before["revision"],
        )
        self.assertTrue(result["ok"])
        self.assertIn("settings.yaml", result["written"])
        self.assertEqual(result["readback"]["values"]["settings:llm.temperature"], 0.7)
        self.assertNotEqual(result["revision"], before["revision"])
        self.assertIn("0.7", (self.config / "settings.yaml").read_text(encoding="utf-8"))

    def test_revision_conflict_rejects_the_write(self):
        result = self.hub.write(
            {"values": {"settings:llm.temperature": 1.5}},
            expected_revision="0" * 32,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.hub.read()["values"]["settings:llm.temperature"], 0.4)

    def test_masked_secret_round_trips_untouched(self):
        result = self.hub.write(
            {
                "values": {
                    "env:WEBHOOK_SECRET": "__SET__",
                    "env:GITHUB_TOKEN": "gh-new-token",
                },
                "lists": {"keyList": ["__SET__"]},
            },
            expected_revision=self.hub.revision(),
        )
        self.assertTrue(result["ok"])
        env_text = (Path(self.tmp.name) / ".env").read_text(encoding="utf-8")
        self.assertIn("sk-secret-value", env_text)
        self.assertIn("whsec-123", env_text)
        self.assertIn("gh-new-token", env_text)

    def test_unknown_keys_are_reported_not_written(self):
        result = self.hub.write({"values": {"settings:nonexistent.key": 1}})
        self.assertTrue(result["ok"])
        self.assertIn("settings:nonexistent.key", result["unknown"])
        self.assertNotIn("nonexistent", (self.config / "settings.yaml").read_text(encoding="utf-8"))

    def test_presave_backups_rotate(self):
        self.hub.write({"values": {"settings:llm.temperature": 0.5}}, expected_revision=self.hub.revision())
        self.hub.write({"values": {"settings:llm.temperature": 0.6}}, expected_revision=self.hub.revision())
        first = self.config / "settings.yaml.pre-save-1.bak"
        second = self.config / "settings.yaml.pre-save-2.bak"
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertIn("0.5", first.read_text(encoding="utf-8"))
        self.assertIn("0.4", second.read_text(encoding="utf-8"))
        self.assertIn("0.6", (self.config / "settings.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
