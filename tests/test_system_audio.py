import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.system_audio import SystemAudioLoopback, SystemAudioUnavailable  # noqa: E402


class _FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.started = False
        self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.started = False

    def close(self):
        self.closed = True


class _FakePyAudio:
    def __init__(self):
        self.stream = None
        self.terminated = False

    def get_host_api_info_by_type(self, _api):
        return {"defaultOutputDevice": 1}

    def get_device_info_by_index(self, index):
        if index == 1:
            return {"name": "Speakers", "isLoopbackDevice": False}
        return {
            "index": index,
            "name": "Speakers [Loopback]",
            "isLoopbackDevice": True,
            "maxInputChannels": 2,
            "defaultSampleRate": 48000,
        }

    def get_loopback_device_info_generator(self):
        yield self.get_device_info_by_index(7)

    def open(self, **kwargs):
        self.stream = _FakeStream(kwargs["stream_callback"])
        return self.stream

    def terminate(self):
        self.terminated = True


class _FakeBackend:
    paWASAPI = 1
    paInt16 = 2
    paContinue = 0
    last = None

    def PyAudio(self):
        self.last = _FakePyAudio()
        return self.last


class SystemAudioTests(unittest.TestCase):
    def test_capture_is_explicit_and_missing_backend_degrades(self):
        capture = SystemAudioLoopback(lambda *_: None)
        self.assertFalse(capture.state()["running"])
        with patch(
            "jawl_voicecompanion.system_audio.importlib.import_module",
            side_effect=ImportError,
        ), self.assertRaises(SystemAudioUnavailable):
            capture.start()
        self.assertEqual(capture.state()["last_error"], "pyaudiowpatch_not_installed")

    def test_fake_loopback_delivers_bounded_pcm_to_ephemeral_consumer(self):
        received = []
        delivered = threading.Event()

        def consume(data, sample_rate, channels, session_id):
            received.append((data, sample_rate, channels, session_id))
            delivered.set()

        capture = SystemAudioLoopback(
            consume,
            backend=_FakeBackend(),
            max_chunk_bytes=2048,
            queue_size=2,
        )
        state = capture.start()
        self.assertTrue(state["running"])
        stream = capture.backend.last.stream
        stream.callback(b"\x01\x02" * 4000, 4000, {}, None)
        self.assertTrue(delivered.wait(1), received)
        self.assertEqual(received[0][1:], (48000, 2, "ambient-audio"))
        self.assertLessEqual(len(received[0][0]), 2048)
        self.assertFalse(capture.state()["raw_persisted"])
        stopped = capture.stop()
        self.assertFalse(stopped["running"])

    def test_callback_queue_is_bounded_and_counts_drops(self):
        capture = SystemAudioLoopback(
            lambda *_: time.sleep(0.2),
            backend=_FakeBackend(),
            queue_size=1,
        )
        capture.start()
        stream = capture.backend.last.stream
        for _ in range(10):
            stream.callback(b"\x00\x00" * 512, 512, {}, None)
        self.assertLessEqual(capture.state()["queue_depth"], 1)
        self.assertGreater(capture.state()["dropped_chunks"], 0)
        capture.stop()


if __name__ == "__main__":
    unittest.main()
