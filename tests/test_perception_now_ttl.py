
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from jawl_voicecompanion.perception_fusion import PerceptionFusion

class NowTtlTests(unittest.TestCase):
    def test_old_media_is_history_not_current(self):
        fusion = PerceptionFusion()
        fusion.observe_media({"description": "old scene"}, modality="vision", summary="old scene", now=100.0)
        self.assertIn("old scene", fusion.compose(now=103.0))
        self.assertNotIn("old scene", fusion.compose(now=106.0))

    def test_current_state_reports_screen_expiry_without_refreshing_it(self):
        fusion = PerceptionFusion()
        fusion.observe_caption(
            "Earth",
            captured_at_monotonic=100.0,
            captured_at_wall=1_000_000.0,
            frame_id="frame-1",
            source="screen",
            scene_id="scene-1",
        )
        self.assertEqual(fusion.current_state("screen", now=104.0)["age_ms"], 4000.0)
        self.assertTrue(fusion.current_state("screen", now=104.0)["fresh"])
        fusion.compose(now=104.0)
        expired = fusion.current_state("screen", now=105.1)
        self.assertFalse(expired["fresh"])
        self.assertEqual(expired["age_ms"], 5100.0)
        self.assertEqual(expired["metadata"]["frame_id"], "frame-1")

if __name__ == "__main__":
    unittest.main()
