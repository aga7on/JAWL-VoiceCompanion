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
            "hostApi": 1,
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
        self.assertEqual(state["device_index"], 7)
        self.assertEqual(state["host_api_index"], 1)
        stream = capture.backend.last.stream
        stream.callback(b"\x01\x02" * 4000, 4000, {}, None)
        self.assertTrue(delivered.wait(1), received)
        self.assertEqual(received[0][1:], (48000, 2, "ambient-audio"))
        self.assertLessEqual(len(received[0][0]), 2048)
        self.assertIsNotNone(capture.state()["last_chunk_age_ms"])
        self.assertLess(capture.state()["last_chunk_age_ms"], 1000)
        self.assertFalse(capture.state()["raw_persisted"])
        stopped = capture.stop()
        self.assertFalse(stopped["running"])
        self.assertIsNone(stopped["device_index"])

    def test_default_loopback_prefers_exact_name_and_refuses_ambiguous_fallback(self):
        class Backend:
            paWASAPI = 1

        class Devices:
            def __init__(self, candidates):
                self.candidates = candidates

            def get_host_api_info_by_type(self, _api):
                return {"defaultOutputDevice": 1}

            def get_device_info_by_index(self, _index):
                return {"name": "DigitalOutput (NVIDIA Audio)", "isLoopbackDevice": False}

            def get_loopback_device_info_generator(self):
                return iter(self.candidates)

        def candidate(index, name, channels=2):
            return {
                "index": index,
                "name": name,
                "isLoopbackDevice": True,
                "maxInputChannels": channels,
            }

        exact = candidate(9, "DigitalOutput (NVIDIA Audio) [Loopback]")
        partial = candidate(8, "Virtual DigitalOutput (NVIDIA Audio) [Loopback]")
        selected = SystemAudioLoopback._default_loopback(Devices([partial, exact]), Backend)
        self.assertEqual(selected["index"], 9)

        with self.assertRaisesRegex(SystemAudioUnavailable, "ambiguous"):
            SystemAudioLoopback._default_loopback(
                Devices([partial, candidate(10, "Other DigitalOutput (NVIDIA Audio) [Loopback]")]),
                Backend,
            )

    def test_explicit_output_name_selects_exact_loopback_without_default_fallback(self):
        class Devices:
            def __init__(self, candidates):
                self.candidates = candidates

            def get_loopback_device_info_generator(self):
                return iter(self.candidates)

        def candidate(index, name, channels=2):
            return {
                "index": index,
                "name": name,
                "isLoopbackDevice": True,
                "maxInputChannels": channels,
                "defaultSampleRate": 48000,
                "hostApi": 1,
            }

        wanted = "DigitalOutput (NVIDIA High Definition Audio)"
        selected = SystemAudioLoopback._named_loopback(
            Devices([
                candidate(38, "DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]"),
                candidate(39, wanted + " [Loopback]"),
            ]),
            wanted,
        )
        self.assertEqual(selected["index"], 39)

        with self.assertRaisesRegex(SystemAudioUnavailable, "not found"):
            SystemAudioLoopback._named_loopback(Devices([]), wanted)
        with self.assertRaisesRegex(SystemAudioUnavailable, "ambiguous"):
            SystemAudioLoopback._named_loopback(
                Devices([candidate(39, wanted + " [Loopback]"), candidate(40, wanted + " [Loopback]")]),
                wanted,
            )

        class NamedPyAudio(_FakePyAudio):
            def get_loopback_device_info_generator(self):
                yield candidate(38, "DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]")
                yield candidate(39, wanted + " [Loopback]")

        class NamedBackend(_FakeBackend):
            def PyAudio(self):
                self.last = NamedPyAudio()
                return self.last

        backend = NamedBackend()
        capture = SystemAudioLoopback(
            lambda *_args: None,
            backend=backend,
            output_device_name=wanted,
        )
        self.assertEqual(capture.start()["device_index"], 39)
        capture.stop()

    def test_default_loopback_ignores_candidates_without_input_channels(self):
        class Backend:
            paWASAPI = 1

        class Devices:
            def get_host_api_info_by_type(self, _api):
                return {"defaultOutputDevice": 1}

            def get_device_info_by_index(self, _index):
                return {"name": "DigitalOutput (NVIDIA Audio)", "isLoopbackDevice": False}

            def get_loopback_device_info_generator(self):
                return iter([{
                    "index": 9,
                    "name": "DigitalOutput (NVIDIA Audio) [Loopback]",
                    "isLoopbackDevice": True,
                    "maxInputChannels": 0,
                }])

        with self.assertRaisesRegex(SystemAudioUnavailable, "not found"):
            SystemAudioLoopback._default_loopback(Devices(), Backend)

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

    def test_signal_level_and_consumer_freshness_are_reported_without_pcm_retention(self):
        received = threading.Event()
        capture = SystemAudioLoopback(
            lambda *_args: received.set(),
            backend=_FakeBackend(),
            queue_size=2,
        )
        capture.start()
        capture.backend.last.stream.callback(b"\x01\x00\xff\x7f\x00\x00\x00\x00", 4, {}, None)
        self.assertTrue(received.wait(1))
        state = capture.state()
        self.assertEqual(state["chunks"], 1)
        self.assertEqual(state["consumer_chunks"], 1)
        self.assertEqual(state["last_chunk_peak_abs"], 32767)
        self.assertAlmostEqual(state["last_chunk_rms"], (32767**2 / 4) ** 0.5, places=2)
        self.assertLess(state["last_consumer_chunk_age_ms"], 1000)
        self.assertLess(state["last_consumer_lag_ms"], 1000)
        self.assertEqual(state["queue_high_water"], 1)
        self.assertFalse(state["raw_persisted"])
        capture.stop()

    def test_signal_window_needs_a_second_of_fresh_pcm_and_distinguishes_digital_zeros(self):
        capture = SystemAudioLoopback(lambda *_args: None, backend=_FakeBackend(), queue_size=128)
        capture.start()
        stream = capture.backend.last.stream
        zeros = b"\x00" * 4096  # 1024 frames, 48 kHz stereo
        for _ in range(50):
            stream.callback(zeros, 1024, {}, None)
            time.sleep(0.021)
        deadline = time.monotonic() + 2
        state = capture.state()
        while state["consumer_chunks"] < 50 and time.monotonic() < deadline:
            time.sleep(0.01)
            state = capture.state()
        self.assertEqual(state["consumer_chunks"], 50)
        self.assertEqual(state["signal_window_state"], "digital_silence")
        self.assertGreaterEqual(state["signal_window_duration_ms"], 800)
        self.assertGreaterEqual(state["signal_window_wall_span_ms"], 800)
        self.assertEqual(state["signal_window_rms"], 0.0)
        self.assertLessEqual(capture._signal_window.maxlen, 512)
        self.assertGreaterEqual(capture._signal_window.maxlen, 375)  # 96 kHz stereo / 256 frames needs ~300 entries per 800 ms
        capture.stop()

    def test_signal_window_marks_nonzero_pcm_unclassified_without_claiming_sound(self):
        capture = SystemAudioLoopback(lambda *_args: None, backend=_FakeBackend(), queue_size=128)
        capture.start()
        stream = capture.backend.last.stream
        low_pcm = b"\x10\x00" * 2048
        for _ in range(50):
            stream.callback(low_pcm, 1024, {}, None)
            time.sleep(0.021)
        deadline = time.monotonic() + 2
        state = capture.state()
        while state["consumer_chunks"] < 50 and time.monotonic() < deadline:
            time.sleep(0.01)
            state = capture.state()
        self.assertEqual(state["consumer_chunks"], 50)
        self.assertEqual(state["signal_window_state"], "nonzero_pcm_unclassified")
        self.assertEqual(state["signal_window_peak_abs"], 16)
        self.assertAlmostEqual(state["signal_window_rms"], 16.0, places=2)
        capture.stop()

    def test_stop_timeout_preserves_live_consumer_ownership_until_retry(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_consumer(*_args):
            entered.set()
            release.wait(2)

        backend = _FakeBackend()
        capture = SystemAudioLoopback(blocked_consumer, backend=backend)
        capture.start()
        backend.last.stream.callback(b"\x00\x00" * 1024, 1024, {}, None)
        self.assertTrue(entered.wait(1))

        stopped = capture.stop(timeout=0.01)
        self.assertTrue(stopped["running"])
        self.assertFalse(backend.last.terminated)
        with self.assertRaises(SystemAudioUnavailable):
            capture.start()

        release.set()
        stopped = capture.stop(timeout=1)
        self.assertFalse(stopped["running"])
        self.assertTrue(backend.last.terminated)


if __name__ == "__main__":
    unittest.main()
