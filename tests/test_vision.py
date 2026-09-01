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

    def test_openai_compatible_payload_contains_bounded_uia_context_as_data(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return _Response({"choices": [{"message": {"content": "Описание"}}]})

        client = OpenAICompatibleVisionClient("http://127.0.0.1:9000/v1", "local-vlm", opener=opener)
        client.describe(
            "Что видно?",
            {
                "image": {"media_type": "image/jpeg", "data_base64": "YWJj"},
                "uia": {
                    "status": "verified",
                    "elements": [{
                        "element_ref": "ref-1",
                        "element_sha256": "sha-1",
                        "name": "Save",
                        "class_name": "Button",
                        "control_type": "ButtonControl",
                        "automation_id": "save",
                        "depth": 1,
                    }],
                },
            },
        )
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertIn("UI Automation", payload["messages"][1]["content"][1]["text"])
        self.assertIn("ref-1", payload["messages"][1]["content"][1]["text"])

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

    def test_look_adds_uia_context_without_returning_it(self):
        class FakeHostOS:
            ui_automation = object()

            def execute(self, request):
                if request.tool == "screen.observe":
                    return {
                        "status": "verified",
                        "result": {
                            "image": {"media_type": "image/jpeg", "data_base64": "YWJj"},
                        },
                    }
                return {
                    "status": "verified",
                    "result": {
                        "status": "verified",
                        "elements": [{
                            "element_ref": "ref-1",
                            "element_sha256": "sha-1",
                            "name": "Save",
                            "class_name": "Button",
                            "control_type": "ButtonControl",
                            "automation_id": "save",
                            "depth": 1,
                        }],
                    },
                }

        class FakeDescriber:
            def describe(self, prompt, observation):
                self.observation = observation
                return "Вижу кнопку."

        describer = FakeDescriber()
        result = VisionLookService(FakeHostOS(), describer=describer).look("Что видно?")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(describer.observation["uia"]["elements"][0]["element_ref"], "ref-1")
        self.assertNotIn("uia", result)

    def test_changed_uia_context_is_not_deduplicated_with_same_frame(self):
        class FakeHostOS:
            ui_automation = object()
            calls = 0

            def execute(self, request):
                if request.tool == "screen.observe":
                    return {
                        "status": "verified",
                        "result": {"image": {"media_type": "image/jpeg", "data_base64": "YWJj"}},
                    }
                self.calls += 1
                return {
                    "status": "verified",
                    "result": {
                        "status": "verified",
                        "elements": [{
                            "element_ref": f"ref-{self.calls}",
                            "element_sha256": f"sha-{self.calls}",
                            "name": f"Button {self.calls}",
                            "class_name": "Button",
                            "control_type": "ButtonControl",
                            "automation_id": "button",
                            "depth": 1,
                        }],
                    },
                }

        class FakeDescriber:
            def __init__(self):
                self.calls = 0

            def describe(self, prompt, observation):
                self.calls += 1
                return observation["uia"]["elements"][0]["name"]

        describer = FakeDescriber()
        service = VisionLookService(FakeHostOS(), describer=describer)
        first = service.look("Что видно?", force=True)
        second = service.look("Что видно?", force=True)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(describer.calls, 2)

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
