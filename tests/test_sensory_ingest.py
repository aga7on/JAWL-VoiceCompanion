import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
from jawl_voicecompanion.sensory_ingest import SensoryIngestor  # noqa: E402


def _write(path: Path, *events: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")


class SensoryIngestorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sensory.ndjson"
        self.memory = AmbientMemoryBuffer(enabled=True)
        self.ingestor = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)

    def test_screen_change_ingested(self):
        _write(self.path, {"type": "screen_frame", "ts": "t", "window": "Code", "changed": True})
        result = self.ingestor.poll_once(now=1000.0)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(self.ingestor.state()["counters"]["visual"], 1)
        self.assertEqual(len(self.memory.observations(now=1001.0)), 1)

    def test_screen_unchanged_ignored(self):
        _write(self.path, {"type": "screen_frame", "ts": "t", "window": "Code", "changed": False})
        self.ingestor.poll_once(now=1000.0)
        self.assertEqual(self.ingestor.state()["counters"]["visual"], 0)

    def test_private_window_suppressed(self):
        _write(self.path, {"type": "screen_frame", "ts": "t", "window": "Bank wallet", "changed": True})
        self.ingestor.poll_once(now=1000.0)
        self.assertEqual(self.ingestor.state()["counters"]["visual"], 0)
        self.assertEqual(self.memory.observations(now=1001.0), [])

    def test_music_deduplicated_until_change(self):
        _write(self.path, {"type": "music_state", "key": "C# major", "bpm": 156.2, "key_confidence": 0.54})
        self.ingestor.poll_once(now=1000.0)
        _write(self.path, {"type": "music_state", "key": "C# major", "bpm": 156.2, "key_confidence": 0.54})
        self.ingestor.poll_once(now=1005.0)
        self.assertEqual(self.ingestor.state()["counters"]["music"], 1)
        _write(self.path, {"type": "music_state", "key": "A minor", "bpm": 92.0, "key_confidence": 0.4})
        self.ingestor.poll_once(now=1010.0)
        self.assertEqual(self.ingestor.state()["counters"]["music"], 2)

    def test_speech_ingested(self):
        _write(self.path, {"type": "speech", "ts": "t", "text": "привет, как дела", "speech_seconds": 1.5})
        self.ingestor.poll_once(now=1000.0)
        self.assertEqual(self.ingestor.state()["counters"]["speech"], 1)

    def test_offset_persists_between_polls(self):
        _write(self.path, {"type": "speech", "ts": "t", "text": "раз"})
        first = self.ingestor.poll_once(now=1000.0)
        second = self.ingestor.poll_once(now=1001.0)
        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["processed"], 0)
        self.assertEqual(self.ingestor.state()["counters"]["speech"], 1)

    def test_partial_line_waits_for_completion(self):
        with self.path.open("wb") as stream:
            stream.write(b'{"type": "speech", "text": "cut-off"')
        self.assertEqual(self.ingestor.poll_once(now=1000.0)["processed"], 0)
        with self.path.open("ab") as stream:
            stream.write(b'}\n')
        result = self.ingestor.poll_once(now=1001.0)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(self.ingestor.state()["counters"]["speech"], 1)

    def test_truncation_resets_offset(self):
        _write(self.path, {"type": "speech", "text": "старое"})
        self.ingestor.poll_once(now=1000.0)
        self.path.write_text("", encoding="utf-8")
        _write(self.path, {"type": "speech", "text": "новое"})
        result = self.ingestor.poll_once(now=1001.0)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(self.ingestor.state()["counters"]["speech"], 2)


class SensoryOffsetPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sensory.ndjson"
        self.memory = AmbientMemoryBuffer(enabled=True)

    def test_offset_survives_restart(self):
        first = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)
        _write(self.path, {"type": "screen_frame", "ts": "t", "window": "Code", "changed": True})
        first.poll_once(now=1000.0)
        offset = first.state()["offset"]
        self.assertGreater(offset, 0)
        restarted = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)
        self.assertEqual(restarted.state()["offset"], offset)
        _write(self.path, {"type": "speech", "ts": "t2", "text": "новая реплика", "speech_seconds": 1.0})
        result = restarted.poll_once(now=1001.0)
        self.assertEqual(result["processed"], 1)

    def test_shrunk_journal_restarts_from_zero(self):
        first = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)
        _write(self.path, {"type": "screen_frame", "ts": "t", "window": "Code", "changed": True})
        first.poll_once(now=1000.0)
        self.path.write_text("", encoding="utf-8")
        restarted = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)
        self.assertEqual(restarted.state()["offset"], 0)

    def test_persisted_offset_never_exceeds_the_journal(self):
        first = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)
        _write(self.path, {"type": "speech", "ts": "t", "text": "привет", "speech_seconds": 1.0})
        first.poll_once(now=1000.0)
        self.path.write_text("", encoding="utf-8")
        _write(self.path, {"type": "speech", "ts": "t2", "text": "снова", "speech_seconds": 1.0})
        restarted = SensoryIngestor(self.memory, self.path, music_dedupe_s=300.0)
        self.assertEqual(restarted.state()["offset"], 0)


if __name__ == "__main__":
    unittest.main()
