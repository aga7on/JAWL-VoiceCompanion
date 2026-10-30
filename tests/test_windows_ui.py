import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.windows_ui import control_fingerprint, _bounded_bounds  # noqa: E402


class FakeRect:
    left = 100
    top = 50
    right = 300
    bottom = 90


class FakeControl:
    Name = "Save"
    ClassName = "Button"
    ControlTypeName = "ButtonControl"
    AutomationId = "save-button"
    NativeWindowHandle = 123
    BoundingRectangle = FakeRect()


class BrokenBoundsControl(FakeControl):
    @property
    def BoundingRectangle(self):
        raise RuntimeError("detached")


class WindowsUIHelpersTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_same_semantic_control(self):
        self.assertEqual(control_fingerprint(FakeControl()), control_fingerprint(FakeControl()))

    def test_fingerprint_changes_when_target_changes(self):
        first = FakeControl()
        second = FakeControl()
        second.AutomationId = "other-button"
        self.assertNotEqual(control_fingerprint(first), control_fingerprint(second))

    def test_bounds_are_exposed_for_grounding(self):
        self.assertEqual(_bounded_bounds(FakeControl()), [100, 50, 300, 90])

    def test_missing_bounds_do_not_break_observation(self):
        self.assertIsNone(_bounded_bounds(BrokenBoundsControl()))


if __name__ == "__main__":
    unittest.main()

