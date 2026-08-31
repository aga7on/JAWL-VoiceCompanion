import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.windows_ui import control_fingerprint  # noqa: E402


class FakeControl:
    Name = "Save"
    ClassName = "Button"
    ControlTypeName = "ButtonControl"
    AutomationId = "save-button"
    NativeWindowHandle = 123


class WindowsUIHelpersTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_same_semantic_control(self):
        self.assertEqual(control_fingerprint(FakeControl()), control_fingerprint(FakeControl()))

    def test_fingerprint_changes_when_target_changes(self):
        first = FakeControl()
        second = FakeControl()
        second.AutomationId = "other-button"
        self.assertNotEqual(control_fingerprint(first), control_fingerprint(second))


if __name__ == "__main__":
    unittest.main()

