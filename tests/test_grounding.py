import hashlib
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.grounding import (  # noqa: E402
    GroundingService,
    _text_score,
)
from jawl_voicecompanion.screen_adapter import issue_observation_token  # noqa: E402
from jawl_voicecompanion.vision import VisionActionPlan, VisionLookService  # noqa: E402

DIGEST = hashlib.sha256(b"frame").hexdigest()
WINDOW = [100, 50, 600, 450]


def _uia_element(name, bounds, *, ref="ref-1", control_type="ButtonControl"):
    return {
        "element_ref": ref,
        "element_sha256": "a" * 64,
        "name": name,
        "control_type": control_type,
        "bounds": bounds,
    }


class FakeUIA:
    def __init__(self, elements):
        self.elements = elements
        self.calls = 0

    def observe(self):
        self.calls += 1
        return {"status": "verified", "elements": self.elements}


class FakeScreen:
    def __init__(self, ocr, *, ttl_seconds=5.0, token=True, bounds=WINDOW):
        self.ocr = ocr
        self.ttl_seconds = ttl_seconds
        self.token = token
        self.bounds = bounds
        self.calls = 0

    def observe(self, include_image=True):
        self.calls += 1
        state = {
            "status": "verified",
            "observation_digest": DIGEST,
            "window": {"class_name": "TestWindow", "bounds": list(self.bounds)},
            "coordinate_scale": {"x": 1.0, "y": 1.0},
            "ocr": list(self.ocr),
        }
        if self.token:
            state["observation_token"] = issue_observation_token(
                1, "TestWindow", list(self.bounds), DIGEST, ttl_seconds=self.ttl_seconds
            )
        return state


class FakeHostOS:
    def __init__(self, uia, screen):
        self.ui_automation = uia
        self.screen_capture = screen
        self.requests = []

    def execute(self, request, has_approval=False):
        self.requests.append(request)
        return {
            "status": "verified",
            "result": {"postcondition": {"name": "action_result", "verified": True}},
        }


def service(uia=None, screen=None, **kwargs):
    return GroundingService(uia=uia, screen=screen, **kwargs)


class GroundingTests(unittest.TestCase):
    def test_observe_builds_uia_and_translated_ocr_candidates(self):
        screen = FakeScreen([{"text": "Отмена", "bbox": [10, 20, 60, 36], "confidence": 92.0}])
        state = service(screen=screen).observe()
        self.assertEqual(state["status"], "verified")
        by_source = {(c["source"], c["label"]): c for c in state["candidates"]}
        ocr = by_source[("ocr", "Отмена")]
        self.assertEqual(ocr["bbox"], [110, 70, 160, 86])
        self.assertAlmostEqual(ocr["confidence"], 0.92, places=3)
        self.assertTrue(state["observation_token"])
        self.assertFalse(state["persisted"])

    def test_uia_button_fuses_away_ocr_text_inside_it(self):
        uia = FakeUIA([_uia_element("Сохранить", [100, 50, 200, 90])])
        screen = FakeScreen([{"text": "Сохранить", "bbox": [20, 10, 90, 30], "confidence": 88.0}])
        state = service(uia=uia, screen=screen).observe()
        labels = [(c["source"], c["label"]) for c in state["candidates"]]
        self.assertIn(("uia", "Сохранить"), labels)
        self.assertNotIn(("ocr", "Сохранить"), labels)
        self.assertEqual(state["candidate_count"], 1)

    def test_find_prefers_the_semantic_button(self):
        uia = FakeUIA([_uia_element("Сохранить", [100, 50, 200, 90])])
        screen = FakeScreen([{"text": "Сохранить как", "bbox": [10, 100, 90, 120], "confidence": 70.0}])
        found = service(uia=uia, screen=screen).find("сохранить", limit=1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source"], "uia")
        self.assertGreater(found[0]["match_score"], 0.5)

    def test_low_confidence_candidate_cannot_plan_a_click(self):
        screen = FakeScreen([{"text": "Отмена", "bbox": [10, 20, 60, 36], "confidence": 50.0}])
        denied = service(screen=screen).plan("click", "Отмена")
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(denied["reason"], "low_confidence")
        allowed = service(screen=screen, min_confidence=0.4).plan("click", "Отмена")
        self.assertEqual(allowed["status"], "ok")
        self.assertEqual(allowed["plan"]["actions"][0]["target"]["coordinate_space"], "screen")

    def test_plan_uses_uia_identity_for_semantic_operations(self):
        uia = FakeUIA([
            _uia_element("Поле ввода", [100, 100, 300, 130], ref="ref-edit", control_type="EditControl"),
        ])
        screen = FakeScreen([])
        grounding = service(uia=uia, screen=screen)
        click = grounding.plan("click", "Поле ввода")
        self.assertEqual(click["status"], "ok")
        target = click["plan"]["actions"][0]["target"]
        self.assertEqual(target["element_ref"], "ref-edit")
        self.assertEqual(target["element_sha256"], "a" * 64)
        focus = grounding.plan("focus", "Поле ввода")
        self.assertEqual(focus["status"], "ok")
        typed = grounding.plan("type", "Поле ввода", value="привет")
        self.assertEqual(typed["plan"]["actions"][0]["operation"], "type")
        self.assertEqual(typed["plan"]["actions"][0]["target"]["coordinate_space"], "screen")
        self.assertEqual(typed["plan"]["actions"][0]["value"], "привет")
        VisionActionPlan.from_dict(click["plan"])

    def test_missing_or_expired_observation_is_denied(self):
        screen = FakeScreen([{"text": "Отмена", "bbox": [10, 20, 60, 36], "confidence": 95.0}], token=False)
        missing = service(screen=screen).plan("click", "Отмена")
        self.assertEqual(missing["reason"], "fresh_observation_required")
        expired_screen = FakeScreen(
            [{"text": "Отмена", "bbox": [10, 20, 60, 36], "confidence": 95.0}], ttl_seconds=1.0
        )
        observation = service(screen=expired_screen).observe()
        with mock.patch("jawl_voicecompanion.screen_adapter.time.time", return_value=time.time() + 30):
            expired = service(screen=expired_screen).plan("click", "Отмена", observation=observation)
        self.assertEqual(expired["reason"], "stale_observation")

    def test_execute_grounded_uses_plan_executor_and_idempotency(self):
        uia = FakeUIA([_uia_element("Сохранить", [100, 50, 200, 90])])
        hostos = FakeHostOS(uia, FakeScreen([]))
        vision = VisionLookService(hostos)
        first = vision.execute_grounded("click", "Сохранить", postcondition_verifier=lambda c, r: True)
        self.assertEqual(first["status"], "verified")
        self.assertEqual(len(hostos.requests), 1)
        self.assertEqual(hostos.requests[0].tool, "desktop.act")
        self.assertEqual(hostos.requests[0].target["element_ref"], "ref-1")
        second = vision.execute_grounded("click", "Сохранить", postcondition_verifier=lambda c, r: True)
        self.assertEqual(second["status"], "verified")
        self.assertEqual(
            hostos.requests[0].idempotency_key,
            hostos.requests[1].idempotency_key,
            "the same grounded target must reuse the idempotency key",
        )

    def test_text_score_is_symmetric_for_ru_queries(self):
        self.assertEqual(_text_score("сохранить", "Сохранить"), 1.0)
        self.assertGreater(_text_score("сохранить", "Сохранить файл"), 0.5)
        self.assertEqual(_text_score("сохранить", "Отмена"), 0.0)


if __name__ == "__main__":
    unittest.main()
