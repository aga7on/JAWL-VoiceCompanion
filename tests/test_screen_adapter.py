import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402


class ScreenCaptureAdapterTests(unittest.TestCase):
    def test_capture_is_disabled_by_default(self):
        result = ScreenCaptureAdapter().observe()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["reason"], "screen_observation_disabled")
        self.assertFalse(result["persisted"])

    def test_metadata_only_request_does_not_capture(self):
        result = ScreenCaptureAdapter(enabled=True).observe(include_image=False)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["reason"], "metadata_only_screen_observation_not_implemented")
        self.assertNotIn("image", result)

    def test_sensitive_and_companion_titles_are_blocked(self):
        adapter = ScreenCaptureAdapter(enabled=True)
        self.assertTrue(adapter._is_blocked_window("Password manager", "Chrome_WidgetWin_1"))
        self.assertTrue(adapter._is_blocked_window("JAWL Avatar", "Chrome_WidgetWin_1"))
        self.assertFalse(adapter._is_blocked_window("Visual Studio Code", "Chrome_WidgetWin_1"))


if __name__ == "__main__":
    unittest.main()
