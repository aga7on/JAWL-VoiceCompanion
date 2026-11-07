import json
import sys
import tempfile
import time
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

    def test_batch_processing_five_lines_with_max_events_two(self):
        ingestor = SensoryIngestor(
            self.memory, self.path, max_events_per_poll=2, music_dedupe_s=300.0
        )
        for i in range(5):
            _write(self.path, {"type": "speech", "ts": f"t{i}", "text": f"line {i}"})

        # Poll 1: 2 lines
        res1 = ingestor.poll_once(now=1000.0)
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(res1["processed"], 2)
        self.assertEqual(ingestor.state()["counters"]["lines"], 2)
        self.assertEqual(ingestor.state()["counters"]["speech"], 2)

        # Poll 2: 2 lines
        res2 = ingestor.poll_once(now=1001.0)
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(res2["processed"], 2)
        self.assertEqual(ingestor.state()["counters"]["lines"], 4)
        self.assertEqual(ingestor.state()["counters"]["speech"], 4)

        # Poll 3: 1 line
        res3 = ingestor.poll_once(now=1002.0)
        self.assertEqual(res3["status"], "ok")
        self.assertEqual(res3["processed"], 1)
        self.assertEqual(ingestor.state()["counters"]["lines"], 5)
        self.assertEqual(ingestor.state()["counters"]["speech"], 5)

        # Poll 4: idle (0 lines)
        res4 = ingestor.poll_once(now=1003.0)
        self.assertEqual(res4["status"], "idle")
        self.assertEqual(res4["processed"], 0)
        self.assertEqual(ingestor.state()["counters"]["lines"], 5)
        self.assertEqual(ingestor.state()["counters"]["speech"], 5)

        # Verify offset matches file size and is persisted
        file_size = self.path.stat().st_size
        self.assertEqual(ingestor.state()["offset"], file_size)
        offset_file = self.path.with_name(self.path.name + ".offset")
        self.assertEqual(int(offset_file.read_text(encoding="ascii").strip()), file_size)

    def test_partial_trailing_line_across_polls(self):
        # Write 2 complete lines and 1 partial line
        line1 = json.dumps({"type": "speech", "text": "first"}) + "\n"
        line2 = json.dumps({"type": "speech", "text": "second"}) + "\n"
        partial_start = '{"type": "speech", "text": "third '
        self.path.write_bytes((line1 + line2 + partial_start).encode("utf-8"))

        res1 = self.ingestor.poll_once(now=1000.0)
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(res1["processed"], 2)
        self.assertEqual(self.ingestor.state()["counters"]["speech"], 2)
        # Offset must be exactly the byte length of line1 + line2
        expected_offset = len((line1 + line2).encode("utf-8"))
        self.assertEqual(self.ingestor.state()["offset"], expected_offset)

        # Now complete the partial line
        partial_end = 'message"}\n'
        with self.path.open("ab") as stream:
            stream.write(partial_end.encode("utf-8"))

        res2 = self.ingestor.poll_once(now=1001.0)
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(res2["processed"], 1)
        self.assertEqual(self.ingestor.state()["counters"]["speech"], 3)
        self.assertEqual(self.ingestor.state()["offset"], self.path.stat().st_size)

        # Subsequent poll is idle
        res3 = self.ingestor.poll_once(now=1002.0)
        self.assertEqual(res3["status"], "idle")
        self.assertEqual(res3["processed"], 0)

    def test_malformed_line_advances_offset_without_getting_stuck(self):
        ingestor = SensoryIngestor(
            self.memory, self.path, max_events_per_poll=1, music_dedupe_s=300.0
        )
        with self.path.open("wb") as stream:
            stream.write(b"this is not valid json\n")
            stream.write(b'{"type": "speech", "text": "valid after error"}\n')

        # Poll 1 encounters the malformed line
        res1 = ingestor.poll_once(now=1000.0)
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(res1["processed"], 1)
        self.assertEqual(ingestor.state()["counters"]["errors"], 1)
        self.assertEqual(ingestor.state()["counters"]["speech"], 0)
        self.assertEqual(ingestor.state()["offset"], len(b"this is not valid json\n"))

        # Poll 2 should advance to the next line and NOT get stuck on the malformed line
        res2 = ingestor.poll_once(now=1001.0)
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(res2["processed"], 1)
        self.assertEqual(ingestor.state()["counters"]["errors"], 1)
        self.assertEqual(ingestor.state()["counters"]["speech"], 1)
        self.assertEqual(ingestor.state()["offset"], self.path.stat().st_size)

        # Poll 3 is idle
        res3 = ingestor.poll_once(now=1002.0)
        self.assertEqual(res3["status"], "idle")
        self.assertEqual(res3["processed"], 0)

    def test_file_shrink_resets_offset_to_zero(self):
        # Write large content first
        for i in range(3):
            _write(self.path, {"type": "speech", "ts": f"t{i}", "text": f"long text speech message {i}"})
        self.ingestor.poll_once(now=1000.0)
        old_offset = self.ingestor.state()["offset"]
        self.assertGreater(old_offset, 50)

        # Shrink the file to something smaller than old_offset
        short_line = json.dumps({"type": "speech", "text": "short"}) + "\n"
        self.path.write_text(short_line, encoding="utf-8")
        shrunk_size = self.path.stat().st_size
        self.assertLess(shrunk_size, old_offset)

        # Poll after shrink should reset offset and process the new content from byte 0
        res = self.ingestor.poll_once(now=1001.0)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["processed"], 1)
        self.assertEqual(self.ingestor.state()["offset"], shrunk_size)
        offset_file = self.path.with_name(self.path.name + ".offset")
        self.assertEqual(int(offset_file.read_text(encoding="ascii").strip()), shrunk_size)

        # Shrink to 0 bytes
        self.path.write_text("", encoding="utf-8")
        res_empty = self.ingestor.poll_once(now=1002.0)
        self.assertEqual(res_empty["status"], "idle")
        self.assertEqual(res_empty["processed"], 0)
        self.assertEqual(self.ingestor.state()["offset"], 0)
        self.assertEqual(int(offset_file.read_text(encoding="ascii").strip()), 0)

    def test_journal_rotation_drains_unread_tail_from_rotated_file(self):
        ingestor = SensoryIngestor(
            self.memory, self.path, max_events_per_poll=2, music_dedupe_s=300.0
        )
        # Write 4 speech lines
        for i in range(4):
            _write(self.path, {"type": "speech", "ts": f"t{i}", "text": f"speech line {i}"})

        # Poll 1: only reads 2 lines due to max_events_per_poll=2
        res1 = ingestor.poll_once(now=1000.0)
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(res1["processed"], 2)
        self.assertEqual(ingestor.state()["counters"]["speech"], 2)

        # Log rotation occurs: active file renamed to .1, new active file created with 1 line
        rotated_path = self.path.with_name(self.path.name + ".1")
        self.path.rename(rotated_path)
        _write(self.path, {"type": "speech", "ts": "new_t0", "text": "brand new speech"})

        # Poll 2: detects rotation, drains the remaining 2 lines from .1
        res2 = ingestor.poll_once(now=1001.0)
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(ingestor.state()["counters"]["speech"], 4)

        # Poll 3: reads the new file from byte 0
        res3 = ingestor.poll_once(now=1002.0)
        self.assertEqual(res3["status"], "ok")
        self.assertEqual(ingestor.state()["counters"]["speech"], 5)
        self.assertEqual(ingestor.state()["offset"], self.path.stat().st_size)


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

    def test_pause_blocks_polling_until_resume(self):
        ingestor = SensoryIngestor(
            self.memory, self.path, music_dedupe_s=300.0, poll_interval_s=0.05
        )
        self.addCleanup(ingestor.stop)
        _write(self.path, {"type": "screen_frame", "ts": "t", "window": "Code", "changed": True})
        ingestor.pause()
        self.assertTrue(ingestor.state()["paused"])
        ingestor.start()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(ingestor.state()["counters"]["visual"], 0)
        ingestor.resume()
        self.assertFalse(ingestor.state()["paused"])
        deadline = time.monotonic() + 3.0
        while ingestor.state()["counters"]["visual"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(ingestor.state()["counters"]["visual"], 1)
        self.assertEqual(self.memory.state()["observation_count"], 1)


if __name__ == "__main__":
    unittest.main()
