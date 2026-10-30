import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.windows_ocr import WindowsOcr  # noqa: E402


class WindowsOcrTests(unittest.TestCase):
    def test_parse_maps_line_boxes_and_ignores_duplicates(self):
        payload = {
            "ok": True,
            "lines": [
                {"text": "OCR CANVAS", "x": 10, "y": 20, "width": 100, "height": 30},
                {"text": "OCR CANVAS", "x": 11, "y": 21, "width": 100, "height": 30},
                {"text": "  ", "x": 1, "y": 1, "width": 10, "height": 10},
                {"text": "broken", "x": "x", "y": 0, "width": 10, "height": 10},
            ],
        }
        items = WindowsOcr._parse(json.dumps(payload))
        self.assertEqual(
            items,
            [
                {
                    "text": "OCR CANVAS",
                    "bbox": [10, 20, 110, 50],
                    "confidence": 90.0,
                }
            ],
        )

    def test_parse_rejects_missing_or_malformed_output(self):
        self.assertEqual(WindowsOcr._parse(""), [])
        self.assertEqual(WindowsOcr._parse("not json"), [])
        self.assertEqual(WindowsOcr._parse('{"ok": false}'), [])
        self.assertEqual(WindowsOcr._parse('{"ok": true, "lines": "nope"}'), [])

    def test_parse_keeps_only_the_first_64_lines(self):
        payload = {
            "ok": True,
            "lines": [
                {"text": f"line {index}", "x": 0, "y": index, "width": 10, "height": 1}
                for index in range(80)
            ],
        }
        self.assertEqual(len(WindowsOcr._parse(json.dumps(payload))), 64)


if __name__ == "__main__":
    unittest.main()
