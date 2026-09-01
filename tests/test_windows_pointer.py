import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.windows_pointer import WindowsPointerAdapter  # noqa: E402


class _PointerBackend:
    def __init__(self):
        self.calls = []
        self.last = None

    def perform(self, operation, x, y):
        self.calls.append((operation, x, y))
        self.last = (x, y)

    def position(self):
        return self.last


class WindowsPointerTests(unittest.TestCase):
    def setUp(self):
        self.backend = _PointerBackend()
        self.foreground = {
            "status": "verified",
            "class_name": "CanvasWindow",
            "bounds": [100, 200, 1100, 1000],
        }
        self.adapter = WindowsPointerAdapter(
            foreground_provider=lambda: self.foreground,
            pointer_backend=self.backend,
        )

    def test_image_coordinates_are_calibrated_against_fresh_window_bounds(self):
        result = self.adapter.act("click", {
            "coordinate_space": "image",
            "x": 250,
            "y": 200,
            "image_width": 500,
            "image_height": 400,
            "window_class": "CanvasWindow",
            "window_bounds": [100, 200, 1100, 1000],
        })
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(self.backend.calls, [("click", 601, 601)])
        self.assertEqual(result["postcondition"], {"name": "cursor_at_target", "verified": True})
        self.assertFalse(result["verified"])

    def test_stale_window_is_rejected_before_pointer_backend(self):
        result = self.adapter.act("click", {
            "coordinate_space": "image",
            "x": 10,
            "y": 10,
            "image_width": 500,
            "image_height": 400,
            "window_class": "CanvasWindow",
            "window_bounds": [0, 0, 1000, 800],
        })
        self.assertEqual(result, {"status": "stale_target", "reason": "foreground_window_bounds_changed"})
        self.assertEqual(self.backend.calls, [])

    def test_unsupported_and_out_of_frame_targets_fail_closed(self):
        unsupported = self.adapter.act("type", {"x": 1, "y": 1})
        outside = self.adapter.act("click", {
            "coordinate_space": "image",
            "x": 500,
            "y": 10,
            "image_width": 500,
            "image_height": 400,
            "window_bounds": [100, 200, 1100, 1000],
        })
        self.assertEqual(unsupported["status"], "denied")
        self.assertEqual(outside["status"], "denied")
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
