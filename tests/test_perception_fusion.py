import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402


class PerceptionFusionTests(unittest.TestCase):
    def test_compose_merges_fresh_channels(self):
        fusion = PerceptionFusion()
        fusion.note("window", "Visual Studio Code - JAWL", now=100.0)
        fusion.note("music", "Музыка: A minor, 92 BPM", now=101.0)
        fusion.note("speech", "проверка связи", now=102.0)
        text = fusion.compose("открыт редактор кода", now=110.0)
        self.assertIn("Экран: открыт редактор кода", text)
        self.assertIn("Окно: Visual Studio Code - JAWL", text)
        self.assertIn("Звук: Музыка: A minor, 92 BPM", text)
        self.assertIn("Слышно: проверка связи", text)

    def test_compose_drops_expired_channels(self):
        fusion = PerceptionFusion()
        fusion.note("window", "старое окно", now=0.0)
        fusion.note("music", "старая музыка", now=0.0)
        text = fusion.compose("новый экран", now=400.0)
        self.assertIn("Экран: новый экран", text)
        self.assertNotIn("старое окно", text)
        self.assertNotIn("старая музыка", text)

    def test_compose_without_screen_uses_other_channels(self):
        fusion = PerceptionFusion()
        fusion.note("music", "тишина", now=10.0)
        self.assertEqual(fusion.compose("", now=11.0), "Звук: тишина")

    def test_state_reports_fresh_items(self):
        fusion = PerceptionFusion()
        fusion.note("window", "код", now=50.0)
        state = fusion.state(now=51.0)
        self.assertIn("window", state["fresh"])
        self.assertIn("код", state["fresh"]["window"]["text"])


if __name__ == "__main__":
    unittest.main()
