import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.vision import (  # noqa: E402
    OpenAICompatibleVisionClient,
    VisionLookService,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode("utf-8")


class VisionTests(unittest.TestCase):
    def test_openai_compatible_payload_contains_transient_image(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return _Response({"choices": [{"message": {"content": "На экране редактор."}}]})

        client = OpenAICompatibleVisionClient(
            "http://127.0.0.1:9000/v1",
            "local-vlm",
            opener=opener,
        )
        result = client.describe(
            "Что открыто?",
            {"image": {"media_type": "image/jpeg", "data_base64": "YWJj"}},
        )
        self.assertEqual(result, "На экране редактор.")
        request_payload = json.loads(requests[0][0].data.decode("utf-8"))
        user_content = request_payload["messages"][1]["content"]
        self.assertEqual(user_content[0]["text"], "Что открыто?")
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertIn("data:image/jpeg;base64,YWJj", user_content[1]["image_url"]["url"])

    def test_repeated_frame_is_not_sent_to_vlm_again(self):
        class FakeHostOS:
            def execute(self, request):
                return {
                    "status": "verified",
                    "result": {
                        "image": {"media_type": "image/jpeg", "data_base64": "YWJj"},
                    },
                }

        class FakeDescriber:
            calls = 0

            def describe(self, prompt, observation):
                self.calls += 1
                if prompt != "Что видно?":
                    raise AssertionError("unexpected vision prompt")
                return "Видно окно редактора."

        describer = FakeDescriber()
        service = VisionLookService(FakeHostOS(), describer=describer)
        first = service.look("Что видно?")
        second = service.look("Что видно?")
        forced = service.look("Что видно?", force=True)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(forced["status"], "ok")
        self.assertEqual(describer.calls, 2)
        self.assertNotIn("image", first)
        self.assertFalse(second["vlm_called"])

    def test_missing_describer_degrades_without_returning_image(self):
        class FakeHostOS:
            def execute(self, request):
                return {
                    "status": "verified",
                    "result": {
                        "image": {"media_type": "image/jpeg", "data_base64": "YWJj"},
                    },
                }

        result = VisionLookService(FakeHostOS()).look("Что видно?")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["reason"], "vision_describer_not_configured")
        self.assertNotIn("image", result)

    def test_status_exposes_bounded_capture_profile(self):
        class FakeScreen:
            enabled = True

            def profile(self):
                return {"max_width": 960, "max_height": 720, "max_bytes": 1_000_000}

        class FakeHostOS:
            dry_run = True
            screen_capture = FakeScreen()

        status = VisionLookService(FakeHostOS()).status()
        self.assertEqual(status["capture_profile"]["max_width"], 960)
        self.assertEqual(status["capture_profile"]["max_height"], 720)


if __name__ == "__main__":
    unittest.main()
