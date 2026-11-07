import base64
import sys
import time
from threading import Event, Thread
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.streaming_perception import StreamingPerception  # noqa: E402


class _Capture:
    def observe(self):
        return {
            "status": "verified",
            "captured_at": "2026-01-01T00:00:00+00:00",
            "window": {"class_name": "TestWindow", "bounds": [0, 0, 100, 100]},
            "image": {"data_base64": base64.b64encode(b"frame").decode("ascii")},
        }


class _Cortex:
    def embed_image_tokens(self, image_bytes):
        vector = np.ones(768, dtype=np.float32) / np.sqrt(768)
        return vector, np.ones((70, 768), dtype=np.float32) / np.sqrt(768)

    def embed_audio_pcm16(self, clip, sample_rate=16000):
        return np.ones(768, dtype=np.float32) / np.sqrt(768)


class _Transcriber:
    def transcribe_image_vectors(self, global_vec, token_vecs, **kwargs):
        return [{"region_index": 0, "candidates": [{"token": "garbage", "score": 0.5}]}]

    def top_tokens(self, global_vec, **kwargs):
        return [{"token": "garbage", "score": 0.5}]

    def visual_transcript(self, slices, **kwargs):
        return "garbage"

    def transcribe_pcm16(self, clip, **kwargs):
        return [{"candidates": [{"token": "noise", "score": 0.4}]}]


class _Describer:
    def describe_screen_detailed(self, image_bytes):
        return SimpleNamespace(description="detailed scene")

    def describe_audio_pcm16(self, clip, **kwargs):
        return SimpleNamespace(description="audio scene", level0="unknown_audio", level0_score=0.4)


class _Fusion:
    media_buffer = None

    def __init__(self):
        self.calls = []

    def observe_media(self, observation, **kwargs):
        self.calls.append((observation, kwargs))
        return ""


class StreamingPerceptionTests(unittest.TestCase):
    def test_video_worker_never_starts_or_resumes_ambient_capture(self):
        class Ambient:
            def __init__(self, status):
                self.bridge = SimpleNamespace(stream_tap=None, stream_tap_owner=None)
                self.status = status
                self.start_calls = 0
            def start(self):
                self.start_calls += 1
                self.status = "running"

        # The explicit service owner may leave the source stopped, paused, or
        # running already. Starting video must preserve each state unchanged.
        for initial in ("stopped", "paused", "running"):
            with self.subTest(initial=initial):
                ambient = Ambient(initial)
                perception = StreamingPerception(
                    screen_capture=_Capture(), cortex=_Cortex(), describer=_Describer(),
                    fusion=_Fusion(), ambient_audio=ambient,
                )
                perception.start()
                try:
                    self.assertEqual(ambient.start_calls, 0)
                    self.assertEqual(ambient.status, initial)
                    self.assertIs(ambient.bridge.stream_tap_owner, perception)
                finally:
                    perception.stop()
                self.assertIsNone(ambient.bridge.stream_tap)

    def test_structured_vision_is_used_when_open_vocab_is_weak(self):
        fusion = _Fusion()
        perception = StreamingPerception(
            screen_capture=_Capture(),
            cortex=_Cortex(),
            describer=_Describer(),
            fusion=fusion,
            transcriber=_Transcriber(),
        )
        perception._capture_video()
        self.assertEqual(perception._last_video["selected"], "structured")
        self.assertEqual(perception._last_video["summary"], "detailed scene")
        self.assertEqual(perception._last_video["open_vocab"], "garbage")
        self.assertEqual(fusion.calls[0][1]["metadata"]["source"], "focused_window")

    def test_audio_queue_drops_oldest_instead_of_newest(self):
        perception = StreamingPerception(
            screen_capture=_Capture(),
            cortex=_Cortex(),
            describer=_Describer(),
            fusion=_Fusion(),
            transcriber=_Transcriber(),
            audio_queue_size=1,
        )
        one_second = b"\x00\x00" * 16000
        perception.consume_audio(one_second, 16000, 1, "ambient-audio")
        perception.consume_audio(one_second, 16000, 1, "ambient-audio")
        self.assertEqual(perception._audio_drops_old, 1)
        self.assertEqual(perception._audio_queue.qsize(), 1)

    def test_pause_audio_clears_partial_and_queued_windows_and_gates_tap(self):
        perception = StreamingPerception(
            screen_capture=_Capture(), cortex=_Cortex(), describer=_Describer(),
            fusion=_Fusion(), transcriber=_Transcriber(),
        )
        one_second = b"\x00\x00" * 16000
        perception.consume_audio(one_second[:12000], 16000, 1, "ambient-audio")
        perception.consume_audio(one_second, 16000, 1, "ambient-audio")
        self.assertEqual(perception._audio_queue.qsize(), 1)
        perception.pause_audio()
        self.assertEqual(perception._audio_queue.qsize(), 0)
        self.assertEqual(len(perception._audio_buffer), 0)
        self.assertEqual(perception._audio_queue.unfinished_tasks, 0)
        perception.consume_audio(one_second, 16000, 1, "ambient-audio")
        self.assertEqual(perception._audio_queue.qsize(), 0)
        perception.resume_audio()
        perception.consume_audio(one_second, 16000, 1, "ambient-audio")
        self.assertEqual(perception._audio_queue.qsize(), 1)

    def test_discontinuity_does_not_resume_explicitly_paused_audio(self):
        perception = StreamingPerception(screen_capture=_Capture(), cortex=_Cortex(), describer=_Describer(),
                                         fusion=_Fusion(), transcriber=_Transcriber())
        perception.pause_audio()
        perception.consume_audio(b"\x01\x00" * 16000, 16000, 1, "ambient-audio",
                                 captured_at=time.monotonic(), discontinuity=True)
        self.assertTrue(perception._audio_paused)
        self.assertEqual(perception._audio_queue.qsize(), 0)
        self.assertEqual(len(perception._audio_buffer), 0)

    def test_concurrent_pause_and_gap_leave_no_post_pause_queued_audio(self):
        perception = StreamingPerception(screen_capture=_Capture(), cortex=_Cortex(), describer=_Describer(),
                                         fusion=_Fusion(), transcriber=_Transcriber())
        entered, release, pause_started = Event(), Event(), Event()
        original_put = perception._audio_queue.put_nowait
        def blocked_put(item):
            entered.set()
            release.wait(2)
            return original_put(item)
        perception._audio_queue.put_nowait = blocked_put
        sender = Thread(target=lambda: perception.consume_audio(
            b"\x01\x00" * 16000, 16000, 1, "ambient-audio",
            captured_at=time.monotonic(), discontinuity=True), daemon=True)
        def pause():
            pause_started.set()
            perception.pause_audio()
        stopper = Thread(target=pause, daemon=True)
        sender.start()
        try:
            self.assertTrue(entered.wait(1))
            stopper.start()
            self.assertTrue(pause_started.wait(1))
        finally:
            release.set()
            sender.join(2)
            if stopper.ident is not None:
                stopper.join(2)
        self.assertFalse(sender.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertTrue(perception._audio_paused)
        self.assertEqual(perception._audio_queue.qsize(), 0)
        self.assertEqual(perception._audio_queue.unfinished_tasks, 0)

    def test_restart_waits_for_blocked_previous_audio_worker(self):
        entered, release = Event(), Event()
        perception = StreamingPerception(screen_capture=_Capture(), cortex=_Cortex(), describer=_Describer(),
                                         fusion=_Fusion(), transcriber=_Transcriber())
        def blocked_processing(*args, **kwargs):
            entered.set()
            release.wait(3)
        perception._process_audio = blocked_processing
        perception.start()
        try:
            perception.consume_audio(b"\x01\x00" * 16000, 16000, 1, "ambient-audio",
                                     captured_at=time.monotonic())
            self.assertTrue(entered.wait(1))
            previous = perception._audio_thread
            perception.stop(timeout=.01)
            self.assertTrue(perception.state()["stopping"])
            self.assertTrue(perception.state()["audio_worker_alive"])
            self.assertIs(perception._audio_thread, previous)
            with self.assertRaisesRegex(RuntimeError, "still stopping"):
                perception.start()
            self.assertIs(perception._audio_thread, previous)
            release.set()
            previous.join(2)
            perception.stop(timeout=1)
            self.assertFalse(perception.state()["stopping"])
            perception.start()
            self.assertIsNot(perception._audio_thread, previous)
        finally:
            release.set()
            perception.stop(timeout=2)

    def test_stop_timeout_reports_inflight_fusion_commit_and_blocks_restart(self):
        entered, release = Event(), Event()
        class BlockingFusion:
            media_buffer = None
            def __init__(self): self.calls = 0
            def note(self, kind, text, **kwargs):
                self.calls += 1
                entered.set()
                release.wait(3)

        fusion = BlockingFusion()
        perception = StreamingPerception(screen_capture=_Capture(), cortex=_Cortex(), describer=None,
                                         fusion=fusion, transcriber=_Transcriber())
        perception.start()
        try:
            perception.consume_audio(b"\x01\x00" * 16000, 16000, 1, "ambient-audio",
                                     captured_at=time.monotonic())
            self.assertTrue(entered.wait(1))
            before = time.monotonic()
            perception.stop(timeout=.05)
            self.assertLess(time.monotonic() - before, .3)
            state = perception.state()
            self.assertTrue(state["stopping"])
            self.assertTrue(state["audio_worker_alive"])
            self.assertEqual(state["last_error"], "streaming_perception_workers_still_stopping")
            with self.assertRaisesRegex(RuntimeError, "still stopping"):
                perception.start()
            # This commit began before stop; a timed stop explicitly reports
            # stopping until it finishes instead of pretending to revoke it.
            self.assertEqual(fusion.calls, 1)
            previous = perception._audio_thread
            release.set()
            previous.join(2)
            perception.stop(timeout=1)
            self.assertFalse(perception.state()["stopping"])
            self.assertEqual(fusion.calls, 1)
        finally:
            release.set()
            perception.stop(timeout=2)

    def test_stop_deadline_includes_busy_lifecycle_lock(self):
        perception = StreamingPerception(screen_capture=_Capture(), cortex=_Cortex(), describer=None,
                                         fusion=_Fusion(), transcriber=_Transcriber())
        entered, release = Event(), Event()
        def hold_lifecycle():
            with perception._lifecycle_lock:
                entered.set()
                release.wait(3)
        holder = Thread(target=hold_lifecycle, daemon=True)
        holder.start()
        try:
            self.assertTrue(entered.wait(1))
            before = time.monotonic()
            perception.stop(timeout=.05)
            self.assertLess(time.monotonic() - before, .3)
            self.assertTrue(perception.state()["stopping"])
            self.assertEqual(perception.state()["last_error"], "streaming_perception_workers_still_stopping")
        finally:
            release.set()
            holder.join(2)
            perception.stop(timeout=1)
        self.assertFalse(perception.state()["stopping"])

    def test_pause_suppresses_inflight_audio_result_after_model_returns(self):
        entered, release = Event(), Event()

        class BlockingCortex(_Cortex):
            def embed_audio_pcm16(self, clip, sample_rate=16000):
                entered.set()
                release.wait(2)
                return super().embed_audio_pcm16(clip, sample_rate)

        fusion = _Fusion()
        perception = StreamingPerception(
            screen_capture=_Capture(), cortex=BlockingCortex(), describer=_Describer(),
            fusion=fusion, transcriber=None,
        )
        epoch = perception._audio_epoch
        worker = Thread(
            target=lambda: perception._process_audio(
                b"\x00\x00" * 16000, 16000, 1, audio_epoch=epoch,
            )
        )
        worker.start()
        self.assertTrue(entered.wait(1))
        perception.pause_audio()
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(fusion.calls, [])

    def test_audio_context_uses_transcript_over_unverified_music_claim(self):
        fusion = _Fusion()

        class Transcript(_Transcriber):
            def visual_transcript(self, slices, **kwargs):
                return "Привет, как дела?"

        class MixedDescriber(_Describer):
            def describe_audio_pcm16(self, clip, **kwargs):
                return SimpleNamespace(
                    description="raw energetic_action_music, 120 BPM",
                    level0="energetic_action_music", level0_score=0.9,
                    level1={},
                    level2={"dsp": {"is_speech_likely": True, "is_music_likely": True,
                                     "rms_dbfs": -27.2, "duration_s": 1.0}},
                )

        perception = StreamingPerception(
            screen_capture=_Capture(), cortex=_Cortex(), describer=MixedDescriber(),
            fusion=fusion, transcriber=Transcript(),
        )
        perception._process_audio(b"\x00\x00" * 16000, 16000, 1)
        observation, kwargs = fusion.calls[0]
        self.assertEqual(observation["description"], "Привет, как дела?")
        self.assertEqual(kwargs["metadata"]["confidence"], 0.0)
        self.assertNotIn("music", observation["description"].lower())

    def test_audio_context_abstains_on_silence_without_transcript(self):
        fusion = _Fusion()

        class NoTranscript(_Transcriber):
            def visual_transcript(self, slices, **kwargs):
                return ""

        class SilenceDescriber(_Describer):
            def describe_audio_pcm16(self, clip, **kwargs):
                return SimpleNamespace(
                    description="raw energetic_action_music",
                    level0="energetic_action_music", level0_score=0.99,
                    level1={},
                    level2={"dsp": {"is_speech_likely": False, "is_music_likely": False,
                                     "rms_dbfs": -100.0, "duration_s": 1.0}},
                )

        perception = StreamingPerception(
            screen_capture=_Capture(), cortex=_Cortex(), describer=SilenceDescriber(),
            fusion=fusion, transcriber=NoTranscript(),
        )
        perception._process_audio(b"\x00\x00" * 16000, 16000, 1)
        self.assertEqual(fusion.calls, [])

    def test_bridge_tap_preserves_capture_time_for_fusion_and_wall_buffer(self):
        from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge
        from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer

        class Transcript(_Transcriber):
            def visual_transcript(self, slices, **kwargs): return "человек говорит"
        class Buffer:
            def __init__(self): self.calls = []
            def observe(self, observation, **kwargs): self.calls.append(kwargs)
        class Fusion:
            def __init__(self): self.media_buffer = Buffer(); self.calls = []; self.noted = Event()
            def note(self, kind, text, **kwargs):
                self.calls.append((kind, text, kwargs)); self.noted.set()
        class Segmenter:
            def submit(self, *args, **kwargs): return {"status": "accepted"}
        class Voice:
            def feed_audio(self, *args, **kwargs): return []
            def end_audio(self, *args, **kwargs): return []

        fusion = Fusion()
        perception = StreamingPerception(screen_capture=None, cortex=_Cortex(), describer=None,
                                         fusion=fusion, transcriber=Transcript(), audio_max_age_seconds=5)
        bridge = AmbientAudioASRBridge(Voice(), AmbientMemoryBuffer(enabled=True))
        bridge._session_id = "ambient-audio"
        bridge._segmenter = Segmenter()
        bridge.stream_tap, bridge.stream_tap_owner = perception.consume_audio, perception
        worker = Thread(target=perception._audio_loop, daemon=True)
        worker.start()
        capture = time.monotonic() - 1.0
        try:
            bridge.consume(b"\x01\x00" * 16000, 16000, 1, "ambient-audio", captured_at=capture,
                           timestamp_source="host_callback_receipt_monotonic")
            self.assertTrue(fusion.noted.wait(2))
            self.assertEqual(len(fusion.calls), 1)
            self.assertEqual(fusion.calls[0][2]["now"], capture)
            self.assertGreaterEqual(fusion.calls[0][2]["metadata"]["age_ms"], 950)
            self.assertEqual(fusion.calls[0][2]["metadata"]["timestamp_source"], "host_callback_receipt_monotonic")
            self.assertAlmostEqual(fusion.media_buffer.calls[0]["now"], time.time() - 1.0, delta=0.5)
        finally:
            perception._stop.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_unknown_or_stale_capture_time_never_published_as_current(self):
        fusion = _Fusion()
        perception = StreamingPerception(screen_capture=None, cortex=_Cortex(), describer=_Describer(),
                                         fusion=fusion, transcriber=_Transcriber(), audio_max_age_seconds=2)
        worker = Thread(target=perception._audio_loop, daemon=True)
        worker.start()
        try:
            pcm = b"\x01\x00" * 16000
            perception.consume_audio(pcm, 16000, 1, "unknown")
            perception._audio_queue.join()
            perception.consume_audio(pcm, 16000, 1, "stale", captured_at=time.monotonic() - 20)
            perception._audio_queue.join()
            self.assertEqual(perception._audio_drops_unknown_time, 1)
            self.assertEqual(perception._audio_drops_stale, 1)
            self.assertEqual(fusion.calls, [])
        finally:
            perception._stop.set()
            worker.join(2)

    def test_model_result_that_becomes_stale_is_not_published(self):
        fusion = _Fusion()
        perception = StreamingPerception(screen_capture=None, cortex=_Cortex(), describer=None,
                                         fusion=fusion, transcriber=_Transcriber(), audio_max_age_seconds=2)
        perception._process_audio(b"\x01\x00" * 16000, 16000, 1,
                                  captured_at=time.monotonic() - 20)
        self.assertEqual(perception._audio_drops_stale, 1)
        self.assertEqual(fusion.calls, [])


if __name__ == "__main__":
    unittest.main()
