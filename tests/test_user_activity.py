import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.user_activity import WindowsUserActivity  # noqa: E402


class _FakeActivityBackend:
    def idle_seconds(self):
        return 12.34

    def foreground_class(self):
        return "Chrome_WidgetWin_1"


class UserActivityTests(unittest.TestCase):
    def test_sample_is_bounded_and_does_not_need_windows_for_injected_backend(self):
        result = WindowsUserActivity(60, backend=_FakeActivityBackend()).sample()
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["user_active"])
        self.assertEqual(result["foreground_class"], "Chrome_WidgetWin_1")
        self.assertEqual(result["idle_seconds"], 12.3)

    def test_unavailable_platform_is_degraded(self):
        activity = WindowsUserActivity()
        activity.backend = None
        activity._load_error = "test_unavailable"
        result = activity.sample()
        self.assertEqual(result, {"status": "degraded", "reason": "test_unavailable"})


if __name__ == "__main__":
    unittest.main()
