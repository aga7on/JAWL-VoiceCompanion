import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.windows_keyboard import WindowsKeyboardAdapter  # noqa: E402


class _KeyboardBackend:
    def __init__(self):
        self.calls = []

    def type_text(self, text):
        self.calls.append(("type", text))

    def hotkey(self, keys):
        self.calls.append(("hotkey", keys))


class WindowsKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.backend = _KeyboardBackend()
        self.foreground = {
            "status": "verified",
            "class_name": "CanvasWindow",
            "bounds": [100, 200, 1100, 1000],
        }
        self.adapter = WindowsKeyboardAdapter(
            foreground_provider=lambda: self.foreground,
            keyboard_backend=self.backend,
        )

    def test_unicode_text_is_bounded_and_targets_fresh_foreground_window(self):
        result = self.adapter.act("type", {
            "text": "Привет, компаньон!",
            "window_class": "CanvasWindow",
            "window_bounds": [100, 200, 1100, 1000],
        })
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(self.backend.calls, [("type", "Привет, компаньон!")])
        self.assertTrue(result["postcondition"]["verified"])
        self.assertFalse(result["verified"])

    def test_hotkey_and_stale_target(self):
        result = self.adapter.act("hotkey", {
            "keys": ["ctrl", "shift", "p"],
            "window_class": "CanvasWindow",
        })
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(self.backend.calls, [("hotkey", [0x11, 0x10, 0x50])])
        self.foreground["class_name"] = "OtherWindow"
        stale = self.adapter.act("hotkey", {"keys": ["esc"], "window_class": "CanvasWindow"})
        self.assertEqual(stale, {"status": "stale_target", "reason": "foreground_window_changed"})

    def test_invalid_hotkey_and_oversized_text_fail_closed(self):
        bad_key = self.adapter.act("hotkey", {"keys": ["ctrl", "launch-missile"]})
        long_text = self.adapter.act("type", {"text": "x" * 4001})
        self.assertEqual(bad_key["status"], "denied")
        self.assertEqual(long_text["status"], "denied")
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
