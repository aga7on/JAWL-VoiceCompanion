import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.screen_adapter import (  # noqa: E402
    ScreenCaptureAdapter,
    issue_observation_token,
    verify_observation_token,
)


class ScreenCaptureAdapterTests(unittest.TestCase):
    def test_capture_profile_is_bounded_and_exposed_without_paths(self):
        adapter = ScreenCaptureAdapter(max_width=960, max_height=720, max_bytes=1_000_000)
        profile = adapter.profile()
        self.assertEqual(
            {key: profile[key] for key in ("max_width", "max_height", "max_bytes")},
            {"max_width": 960, "max_height": 720, "max_bytes": 1_000_000},
        )

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

    def test_observation_token_is_signed_bound_and_rejects_tampering(self):
        token = issue_observation_token(42, "Canvas", [1, 2, 3, 4], "a" * 64)
        claims = verify_observation_token(token)
        self.assertEqual(claims["hwnd"], 42)
        self.assertEqual(claims["digest"], "a" * 64)
        self.assertIsNone(verify_observation_token(token + "x"))

    def test_profile_exposes_ocr_and_redaction_capabilities(self):
        adapter = ScreenCaptureAdapter(
            ocr_enabled=True,
            redaction_rects=[(1, 2, 20, 30)],
        )
        self.assertTrue(adapter.profile()["ocr_enabled"])
        self.assertEqual(adapter.profile()["configured_redaction_rects"], 1)

    def test_ocr_provider_is_bounded_and_sensitive_text_is_identifiable(self):
        adapter = ScreenCaptureAdapter(
            ocr_enabled=True,
            ocr_provider=lambda _image: [
                {"text": "Password: secret", "bbox": [1, 2, 20, 30], "confidence": 98},
                {"text": "Button", "bbox": [30, 40, 50, 60], "confidence": 88},
                {"text": "invalid", "bbox": [1, 2, 2, 2]},
            ],
        )
        items = adapter._run_ocr(object())
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["bbox"], [1, 2, 20, 30])
        self.assertEqual(items[1]["confidence"], 88.0)
        self.assertTrue(any(term in items[0]["text"].casefold() for term in adapter.redaction_terms))

    def test_pixel_redaction_is_opaque_and_clipped(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is optional")
        image = Image.new("RGB", (10, 10), (255, 255, 255))
        ScreenCaptureAdapter._redact_pixels(image, [(-5, -5, 4, 4), (20, 20, 30, 30)])
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((5, 5)), (255, 255, 255))

    def test_ocr_inside_explicit_redaction_is_not_forwarded(self):
        adapter = ScreenCaptureAdapter(redaction_rects=[(0, 0, 20, 20)])
        self.assertTrue(
            adapter._ocr_item_is_redacted(
                {"text": "private text", "bbox": [5, 5, 10, 10]},
                adapter.redaction_rects,
            )
        )
        self.assertFalse(
            adapter._ocr_item_is_redacted(
                {"text": "visible", "bbox": [30, 30, 40, 40]},
                adapter.redaction_rects,
            )
        )


if __name__ == "__main__":
    unittest.main()
