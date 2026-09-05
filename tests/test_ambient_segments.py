import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_segments import AmbientSegmenter  # noqa: E402


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class AmbientSegmenterTests(unittest.TestCase):
    def test_idle_timeout_and_audio_duration_rotate_without_another_chunk(self):
        now = [0.0]
        segments = []
        segmenter = AmbientSegmenter(
            segments.append,
            max_segment_bytes=1024 * 1024,
            max_segment_seconds=0.25,
            clock=lambda: now[0],
        )
        segmenter.start("timed")
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertTrue(_wait_for(lambda: segmenter.state()["queue_depth"] == 0))
        now[0] = 0.30
        self.assertTrue(_wait_for(lambda: len(segments) == 1))
        segmenter.submit(b"\0\0" * 4000, 16000, 1)
        self.assertTrue(_wait_for(lambda: len(segments) == 2))
        segmenter.stop(flush=False)
        self.assertEqual([len(item.pcm16) for item in segments], [2048, 8000])

    def test_submit_rejects_invalid_frames_formats_and_oversized_chunks(self):
        segmenter = AmbientSegmenter(lambda _segment: None, max_chunk_bytes=2048)
        segmenter.start("validation")
        with self.assertRaises(ValueError):
            segmenter.submit(b"\0\0", 16000, 2)
        with self.assertRaises(ValueError):
            segmenter.submit(b"\0\0", True, 1)
        with self.assertRaises(ValueError):
            segmenter.submit(b"\0\0", 16000, True)
        with self.assertRaises(ValueError):
            segmenter.submit(b"\0" * 2050, 16000, 1)
        self.assertEqual(segmenter.state()["rejected_chunks"], 4)
        segmenter.stop(flush=False)

    def test_rotates_on_bound_and_assigns_unique_ids(self):
        segments = []
        segmenter = AmbientSegmenter(segments.append, queue_size=4, max_segment_bytes=4096)
        segmenter.start("capture")
        self.assertEqual(segmenter.submit(b"\0\0" * 1024, 16000, 1)["status"], "accepted")
        self.assertEqual(segmenter.submit(b"\0\0" * 1024, 16000, 1)["status"], "accepted")
        self.assertTrue(_wait_for(lambda: len(segments) == 1))
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        segmenter.stop(flush=True)
        self.assertEqual(len(segments), 2)
        self.assertEqual(len({item.segment_id for item in segments}), 2)
        self.assertEqual([item.sequence for item in segments], [0, 1])
        self.assertTrue(all(len(item.pcm16) <= 4096 for item in segments))
        self.assertTrue(all(item.ended_at >= item.started_at for item in segments))

    def test_queue_overload_is_nonblocking_and_counted(self):
        entered = threading.Event()
        release = threading.Event()

        def consume(_segment):
            entered.set()
            release.wait(2)

        segmenter = AmbientSegmenter(consume, queue_size=1, max_segment_bytes=4096)
        segmenter.start("overload")
        started = time.monotonic()
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertTrue(_wait_for(lambda: segmenter.state()["queue_depth"] == 0))
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertTrue(entered.wait(1))
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        dropped = segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(dropped["status"], "dropped")
        self.assertEqual(segmenter.state()["dropped_chunks"], 1)
        self.assertEqual(segmenter.state()["dropped_bytes"], 2048)
        release.set()
        segmenter.stop(flush=False)

    def test_queue_byte_budget_drops_before_count_limit(self):
        entered = threading.Event()
        release = threading.Event()

        def consume(_segment):
            entered.set()
            release.wait(2)

        segmenter = AmbientSegmenter(
            consume,
            queue_size=4,
            max_chunk_bytes=4096,
            max_queue_bytes=4096,
            max_segment_bytes=4096,
        )
        segmenter.start("byte-budget")
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertTrue(_wait_for(lambda: segmenter.state()["queue_depth"] == 0))
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertTrue(entered.wait(1))
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        segmenter.submit(b"\0\0" * 1024, 16000, 1)
        dropped = segmenter.submit(b"\0\0" * 1024, 16000, 1)
        self.assertEqual(dropped["reason"], "ambient_segment_queue_bytes_full")
        self.assertEqual(segmenter.state()["queue_depth"], 2)
        release.set()
        segmenter.stop(flush=False)


if __name__ == "__main__":
    unittest.main()
