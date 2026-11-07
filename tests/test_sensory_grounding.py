"""Tests for Sensory Grounding & Anti-Hallucination defenses."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.perception_packet import make_packet  # noqa: E402


class SensoryGroundingTests(unittest.TestCase):
    def test_screen_and_ocr_channels_always_marked_as_hypotheses(self):
        fusion = PerceptionFusion()
        fusion.note("screen", "A person standing in front of complex machinery", now=100.0)
        fusion.note("ocr", "Terminal 42", now=100.0)
        state = fusion.state(now=101.0)
        
        screen_ch = state["fresh"]["screen"]
        self.assertTrue(screen_ch["hypothesis"])
        self.assertFalse(screen_ch["metadata"].get("verified"))

        ocr_ch = state["fresh"]["ocr"]
        self.assertTrue(ocr_ch["hypothesis"])
        self.assertFalse(ocr_ch["metadata"].get("verified"))

    def test_uncalibrated_music_and_audio_candidates_marked_as_hypotheses(self):
        fusion = PerceptionFusion()
        fusion.note(
            "music_candidate",
            "candidate match: electronic beat",
            now=100.0,
            metadata={"candidate_tags": ["hip-hop", "electronic"], "candidate_tags_calibrated": False},
        )
        fusion.note(
            "audio_event_candidates",
            "soundscape candidate: machinery hum",
            now=100.0,
            metadata={"confidence": 0.42, "source": "yamnet"},
        )
        state = fusion.state(now=101.0)
        
        music_ch = state["fresh"]["music_candidate"]
        self.assertTrue(music_ch["hypothesis"])
        
        event_ch = state["fresh"]["audio_event_candidates"]
        self.assertTrue(event_ch["hypothesis"])
        self.assertEqual(event_ch.get("confidence"), 0.42)
        self.assertIsNotNone(event_ch.get("provenance"))
        self.assertEqual(event_ch["provenance"]["source"], "yamnet")

    def test_verified_channel_retains_factual_status(self):
        fusion = PerceptionFusion()
        fusion.note("speech", "Hello world", now=100.0, metadata={"verified": True})
        state = fusion.state(now=101.0)
        
        speech_ch = state["fresh"]["speech"]
        self.assertFalse(speech_ch["hypothesis"])
        self.assertTrue(speech_ch["metadata"]["verified"])

    def test_make_packet_preserves_hypothesis_flags(self):
        fusion = PerceptionFusion()
        fusion.note("screen", "A humanoid figure", now=100.0)
        fusion.note("music_candidate", "ambient drone", now=100.0)
        snapshot = fusion.compose_snapshot(now=101.0)
        
        packet = make_packet(snapshot)
        channels = packet.get("channels", {})
        self.assertIn("screen", channels)
        self.assertTrue(channels["screen"].get("hypothesis"))
        self.assertIn("music_candidate", channels)
        self.assertTrue(channels["music_candidate"].get("hypothesis"))

    def test_system_prompt_contains_anti_hallucination_and_grounding_rules(self):
        prompt_path = REPO_ROOT / "config" / "jawl" / "prompts" / "custom" / "ZZ_SCREEN_COMMENTARY.md"
        self.assertTrue(prompt_path.exists())
        content = prompt_path.read_text(encoding="utf-8")
        
        self.assertIn("Sensory Grounding & Anti-Hallucination Rules", content)
        self.assertIn("[ГИПОТЕЗА / СЕНСОРНЫЕ ДАННЫЕ]", content)
        self.assertIn("Forbid Asserting Unverified Details", content)
        self.assertIn("Epistemic Calibration", content)
        self.assertIn("похоже на", content)

    def test_daily_profile_sync_has_zero_conflicts(self):
        script = REPO_ROOT / "scripts" / "prepare_daily_profile.py"
        res = subprocess.run(
            [sys.executable, str(script), "--sync"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Sync failed: {res.stderr}")
        self.assertIn("conflicts=0", res.stdout)


if __name__ == "__main__":
    unittest.main()
