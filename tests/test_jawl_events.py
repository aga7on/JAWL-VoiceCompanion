import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_events import JawlEventFileSink  # noqa: E402


class JawlEventSinkTests(unittest.TestCase):
    def test_writes_framework_api_compatible_bounded_event(self):
        with tempfile.TemporaryDirectory() as root:
            sink = JawlEventFileSink(Path(root) / ".jawl_events")
            result = sink.publish({
                "type": "SPEAK_INTENT",
                "event_id": "intent-1",
                "payload": {
                    "summary": "Ошибка в окне",
                    "significance": 3,
                    "observed_event_id": "screen-1",
                },
            })
            files = list((Path(root) / ".jawl_events").glob("*.json"))
            self.assertEqual(result["status"], "delivered")
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["payload"]["event_type"], "SCREEN_DELTA")
            self.assertFalse(payload["payload"]["raw_frame_persisted"])
            self.assertNotIn("image", json.dumps(payload))

    def test_rejects_non_intent_payload(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                JawlEventFileSink(root).publish({"type": "SCREEN_DELTA"})

    def test_event_id_cannot_escape_event_directory(self):
        with tempfile.TemporaryDirectory() as root:
            sink = JawlEventFileSink(Path(root) / "events")
            sink.publish({
                "type": "SPEAK_INTENT",
                "event_id": "..\\outside/intent",
                "payload": {"summary": "Ошибка", "significance": 2},
            })
            self.assertEqual(len(list((Path(root) / "events").glob("*.json"))), 1)
            self.assertFalse((Path(root) / "outside").exists())


if __name__ == "__main__":
    unittest.main()
