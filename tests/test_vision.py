import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.vision import (  # noqa: E402
    JawlNativeVisionExecutor,
    OpenAICompatibleVisionClient,
    VisionActionPlan,
    VisionPlanError,
    VisionPlanExecutor,
    VisionLookService,
)
from jawl_voicecompanion.screen_adapter import issue_observation_token  # noqa: E402


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

    def test_openai_compatible_payload_accepts_transient_ocr_grounding(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return _Response({"choices": [{"message": {"content": "Вижу кнопку."}}]})

        client = OpenAICompatibleVisionClient("http://127.0.0.1:9000/v1", "local-vlm", opener=opener)
        client.describe(
            "Что видно?",
            {
                "image": {"media_type": "image/jpeg", "data_base64": "YWJj"},
                "ocr": [{"text": "Save", "bbox": [10, 20, 50, 40], "confidence": 91}],
            },
        )
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertIn("Transient OCR grounding", payload["messages"][1]["content"][1]["text"])
        self.assertIn("Save", payload["messages"][1]["content"][1]["text"])

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

    def test_structured_action_plan_requires_fresh_identity_and_postcondition(self):
        plan = VisionActionPlan.from_dict({
            "schema_version": 1,
            "observation_token": "token-" + "x" * 16,
            "observation_digest": "a" * 64,
            "actions": [{
                "operation": "click",
                "target": {"element_ref": "ref", "element_sha256": "b" * 64},
            }],
            "postcondition": {"name": "element_exists", "timeout_ms": 1000},
        })
        request = plan.tool_requests(session_id="s", turn_id="t")[0]
        self.assertEqual(request.tool, "desktop.act")
        self.assertEqual(request.target["observation_token"], "token-" + "x" * 16)
        self.assertTrue(request.idempotency_key.startswith("vision:"))
        with self.assertRaises(VisionPlanError):
            VisionActionPlan.from_dict({"schema_version": 1, "actions": []})

    def test_structured_action_plan_rejects_invalid_coordinates_and_tool_mismatch(self):
        base = {
            "schema_version": 1,
            "observation_token": "token-" + "x" * 16,
            "observation_digest": "a" * 64,
            "postcondition": {"name": "screen_changed", "timeout_ms": 1000},
        }
        with self.assertRaises(VisionPlanError):
            VisionActionPlan.from_dict({
                **base,
                "actions": [{"operation": "click", "target": {"x": float("nan"), "y": 1}}],
            })
        with self.assertRaises(VisionPlanError):
            VisionActionPlan.from_dict({
                **base,
                "actions": [{"operation": "set_value", "target": {"x": 1, "y": 1}, "value": "x"}],
            })
        with self.assertRaises(VisionPlanError):
            VisionActionPlan.from_dict({
                **base,
                "actions": [{"operation": "click", "target": {
                    "coordinate_space": "image", "x": 99, "y": 1,
                    "image_width": 10, "image_height": 10,
                }}],
            })

    def test_plan_executor_stops_on_unverified_dispatch(self):
        token = issue_observation_token(42, "Canvas", [0, 0, 100, 100], "a" * 64)
        payload = {
            "schema_version": 1,
            "observation_token": token,
            "observation_digest": "a" * 64,
            "actions": [{"operation": "click", "target": {"x": 10, "y": 20}}],
            "postcondition": {"name": "cursor_at_target", "timeout_ms": 1000},
        }

        class Host:
            def execute(self, request, has_approval=False):
                return {"status": "dispatched", "result": {"postcondition": {"verified": False}}}

        result = VisionPlanExecutor(Host()).execute(VisionActionPlan.from_dict(payload))
        self.assertEqual(result["status"], "postcondition_failed")
        self.assertEqual(result["failed_action"], 0)

    def test_plan_executor_requires_fresh_token_and_accepts_verified_adapter_result(self):
        token = issue_observation_token(42, "Canvas", [0, 0, 100, 100], "a" * 64)
        payload = {
            "schema_version": 1,
            "observation_token": token,
            "observation_digest": "a" * 64,
            "actions": [{"operation": "click", "target": {"x": 10, "y": 20}}],
            "postcondition": {"name": "cursor_at_target", "timeout_ms": 1000},
        }

        class Host:
            def execute(self, request, has_approval=False):
                return {
                    "status": "dispatched",
                    "result": {"postcondition": {"name": "cursor_at_target", "verified": True}},
                }

        result = VisionPlanExecutor(Host()).execute(VisionActionPlan.from_dict(payload))
        self.assertEqual(result["status"], "verified")

    def test_native_jawl_vision_executor_translates_verified_uia_action(self):
        class Adapter:
            def __init__(self):
                self.call = None

            def execute_hostos_skill(self, skill, arguments):
                self.call = (skill, arguments)
                return {"result": {
                    "is_success": True,
                    "message": json.dumps({
                        "verified": True,
                        "after": {"secret": "must-not-cross"},
                        "next_step": "x" * 1000,
                    }),
                }}

        token = issue_observation_token(42, "Canvas", [0, 0, 100, 100], "a" * 64)
        payload = {
            "schema_version": 1,
            "observation_token": token,
            "observation_digest": "a" * 64,
            "actions": [{
                "operation": "focus",
                "target": {"element_ref": "ref", "element_sha256": "b" * 64},
            }],
            "postcondition": {"name": "focused", "timeout_ms": 1000},
        }
        adapter = Adapter()
        result = VisionPlanExecutor(JawlNativeVisionExecutor(adapter)).execute(
            VisionActionPlan.from_dict(payload)
        )
        self.assertEqual(result["status"], "verified")
        self.assertNotIn("after", result["actions"][0]["result"])
        self.assertLessEqual(len(result["actions"][0]["result"]["next_step"]), 500)
        self.assertEqual(adapter.call[0], "HostOSDesktop.act_on_desktop_element")
        self.assertEqual(adapter.call[1]["action"], "focus")

    def test_native_jawl_vision_executor_maps_all_pointer_operations(self):
        expected = {
            "move": "HostOSDesktop.move_pointer",
            "click": "HostOSDesktop.click_coordinates",
            "double_click": "HostOSDesktop.double_click_coordinates",
            "right_click": "HostOSDesktop.right_click_coordinates",
            "middle_click": "HostOSDesktop.middle_click_coordinates",
        }

        class Adapter:
            def __init__(self):
                self.call = None

            def execute_hostos_skill(self, skill, arguments):
                self.call = (skill, arguments)
                return {"result": {
                    "is_success": True,
                    "message": json.dumps({"verified": True}),
                }}

        token = issue_observation_token(42, "Canvas", [0, 0, 100, 100], "a" * 64)
        for operation, skill_name in expected.items():
            adapter = Adapter()
            result = VisionPlanExecutor(JawlNativeVisionExecutor(adapter)).execute(
                VisionActionPlan.from_dict({
                    "schema_version": 1,
                    "observation_token": token,
                    "observation_digest": "a" * 64,
                    "actions": [{"operation": operation, "target": {"x": 10, "y": 20}}],
                    "postcondition": {"name": "cursor_at_target", "timeout_ms": 1000},
                })
            )
            self.assertEqual(result["status"], "verified")
            self.assertEqual(adapter.call[0], skill_name)
            self.assertEqual(adapter.call[1], {"x": 10, "y": 20})

    def test_plan_executor_rejects_token_digest_mismatch(self):
        token = issue_observation_token(42, "Canvas", [0, 0, 100, 100], "a" * 64)
        payload = {
            "schema_version": 1,
            "observation_token": token,
            "observation_digest": "b" * 64,
            "actions": [{"operation": "click", "target": {"x": 10, "y": 20}}],
            "postcondition": {"name": "screen_changed", "timeout_ms": 1000},
        }

        class Host:
            def execute(self, request, has_approval=False):
                raise AssertionError("stale vision plan must not reach HostOS")

        result = VisionPlanExecutor(Host()).execute(VisionActionPlan.from_dict(payload))
        self.assertEqual(result["status"], "stale_target")
        self.assertEqual(result["failed_action"], 0)

    def test_plan_executor_does_not_reuse_cursor_verification_for_other_condition(self):
        token = issue_observation_token(42, "Canvas", [0, 0, 100, 100], "a" * 64)
        payload = {
            "schema_version": 1,
            "observation_token": token,
            "observation_digest": "a" * 64,
            "actions": [{"operation": "click", "target": {"x": 10, "y": 20}}],
            "postcondition": {"name": "screen_changed", "timeout_ms": 1000},
        }

        class Host:
            def execute(self, request, has_approval=False):
                return {
                    "status": "dispatched",
                    "result": {
                        "verified": True,
                        "verification": "cursor_at_target",
                    },
                }

        result = VisionPlanExecutor(Host()).execute(VisionActionPlan.from_dict(payload))
        self.assertEqual(result["status"], "postcondition_failed")


if __name__ == "__main__":
    unittest.main()
