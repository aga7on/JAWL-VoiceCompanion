import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jawl_voicecompanion.gateway import TextGateway
from jawl_voicecompanion.web import create_server
from jawl_voicecompanion.model_slots import ModelSlotRegistry, ModelSlot, MockModelAdapter
from jawl_voicecompanion.moss_coordinator import MossCoordinationLayer
from jawl_voicecompanion.scene_memory import (
    SceneMemoryManager,
    MultimodalSceneFrame,
    VisualDetection,
    BoundingBox,
    OCRItem,
    AcousticEvent,
)
from jawl_voicecompanion.game_controller import GameControllerAdapter


def _stop_server(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


class ModelSlotsWebEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.slot_registry = ModelSlotRegistry()
        self.slot_registry.register(
            ModelSlot.FOREGROUND_BRAIN,
            MockModelAdapter(model_name="default-foreground-brain"),
        )
        self.moss_coordinator = MossCoordinationLayer(slot_registry=self.slot_registry)
        self.scene_memory = SceneMemoryManager(capacity=100)
        self.game_controller = GameControllerAdapter()
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            model_slot_registry=self.slot_registry,
            moss_coordinator=self.moss_coordinator,
            scene_memory=self.scene_memory,
            game_controller=self.game_controller,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def tearDown(self):
        _stop_server(self.server, self.thread)

    def _get(self, path, headers=None):
        req = Request(f"{self.base}{path}", headers=headers if headers is not None else self.headers)
        with urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def _post(self, path, payload, headers=None):
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self.base}{path}",
            data=body,
            headers=headers if headers is not None else self.headers,
            method="POST",
        )
        with urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def test_model_slots_get_and_swap(self):
        # 1. Require session headers
        with self.assertRaises(HTTPError) as ctx:
            self._get("/api/models/slots", headers={})
        self.assertEqual(ctx.exception.code, 403)

        # 2. GET returns configured slots
        status, data = self._get("/api/models/slots")
        self.assertEqual(status, 200)
        self.assertTrue(data["configured"])
        self.assertIn("foreground_brain", data["slots"])

        # 3. POST swap slot
        status, res = self._post(
            "/api/models/swap",
            {
                "slot": "foreground_brain",
                "adapter_type": "mock",
                "model_name": "swapped-mock-brain",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["model_name"], "swapped-mock-brain")

        # 4. Verify updated snapshot
        _, updated = self._get("/api/models/slots")
        self.assertEqual(updated["slots"]["foreground_brain"]["model_name"], "swapped-mock-brain")

    def test_moss_queue_and_task(self):
        # 1. GET queue
        status, data = self._get("/api/moss/queue")
        self.assertEqual(status, 200)
        self.assertTrue(data["configured"])
        self.assertEqual(data["size"], 0)

        # 2. POST dispatch task
        status, res = self._post("/api/moss/task", {"prompt": "Perform deep research on target"})
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertTrue(res["task_id"].startswith("bg_"))
    def test_game_controller_state_and_press(self):
        # 1. GET gamepad state
        status, data = self._get("/api/game/gamepad")
        self.assertEqual(status, 200)
        self.assertTrue(data["configured"])
        self.assertIn("left_stick", data)
        self.assertIn("buttons", data)

        # 2. POST press button
        status, res = self._post("/api/game/gamepad/press", {"button": "A", "duration_ms": 50})
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertIn("status", res["result"])
        self.assertIn(res["result"]["status"], ("queued", "executed"))

    def test_scene_memory_summary_and_query(self):
        # 1. GET empty summary
        status, data = self._get("/api/scene/summary")
        self.assertEqual(status, 200)
        self.assertTrue(data["configured"])
        self.assertEqual(data["frame_count"], 0)

        # Ingest a frame with entity, OCR, and acoustic event
        frame = MultimodalSceneFrame(
            visual_detections=[
                VisualDetection(
                    label="boss_dragon",
                    confidence=0.98,
                    bbox=BoundingBox(0.2, 0.2, 0.8, 0.8),
                    attributes={"element": "fire", "hp": 5000},
                )
            ],
            ocr_items=[
                OCRItem(
                    text="VICTORY ROYAL",
                    confidence=0.95,
                    bbox=BoundingBox(0.4, 0.1, 0.6, 0.2),
                )
            ],
            acoustic_events=[
                AcousticEvent(label="roaring", confidence=0.89, is_speech=False)
            ],
        )
        self.scene_memory.ingest_frame(frame)

        # 2. GET summary after ingestion
        _, data = self._get("/api/scene/summary")
        self.assertEqual(data["frame_count"], 1)

        # 3. POST query entity
        status, res = self._post(
            "/api/scene/query",
            {"type": "entity", "name": "boss_dragon", "attribute": "element"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"]["status"], "observed_present")
        self.assertEqual(res["result"]["matches"][0]["value"], "fire")

        # 4. POST query ocr
        status, res = self._post(
            "/api/scene/query",
            {"type": "ocr", "pattern": "VICTORY"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"]["status"], "observed_present")

        # 5. POST query acoustic
        status, res = self._post(
            "/api/scene/query",
            {"type": "acoustic", "event": "roaring"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"]["status"], "observed_present")


class UnconfiguredModelSlotsWebEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            model_slot_registry=None,
            moss_coordinator=None,
            scene_memory=None,
            game_controller=None,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
        }

    def tearDown(self):
        _stop_server(self.server, self.thread)

    def _get(self, path):
        req = Request(f"{self.base}{path}", headers=self.headers)
        with urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def _post(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self.base}{path}",
            data=body,
            headers=self.headers,
            method="POST",
        )
        with urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def test_unconfigured_responses(self):
        # GETs report configured: False
        _, data = self._get("/api/models/slots")
        self.assertFalse(data["configured"])

        _, data = self._get("/api/moss/queue")
        self.assertFalse(data["configured"])

        _, data = self._get("/api/game/gamepad")
        self.assertFalse(data["configured"])

        _, data = self._get("/api/scene/summary")
        self.assertFalse(data["configured"])

        # POSTs report 503
        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/models/swap", {"slot": "foreground_brain"})
        self.assertEqual(ctx.exception.code, 503)

        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/moss/task", {"prompt": "test"})
        self.assertEqual(ctx.exception.code, 503)

        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/game/gamepad/press", {"button": "A"})
        self.assertEqual(ctx.exception.code, 503)

        with self.assertRaises(HTTPError) as ctx:
            self._post("/api/scene/query", {"type": "entity", "name": "foo"})
        self.assertEqual(ctx.exception.code, 503)
