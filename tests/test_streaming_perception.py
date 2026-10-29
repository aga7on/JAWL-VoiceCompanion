import base64
import sys
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


if __name__ == "__main__":
    unittest.main()
