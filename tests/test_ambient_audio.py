import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from threading import Barrier, Event, Thread

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_audio import (  # noqa: E402
    AmbientAudioASRBridge,
    AmbientAudioDisabled,
    AmbientAudioService,
    PlaybackSuppression,
)
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
from jawl_voicecompanion.asr import UtteranceBuffer  # noqa: E402
from jawl_voicecompanion.audio_understanding import AudioDescriptionService  # noqa: E402
from jawl_voicecompanion.audio_understanding import TENTATIVE_RHYTHM_CUE  # noqa: E402
from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.ambient_segments import AmbientSegment  # noqa: E402
from jawl_voicecompanion.voicemem_client import VoiceMemUnavailable  # noqa: E402


class _FakeVoiceMem:
    def __init__(self, final_on_feed=True):
        self.calls = []
        self.final_on_feed = final_on_feed

    def feed_audio(self, pcm16, *, sample_rate, session_id):
        self.calls.append((pcm16, sample_rate, session_id))
        events = [{"type": "USER_PARTIAL", "payload": {"text": "частичный"}}]
        if self.final_on_feed and len(self.calls) == 1:
            events.append({
                "type": "VOICE_TURN",
                "event_id": "ambient-final-1",
                "payload": {"text": "В игре объявлен важный квест", "confidence": 0.9},
            })
        return events

    def end_audio(self, *, session_id):
        self.calls.append((b"", 16000, session_id))
        return [{
            "type": "VOICE_TURN",
            "event_id": "ambient-flush-1",
            "payload": {"text": "Фраза после сброса", "confidence": 0.8},
        }]


class _FakeCapture:
    session_id = "ambient-audio:test"

    def __init__(self):
        self.running = False

    def start(self):
        self.running = True
        return self.state()

    def stop(self):
        self.running = False
        return self.state()

    def state(self):
        return {"running": self.running, "raw_persisted": False}


class _FakeFinalASR:
    def __init__(self):
        self.calls = []

    def feed_audio(self, pcm16, *, sample_rate, channels, session_id, cancel_event=None):
        self.calls.append((pcm16, sample_rate, channels, session_id))
        return {"status": "buffered", "bytes": sum(len(item[0]) for item in self.calls)}

    def finish(self, session_id):
        self.calls.append((b"", 16000, 1, session_id))
        return {"status": "transcribed", "text": "Русский ambient текст"}


class _FakeAudioDescription:
    name = "fake-captioner"

    def __init__(self):
        self.calls = []

    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        self.calls.append((pcm16, sample_rate, channels, clip_id))
        return {
            "kind": "music",
            "description": "Музыкальный фрагмент с ударными.",
            "tags": ["музыка", "ударные"],
            "mood": "ритмичное",
            "confidence": 0.82,
            "candidate_hypotheses": [{
                "category": "music_genre",
                "candidates": [
                    {"label": "jazz_smooth", "similarity": 0.69},
                    {"label": "hip_hop_beat", "similarity": 0.67},
                ],
            }],
        }


class _TentativeAudioDescription:
    name = "tentative-captioner"

    def describe(self, _pcm16, *, sample_rate, channels, clip_id):
        return {
            "kind": "sound",
            "description": TENTATIVE_RHYTHM_CUE,
            "tags": [],
            "mood": "",
            "confidence": 0.0,
            "duration_seconds": 0.2,
        }


class _IndependentMusicDetector:
    def __init__(self):
        self.calls = []

    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        self.calls.append((len(pcm16), sample_rate, channels, clip_id))
        return {
            "kind": "music",
            "description": "Music detected in 3 of 3 recent audio windows.",
            "tags": ["Saxophone"],
            "mood": "",
            "confidence": 0.82,
            "duration_seconds": 4.0,
            "windows": 3,
            "music_windows": 3,
            "music_score_max": 0.91,
            "music_score_median": 0.82,
        }


class _WeakMusicDetector(_IndependentMusicDetector):
    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        self.calls.append((len(pcm16), sample_rate, channels, clip_id))
        return {
            "kind": "unknown",
            "description": "No reliable audio event detected.",
            "tags": [],
            "confidence": 0.0,
            "duration_seconds": 4.0,
            "windows": 3,
            "music_windows": 0,
            "music_score_max": 0.34,
            "music_score_median": 0.33,
            "music_hypothesis": {
                "raw_score_max": 0.34,
                "raw_score_median": 0.33,
                "windows": 3,
                "music_windows": 0,
                "required_windows": 2,
                "verified": False,
                "calibrated": False,
            },
        }


class _BlockingMusicDetector(_IndependentMusicDetector):
    def __init__(self, *, block_calls=1):
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self.block_calls = block_calls

    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        self.calls.append((len(pcm16), sample_rate, channels, clip_id))
        if len(self.calls) <= self.block_calls:
            self.entered.set()
            self.release.wait(2)
        return {
            "kind": "music",
            "description": "Music detected in 3 of 3 recent audio windows.",
            "tags": ["Saxophone"],
            "mood": "",
            "confidence": 0.82,
            "duration_seconds": 0.25,
            "windows": 3,
            "music_windows": 3,
            "music_score_max": 0.91,
            "music_score_median": 0.82,
        }


class _BlockingOnceASR(_FakeFinalASR):
    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def finish(self, session_id):
        self.entered.set()
        self.release.wait(2)
        return super().finish(session_id)


class _BlockingAudioDescription(_FakeAudioDescription):
    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        self.entered.set()
        self.release.wait(2)
        return super().describe(pcm16, sample_rate=sample_rate, channels=channels, clip_id=clip_id)


class _EmptyFinalASR:
    def feed_audio(self, *_args, **_kwargs):
        return {"status": "buffered"}

    def finish(self, _session_id):
        return {"status": "empty", "text": ""}


class _SequencedFinalASR:
    def __init__(self, *, fail_finishes=0, release=None):
        self.feed_calls = []
        self.finish_calls = []
        self.discard_calls = []
        self.fail_finishes = fail_finishes
        self.release = release

    def feed_audio(self, pcm16, *, sample_rate, channels, session_id, cancel_event=None):
        self.feed_calls.append((pcm16, sample_rate, channels, session_id))
        return {"status": "buffered", "bytes": len(pcm16)}

    def finish(self, session_id):
        self.finish_calls.append(session_id)
        if self.release is not None:
            self.release.wait(2)
        if self.fail_finishes:
            self.fail_finishes -= 1
            raise RuntimeError("synthetic ASR failure")
        return {"status": "transcribed", "text": f"ambient segment {len(self.finish_calls)}"}

    def discard(self, session_id):
        self.discard_calls.append(session_id)


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class AmbientAudioTests(unittest.TestCase):
    def test_unknown_music_frame_replaces_live_music_claim_without_memory_write(self):
        memory = AmbientMemoryBuffer(enabled=True)
        fusion = PerceptionFusion()
        captured = time.monotonic()
        fusion.note("music", "Music detected by independent YAMNet.", now=captured)
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=_FakeFinalASR(), perception_fusion=fusion
        )
        bridge._session_id = "session"
        bridge._generation = "generation"
        segment = AmbientSegment(
            segment_id="unknown-segment", session_id="session", generation="generation",
            sequence=1, pcm16=b"\x00\x00" * 32000, sample_rate=16000, channels=1,
            started_at=captured - 2.0, ended_at=captured,
        )
        bridge._ingest_soundscape(
            {"kind": "unknown", "windows": 0, "music_windows": 0},
            segment,
            "ambient-audio:unknown-segment",
            music_frame={"state": "unknown", "energy_trend": "unknown"},
        )
        state = fusion.current_state("music")
        self.assertTrue(state["fresh"])
        self.assertIn("не доказывает", fusion.compose(now=captured))
        self.assertEqual(state["metadata"]["music_state"], "unknown")
        self.assertEqual(memory.observations(), [])

    def test_concurrent_start_is_serialized_to_one_generation_and_worker(self):
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(_FakeVoiceMem(), memory, final_asr=_EmptyFinalASR())
        barrier = Barrier(3)
        results = []

        def start_worker():
            barrier.wait()
            results.append(bridge.start("concurrent-start"))

        threads = [Thread(target=start_worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())

        self.assertEqual(len(results), 2)
        state = bridge.state()
        self.assertEqual(state["lifecycle"], "running")
        self.assertTrue(state["processing_worker_alive"])
        self.assertEqual(state["segmenter"]["session_id"], "concurrent-start")
        self.assertEqual(len({item["active_generation"] for item in results}), 1)
        bridge.stop("concurrent-start", flush=False)

    def test_stop_waits_for_start_transition_and_leaves_no_extra_worker(self):
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(_FakeVoiceMem(), memory, final_asr=_EmptyFinalASR())
        entered_segmenter = Event()
        release_segmenter = Event()
        original_start = bridge._segmenter.start

        def delayed_segmenter_start(session_id):
            entered_segmenter.set()
            self.assertTrue(release_segmenter.wait(2))
            return original_start(session_id)

        bridge._segmenter.start = delayed_segmenter_start
        start_result = []
        stop_result = []
        start_thread = Thread(target=lambda: start_result.append(bridge.start("start-stop")))
        stop_thread = Thread(target=lambda: stop_result.append(bridge.stop("start-stop", flush=False)))
        start_thread.start()
        self.assertTrue(entered_segmenter.wait(1))
        stop_thread.start()
        self.assertTrue(_wait_for(lambda: stop_thread.is_alive()))
        self.assertEqual(stop_result, [])
        release_segmenter.set()
        start_thread.join(2)
        stop_thread.join(2)
        self.assertFalse(start_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(len(start_result), 1)
        self.assertEqual(len(stop_result), 1)
        self.assertEqual(stop_result[0]["status"], "cancelled")
        state = bridge.state()
        self.assertEqual(state["lifecycle"], "stopped")
        self.assertFalse(state["processing_worker_alive"])
        self.assertFalse(state["segmenter"]["running"])

    def test_self_tts_playback_is_filtered_before_asr(self):
        voice_mem = _FakeVoiceMem()
        memory = AmbientMemoryBuffer(enabled=True)
        suppression = PlaybackSuppression()
        bridge = AmbientAudioASRBridge(
            voice_mem, memory, playback_suppression=suppression
        )
        suppression.begin(30)
        result = bridge.consume(b"\x01\x00" * 1600, 16000, 1, "tts")
        self.assertEqual(result, {"status": "suppressed", "reason": "self_tts_playback"})
        self.assertFalse(voice_mem.calls)
        self.assertEqual(bridge.state()["suppressed_self_tts"], 1)

    def test_self_tts_suppresses_asr_but_keeps_independent_music_lane(self):
        memory = AmbientMemoryBuffer(enabled=True)
        suppression = PlaybackSuppression()
        final_asr = _FakeFinalASR()
        captioner = _FakeAudioDescription()
        detector = _IndependentMusicDetector()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory,
            playback_suppression=suppression,
            final_asr=final_asr,
            audio_describer=AudioDescriptionService(captioner),
            soundscape_detector=detector,
        )
        suppression.begin(30)

        result = bridge.consume(b"\x10\x00" * (16000 * 4), 16000, 1, "tts-mixed-with-game")
        self.assertEqual(result["mode"], "soundscape_only_self_tts")
        self.assertTrue(result["asr_suppressed"])
        bridge.flush("tts-mixed-with-game")

        self.assertFalse(final_asr.calls)
        self.assertFalse(captioner.calls)
        self.assertEqual(len(detector.calls), 1)
        self.assertTrue(any(
            item["payload"].get("source_app") == "yamnet-onnx-cpu"
            and item["payload"].get("audio_kind") == "music"
            for item in memory.observations()
        ))

    def test_loopback_pcm_is_resampled_and_final_only_enters_ambient_memory(self):
        voice_mem = _FakeVoiceMem()
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(voice_mem, memory, max_feed_bytes=2048)
        result = bridge.consume(b"\x01\x00" * 4800 * 2, 48000, 2, "speaker")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["ingested"], 0)
        self.assertEqual(bridge.flush("speaker")["ingested"], 1)
        self.assertEqual(len(memory.observations()), 1)
        self.assertEqual(memory.observations()[0]["payload"]["stream"], "system_audio")
        self.assertTrue(voice_mem.calls)
        self.assertTrue(all(rate == 16000 for _, rate, _ in voice_mem.calls))
        sessions = {session for _, _, session in voice_mem.calls}
        self.assertEqual(len(sessions), 1)
        self.assertTrue(next(iter(sessions)).startswith("ambient-audio:ambient-segment:"))
        self.assertTrue(any(not pcm16 for pcm16, _, _ in voice_mem.calls))
        self.assertTrue(all(len(chunk) <= 2048 and len(chunk) % 2 == 0 for chunk, _, _ in voice_mem.calls))
        self.assertEqual(bridge.state()["conversation_turns_emitted"], 0)
        self.assertFalse(bridge.state()["raw_audio_persisted"])

    def test_partial_is_not_memory_and_flush_accepts_final_turn(self):
        voice_mem = _FakeVoiceMem(final_on_feed=False)
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(voice_mem, memory)
        bridge.consume(b"\x00\x00" * 1600, 16000, 1, "media")
        flushed = bridge.flush("media")
        self.assertEqual(flushed["status"], "flushed")
        self.assertEqual(flushed["ingested"], 1)
        self.assertEqual(memory.observations()[0]["event_id"], "ambient-flush-1")

    def test_external_final_asr_is_used_for_russian_ambient_audio(self):
        voice_mem = _FakeVoiceMem()
        final_asr = _FakeFinalASR()
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(voice_mem, memory, final_asr=final_asr, max_feed_bytes=2048)

        accepted = bridge.consume(b"\x01\x00" * 4800 * 2, 48000, 2, "speaker")
        flushed = bridge.flush("speaker")

        self.assertEqual(accepted["mode"], "external_final_utterance")
        self.assertEqual(accepted["ingested"], 0)
        self.assertFalse(voice_mem.calls)
        self.assertTrue(final_asr.calls)
        self.assertEqual(flushed["transcript"], "Русский ambient текст")
        self.assertEqual(flushed["ingested"], 1)
        self.assertEqual(memory.observations()[0]["payload"]["text"], "Русский ambient текст")
        self.assertEqual(bridge.state()["mode"], "external_final_utterance")

    def test_system_audio_transcript_reaches_fresh_fusion_context_with_provenance(self):
        memory = AmbientMemoryBuffer(enabled=True)
        fusion = PerceptionFusion()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=_FakeFinalASR(), perception_fusion=fusion,
        )

        bridge.consume(b"\x01\x00" * 1600, 16000, 1, "movie-loopback")
        flushed = bridge.flush("movie-loopback")

        transcript = flushed["transcript"]
        self.assertTrue(transcript)
        self.assertIn(transcript, fusion.compose())
        state = fusion.current_state("speech")
        self.assertTrue(state["fresh"])
        self.assertEqual(state["metadata"]["source"], "system_audio_loopback")
        self.assertTrue(state["metadata"]["segment_id"])
        self.assertGreater(state["metadata"]["observed_at_monotonic"], 0)
        self.assertFalse(fusion.current_state("speech", now=state["metadata"]["observed_at_monotonic"] + 21)["fresh"])
        self.assertNotIn(transcript, fusion.compose(now=state["metadata"]["observed_at_monotonic"] + 21))

    def test_privacy_suppressed_system_transcript_never_reaches_fusion(self):
        class PrivateASR(_FakeFinalASR):
            def finish(self, session_id):
                return {"status": "transcribed", "text": "Password token: private-value"}

        memory = AmbientMemoryBuffer(enabled=True)
        fusion = PerceptionFusion()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=PrivateASR(), perception_fusion=fusion,
        )
        bridge.consume(b"\x01\x00" * 1600, 16000, 1, "private-loopback")
        flushed = bridge.flush("private-loopback")

        self.assertEqual(memory.state()["observation_count"], 0)
        self.assertEqual(flushed["transcript"], "")
        self.assertFalse(fusion.current_state("speech")["fresh"])
        self.assertNotIn("private-value", fusion.compose())

    def test_speech_transcript_and_music_description_are_preserved_independently(self):
        memory = AmbientMemoryBuffer(enabled=True)
        captioner = _FakeAudioDescription()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(),
            memory,
            final_asr=_FakeFinalASR(),
            audio_describer=AudioDescriptionService(captioner),
        )
        bridge.consume(b"\x01\x00" * 1600, 16000, 1, "mixed")
        flushed = bridge.flush("mixed")
        self.assertEqual(flushed["ingested"], 1)
        self.assertEqual(flushed["audio_description"]["ingested"], 1)
        self.assertEqual(len(captioner.calls), 1)
        self.assertEqual(len(memory.observations()), 2)
        kinds = [item["payload"].get("audio_kind") for item in memory.observations()]
        self.assertIn("music", kinds)
        self.assertTrue(any(item["payload"].get("text") == flushed["transcript"] for item in memory.observations()))
        description = next(item["payload"] for item in memory.observations() if item["payload"].get("audio_kind"))
        self.assertEqual(len(description["tags"]), 2)
        self.assertTrue(description["mood"])
        self.assertNotIn("not independently confirmed", description["text"])
        self.assertEqual(bridge.state()["conversation_turns_emitted"], 0)
        state = bridge.state()
        self.assertEqual(state["audio_description_count"], 1)
        self.assertEqual(state["audio_description_errors"], 0)
        self.assertEqual(state["audio_description_provider"], "fake-captioner")
        self.assertEqual(state["audio_description_last_kind"], "music")
        self.assertTrue(state["audio_description_last_fresh"])
        self.assertIsNotNone(state["audio_description_last_age_ms"])
        self.assertIsNotNone(state["audio_description_latency_ms_last"])
        self.assertIsNotNone(state["audio_description_latency_ms_p50"])

    def test_weak_music_score_reaches_brain_without_becoming_music_fact(self):
        fusion = PerceptionFusion()
        detector = _WeakMusicDetector()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(),
            AmbientMemoryBuffer(enabled=True),
            final_asr=_FakeFinalASR(),
            soundscape_detector=detector,
            perception_fusion=fusion,
        )
        bridge.consume(b"\x10\x00" * (16000 * 4), 16000, 1, "weak-music")
        bridge.flush("weak-music")

        candidate = fusion.current_state("music_candidate")
        self.assertTrue(candidate["fresh"])
        self.assertEqual(candidate["metadata"]["score_type"], "uncalibrated_raw_model_score")
        self.assertFalse(candidate["metadata"]["verified"])
        candidate_text = fusion.compose_snapshot()["channels"]["music_candidate"]["text"]
        self.assertIn("raw max=0.3400", candidate_text)
        self.assertIn("0/3 окнах", candidate_text)
        self.assertIn("не вероятность", candidate_text)
        self.assertFalse(fusion.current_state("music")["metadata"].get("music_state") == "music")
        self.assertIn("Слабый аудиосигнал", fusion.compose())
        self.assertIn("System-audio transcript:", fusion.compose())
        self.assertFalse(any(
            item["payload"].get("audio_kind") == "music"
            for item in bridge.memory.observations()
        ))
        self.assertEqual(bridge.state()["soundscape_last_kind"], "unknown")

    def test_independent_music_detector_preserves_music_alongside_asr(self):
        memory = AmbientMemoryBuffer(enabled=True)
        fusion = PerceptionFusion()
        detector = _IndependentMusicDetector()
        captioner = _FakeAudioDescription()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(),
            memory,
            final_asr=_FakeFinalASR(),
            audio_describer=AudioDescriptionService(captioner),
            soundscape_detector=detector,
            perception_fusion=fusion,
        )
        bridge.consume(b"\x10\x00" * (16000 * 4), 16000, 1, "mixed-music")
        flushed = bridge.flush("mixed-music")

        observations = memory.observations()
        audio_kinds = [item["payload"].get("audio_kind") for item in observations]
        self.assertIn("music", audio_kinds)
        self.assertTrue(any(
            item["payload"].get("text") and item["payload"].get("audio_kind") is None
            for item in observations
        ))
        music_event = next(
            item for item in observations
            if item["payload"].get("audio_kind") == "music"
            and item["payload"].get("source_app") == "yamnet-onnx-cpu"
        )
        music = music_event["payload"]
        self.assertEqual(music["tags"], ["Saxophone"])
        self.assertEqual(music["source_app"], "yamnet-onnx-cpu")
        caption_observation = next(
            item["payload"] for item in observations
            if item["payload"].get("audio_kind") == "music"
            and item["payload"].get("source_app") != "yamnet-onnx-cpu"
        )
        self.assertEqual(caption_observation["tags"], ["музыка", "ударные"])
        self.assertGreater(datetime.fromisoformat(music_event["created_at"]).timestamp(), time.time() - 10)
        self.assertGreater(datetime.fromisoformat(music["retention_until"]).timestamp(), time.time())
        self.assertTrue(fusion.current_state("music")["fresh"])
        description_state = fusion.current_state("audio_description")
        self.assertTrue(description_state["fresh"])
        self.assertEqual(description_state["metadata"]["source"], "fake-captioner")
        self.assertIn("Music detected by independent YAMNet", fusion.compose())
        self.assertIn("Возможная музыка (fake-captioner", fusion.compose())
        self.assertIn("Музыкальный фрагмент с ударными.", fusion.compose())
        self.assertIn("Гипотезы аудио:", fusion.compose())
        self.assertIn("jazz_smooth 0.69", fusion.compose())
        candidate_state = fusion.current_state("audio_candidates")
        self.assertTrue(candidate_state["fresh"])
        self.assertEqual(candidate_state["metadata"]["source"], "fake-captioner")
        self.assertEqual(candidate_state["metadata"]["score_type"], "cosine_similarity_not_probability")
        self.assertIn("System-audio transcript:", fusion.compose())
        self.assertEqual(len(captioner.calls), 1)
        self.assertEqual(len(detector.calls), 1)
        self.assertTrue(bridge.state()["soundscape_configured"])
        soundscape_state = bridge.state()
        self.assertEqual(soundscape_state["soundscape_count"], 1)
        self.assertEqual(soundscape_state["soundscape_last_kind"], "music")
        self.assertEqual(soundscape_state["soundscape_last_tags"], ["Saxophone"])
        self.assertEqual(soundscape_state["soundscape_last_windows"], 3)
        self.assertEqual(soundscape_state["soundscape_last_music_windows"], 3)
        self.assertEqual(soundscape_state["soundscape_last_music_score_max"], 0.91)
        self.assertEqual(soundscape_state["soundscape_last_music_score_median"], 0.82)
        music_frame = soundscape_state["soundscape_last_music_frame"]
        self.assertEqual(music_frame["state"], "music")
        self.assertEqual(music_frame["segment_id"], detector.calls[-1][3])
        self.assertEqual(music_frame["source"], "system_audio_loopback")
        self.assertEqual(music_frame["calibrated"], False)
        self.assertEqual(fusion.current_state("music")["metadata"]["music_frame"]["state"], "music")
        self.assertEqual(fusion.current_state("music")["metadata"]["candidate_tags"], ["Saxophone"])
        self.assertFalse(fusion.current_state("music")["metadata"]["candidate_tags_calibrated"])
        self.assertEqual([call[0] for call in detector.calls], [16000 * 2 * 4])
        self.assertEqual(bridge.segment_max_seconds, 15.0)
        self.assertEqual(bridge.soundscape_segment_max_seconds, 4.0)
        self.assertTrue(soundscape_state["soundscape_last_fresh"])
        self.assertGreaterEqual(soundscape_state["soundscape_last_age_ms"], 0)
        self.assertEqual(flushed["ingested"], 1)
        self.assertEqual(flushed["soundscape"]["ingested"], 1)

    def test_nonmusic_soundscape_invalidates_older_audio_caption(self):
        fusion = PerceptionFusion()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(),
            AmbientMemoryBuffer(enabled=True),
            perception_fusion=fusion,
        )
        bridge.start("music-to-sound")
        started_at = time.monotonic()
        fusion.note(
            "audio_description",
            "Captioner: possible guitar music.",
            now=started_at,
            metadata={"audio_kind": "music", "source": "captioner"},
        )
        fusion.note(
            "music",
            "Music detected by independent YAMNet.",
            now=started_at,
            metadata={"source": "system_audio_loopback"},
        )
        fusion.note(
            "audio_candidates",
            "Гипотезы audio: jazz_smooth 0.69",
            now=started_at,
            metadata={
                "source": "eg2-audio",
                "audio_kind": "music",
                "segment_started_monotonic": started_at - 1.0,
                "segment_ended_monotonic": started_at,
            },
        )
        segment = AmbientSegment(
            "new-sound-segment",
            "music-to-sound",
            bridge.state()["active_generation"],
            0,
            b"\x00\x00" * 1600,
            16000,
            1,
            started_at - 0.5,
            started_at,
        )

        bridge._ingest_soundscape(
            {
                "kind": "sound",
                "description": "Non-music ambience.",
                "tags": ["speech"],
                "confidence": 0.8,
                "duration_seconds": 1.0,
                "windows": 2,
                "music_windows": 0,
                "event_candidates": [{
                    "label": "Explosion", "score": 0.16, "window_hits": 2,
                    "windows": 3, "calibrated": False,
                }],
            },
            segment,
            "music-to-sound",
            music_frame={"state": "unknown", "rms_dbfs": -24.0},
        )

        self.assertFalse(fusion.current_state("audio_description", now=started_at + 1.1)["fresh"])
        self.assertFalse(fusion.current_state("audio_candidates", now=started_at + 1.1)["fresh"])
        self.assertTrue(fusion.current_state("music", now=started_at + 1.1)["fresh"])
        current = fusion.compose(now=started_at + 1.1)
        self.assertNotIn("possible guitar music", current)
        self.assertNotIn("jazz_smooth", current)
        self.assertIn("Explosion", current)
        self.assertTrue(fusion.current_state("audio_event_candidates", now=started_at + 1.1)["fresh"])
        self.assertIn("не подтвердил присутствие музыки", current)
        bridge.stop("music-to-sound", flush=False)
        self.assertFalse(fusion.current_state("audio_description")["fresh"])
        self.assertFalse(fusion.current_state("audio_candidates")["fresh"])
        self.assertFalse(fusion.current_state("audio_event_candidates")["fresh"])

    def test_soundscape_worker_emits_music_while_asr_is_blocked(self):
        memory = AmbientMemoryBuffer(enabled=True)
        fusion = PerceptionFusion()
        final_asr = _BlockingOnceASR()
        detector = _IndependentMusicDetector()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=final_asr,
            soundscape_detector=detector, perception_fusion=fusion,
            max_feed_bytes=2048, segment_max_bytes=4096,
        )
        self.addCleanup(final_asr.release.set)
        self.addCleanup(bridge.stop, flush=False)

        started = bridge.start("parallel-audio")
        stamp = time.monotonic()
        primary_segment = AmbientSegment(
            segment_id="asr-blocked", session_id="parallel-audio",
            generation=started["active_generation"], sequence=0,
            pcm16=b"\x10\x00" * 1600, sample_rate=16000, channels=1,
            started_at=stamp - 0.2, ended_at=stamp,
        )
        soundscape_segment = AmbientSegment(
            segment_id="music-independent", session_id="parallel-audio",
            generation=started["soundscape_segmenter"]["generation"], sequence=0,
            pcm16=b"\x10\x00" * 1600, sample_rate=16000, channels=1,
            started_at=stamp - 0.2, ended_at=stamp,
        )
        bridge._enqueue_segment(primary_segment)
        bridge._enqueue_soundscape_segment(soundscape_segment)

        self.assertTrue(final_asr.entered.wait(1))
        self.assertTrue(_wait_for(lambda: bridge.state()["soundscape_count"] == 1))
        self.assertTrue(fusion.current_state("music")["fresh"])
        self.assertEqual(
            sum(item["payload"].get("audio_kind") == "music" for item in memory.observations()),
            1,
        )
        self.assertTrue(bridge.state()["processing_worker_alive"])
        self.assertTrue(bridge.state()["soundscape_worker_alive"])

    def test_audio_description_worker_emits_while_asr_is_blocked(self):
        memory = AmbientMemoryBuffer(enabled=True)
        final_asr = _BlockingOnceASR()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory,
            final_asr=final_asr,
            audio_describer=AudioDescriptionService(_FakeAudioDescription()),
        )
        self.addCleanup(final_asr.release.set)
        self.addCleanup(bridge.stop, flush=False)

        started = bridge.start("parallel-description")
        stamp = time.monotonic()
        segment = AmbientSegment(
            segment_id="description-independent",
            session_id="parallel-description",
            generation=started["active_generation"],
            sequence=0,
            pcm16=b"\x10\x00" * 1600,
            sample_rate=16000,
            channels=1,
            started_at=stamp - 0.2,
            ended_at=stamp,
        )
        bridge._enqueue_segment(segment)

        self.assertTrue(final_asr.entered.wait(1))
        self.assertTrue(_wait_for(lambda: bridge.state()["audio_description_count"] == 1))
        state = bridge.state()
        self.assertEqual(state["processing_queue_depth"], 0)
        self.assertEqual(state["audio_description_queue_depth"], 0)
        self.assertTrue(state["processing_worker_alive"])
        self.assertTrue(state["audio_description_worker_alive"])

        audio_items = memory.observations()
        self.assertEqual(len(audio_items), 1)
        self.assertEqual(audio_items[0]["payload"]["audio_kind"], "music")
        final_asr.release.set()
        self.assertTrue(_wait_for(lambda: bridge.state()["segment_events"] == 1))
        self.assertEqual(len(memory.observations()), 2)

    def test_audio_description_queue_is_bounded_and_keeps_latest_pending_clip(self):
        memory = AmbientMemoryBuffer(enabled=True)
        captioner = _BlockingAudioDescription()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory,
            final_asr=_EmptyFinalASR(),
            audio_describer=AudioDescriptionService(captioner),
            description_queue_size=1,
        )
        self.addCleanup(captioner.release.set)
        self.addCleanup(bridge.stop, flush=False)

        started = bridge.start("bounded-description")
        generation = started["active_generation"]

        def segment(segment_id, sequence):
            stamp = time.monotonic()
            return AmbientSegment(
                segment_id=segment_id,
                session_id="bounded-description",
                generation=generation,
                sequence=sequence,
                pcm16=b"\x10\x00" * 1600,
                sample_rate=16000,
                channels=1,
                started_at=stamp - 0.2,
                ended_at=stamp,
            )

        bridge._enqueue_segment(segment("first", 0))
        self.assertTrue(captioner.entered.wait(1))
        bridge._enqueue_segment(segment("middle", 1))
        bridge._enqueue_segment(segment("latest", 2))

        state = bridge.state()
        self.assertEqual(state["audio_description_queue_depth"], 1)
        self.assertEqual(state["audio_description_queue_dropped"], 1)
        captioner.release.set()
        self.assertTrue(_wait_for(lambda: bridge.state()["audio_description_count"] == 2))
        self.assertEqual([call[3] for call in captioner.calls], ["first", "latest"])

    def test_soundscape_queue_is_bounded_and_counts_overflow(self):
        memory = AmbientMemoryBuffer(enabled=True)
        detector = _BlockingMusicDetector()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=_EmptyFinalASR(),
            soundscape_detector=detector, soundscape_queue_size=1,
        )
        self.addCleanup(detector.release.set)
        self.addCleanup(bridge.stop, flush=False)
        started = bridge.start("soundscape-overload")
        generation = started["soundscape_segmenter"]["generation"]

        def enqueue(sequence):
            segment = AmbientSegment(
                segment_id=f"music-{sequence}", session_id="soundscape-overload",
                generation=generation, sequence=sequence, pcm16=b"\x10\x00" * 1600,
                sample_rate=16000, channels=1,
                started_at=time.monotonic() - 0.2, ended_at=time.monotonic(),
            )
            bridge._enqueue_soundscape_segment(segment)

        enqueue(0)
        self.assertTrue(detector.entered.wait(1))
        enqueue(1)
        enqueue(2)
        state = bridge.state()
        self.assertEqual(state["soundscape_queue_depth"], 1)
        self.assertEqual(state["soundscape_dropped"], 1)
        self.assertLessEqual(state["soundscape_queue_depth"], 1)
        detector.release.set()
        self.assertTrue(_wait_for(lambda: len(detector.calls) == 2))
        self.assertTrue(detector.calls[-1][3].startswith("music-2"))

    def test_soundscape_result_from_cancelled_generation_is_dropped_after_restart(self):
        memory = AmbientMemoryBuffer(enabled=True)
        detector = _BlockingMusicDetector(block_calls=1)
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=_EmptyFinalASR(),
            soundscape_detector=detector,
            max_feed_bytes=2048, segment_max_bytes=4096,
        )
        self.addCleanup(detector.release.set)

        first = bridge.start("soundscape-restart")
        soundscape_generation = first["soundscape_segmenter"]["generation"]
        old_segment = AmbientSegment(
            segment_id="old-music", session_id="soundscape-restart",
            generation=soundscape_generation, sequence=0,
            pcm16=b"\x10\x00" * 1600, sample_rate=16000, channels=1,
            started_at=time.monotonic() - 0.2, ended_at=time.monotonic(),
        )
        bridge._enqueue_soundscape_segment(old_segment)
        self.assertTrue(detector.entered.wait(1))
        stopped = bridge.stop("soundscape-restart", flush=False, timeout=0.01)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertEqual(bridge.state()["lifecycle"], "stopping")

        detector.release.set()
        self.assertTrue(_wait_for(lambda: bridge.state()["lifecycle"] == "stopped"))
        self.assertEqual(memory.state()["observation_count"], 0)

        second = bridge.start("soundscape-restart")
        soundscape_generation = second["soundscape_segmenter"]["generation"]
        new_segment = AmbientSegment(
            segment_id="new-music", session_id="soundscape-restart",
            generation=soundscape_generation, sequence=0,
            pcm16=b"\x10\x00" * 1600, sample_rate=16000, channels=1,
            started_at=time.monotonic() - 0.2, ended_at=time.monotonic(),
        )
        bridge._enqueue_soundscape_segment(new_segment)
        self.assertTrue(_wait_for(lambda: memory.state()["observation_count"] == 1))
        self.assertEqual(memory.observations()[0]["event_id"], "new-music:yamnet")
        bridge.stop("soundscape-restart", flush=False)

    def test_unconfirmed_rhythm_cue_and_asr_speech_are_separate_observations(self):
        def build_bridge(asr):
            memory = AmbientMemoryBuffer(enabled=True)
            fusion = PerceptionFusion()
            bridge = AmbientAudioASRBridge(
                _FakeVoiceMem(),
                memory,
                final_asr=asr,
                audio_describer=AudioDescriptionService(_TentativeAudioDescription()),
                perception_fusion=fusion,
            )
            bridge.consume(b"\x01\x00" * 1600, 16000, 1, "rhythm-check")
            flushed = bridge.flush("rhythm-check")
            return memory, fusion, flushed

        memory, fusion, flushed = build_bridge(_EmptyFinalASR())
        self.assertEqual(flushed["audio_description"]["description"]["kind"], "sound")
        self.assertIn(TENTATIVE_RHYTHM_CUE, fusion.compose())
        sound_state = fusion.current_state("sound")
        self.assertEqual(sound_state["metadata"]["verified"], False)
        self.assertEqual(sound_state["metadata"]["confidence"], 0.0)
        self.assertEqual(memory.observations()[0]["payload"]["audio_kind"], "sound")

        speech_memory, speech_fusion, speech_flush = build_bridge(_FakeFinalASR())
        self.assertEqual(speech_flush["audio_description"]["description"]["kind"], "sound")
        self.assertIn(TENTATIVE_RHYTHM_CUE, speech_fusion.compose())
        self.assertTrue(speech_fusion.current_state("sound")["fresh"])
        speech_description = next(
            row["payload"] for row in speech_memory.observations()
            if row["payload"].get("audio_kind")
        )
        self.assertEqual(speech_description["audio_kind"], "sound")

    def test_unavailable_sidecar_degrades_without_emitting_a_user_turn(self):
        class BrokenVoiceMem(_FakeVoiceMem):
            def feed_audio(self, *_args, **_kwargs):
                raise VoiceMemUnavailable("offline")

        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(BrokenVoiceMem(), memory)
        result = bridge.consume(b"\x00\x00" * 100, 16000, 1, "offline")
        self.assertEqual(result["status"], "accepted")
        bridge.flush("offline")
        self.assertEqual(bridge.state()["last_error"], "voicemem_unavailable")
        self.assertEqual(memory.state()["observation_count"], 0)

    def test_external_asr_rotates_multiple_segments_without_stop(self):
        memory = AmbientMemoryBuffer(enabled=True)
        final_asr = _SequencedFinalASR()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=final_asr,
            max_feed_bytes=2048, segment_max_bytes=4096,
        )
        for _ in range(4):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "capture")
        self.assertTrue(_wait_for(lambda: len(final_asr.finish_calls) == 2))
        self.assertEqual(memory.state()["observation_count"], 2)
        self.assertEqual(len(set(final_asr.finish_calls)), 2)
        self.assertEqual(bridge.state()["conversation_turns_emitted"], 0)
        bridge.stop("capture", flush=False)

    def test_bounded_processing_overload_is_counted_and_does_not_grow_memory(self):
        memory = AmbientMemoryBuffer(enabled=True)
        release = Event()
        final_asr = _SequencedFinalASR(release=release)
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=final_asr,
            max_feed_bytes=2048, segment_max_bytes=4096,
            processing_queue_size=1,
        )
        bridge.consume(b"\x01\x00" * 1024, 16000, 1, "overload")
        bridge.consume(b"\x01\x00" * 1024, 16000, 1, "overload")
        self.assertTrue(_wait_for(lambda: len(final_asr.finish_calls) == 1))
        for _ in range(6):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "overload")
        self.assertTrue(_wait_for(lambda: bridge.state()["segmenter"]["emitted_segments"] >= 3))
        self.assertGreaterEqual(bridge.state()["segment_dropped"], 1)
        self.assertEqual(memory.state()["observation_count"], 0)
        release.set()
        bridge.stop("overload", flush=False)

    def test_final_partial_is_flushed_once_with_unique_correlation(self):
        memory = AmbientMemoryBuffer(enabled=True)
        final_asr = _SequencedFinalASR()
        bridge = AmbientAudioASRBridge(_FakeVoiceMem(), memory, final_asr=final_asr)
        bridge.consume(b"\x01\x00" * 100, 16000, 1, "partial")
        self.assertEqual(bridge.flush("partial")["ingested"], 1)
        self.assertEqual(bridge.flush("partial")["ingested"], 0)
        self.assertEqual(len(final_asr.finish_calls), 1)
        self.assertEqual(len(memory.observations()), 1)

    def test_stop_restart_uses_new_generation_and_drops_no_stale_memory(self):
        memory = AmbientMemoryBuffer(enabled=True)
        final_asr = _SequencedFinalASR()
        bridge = AmbientAudioASRBridge(_FakeVoiceMem(), memory, final_asr=final_asr)
        bridge.start("restart")
        bridge.consume(b"\x01\x00" * 100, 16000, 1, "restart")
        bridge.stop("restart", flush=True)
        first_generation = bridge.state()["segmenter"]["generation"]
        bridge.start("restart")
        second_generation = bridge.state()["active_generation"]
        bridge.consume(b"\x01\x00" * 100, 16000, 1, "restart")
        bridge.stop("restart", flush=True)
        self.assertNotEqual(first_generation, second_generation)
        self.assertEqual(len(final_asr.finish_calls), 2)
        self.assertEqual(len(memory.observations()), 2)

    def test_asr_error_recovers_on_the_next_segment(self):
        memory = AmbientMemoryBuffer(enabled=True)
        final_asr = _SequencedFinalASR(fail_finishes=1)
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=final_asr,
            max_feed_bytes=2048, segment_max_bytes=4096,
        )
        for _ in range(4):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "recover")
        self.assertTrue(_wait_for(lambda: len(final_asr.finish_calls) == 2))
        bridge.stop("recover", flush=False)
        self.assertEqual(len(memory.observations()), 1)
        self.assertIsNone(bridge.state()["last_error"])
        self.assertEqual(len(final_asr.discard_calls), 1)

    def test_cancelled_generation_cannot_promote_late_asr_result(self):
        class BlockingASR(_SequencedFinalASR):
            def __init__(self):
                super().__init__(release=Event())
                self.first_finish = Event()

            def finish(self, session_id):
                self.finish_calls.append(session_id)
                if len(self.finish_calls) == 1:
                    self.first_finish.set()
                self.release.wait(2)
                return {"status": "transcribed", "text": f"ambient segment {len(self.finish_calls)}"}

        memory = AmbientMemoryBuffer(enabled=True)
        final_asr = BlockingASR()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=final_asr,
            max_feed_bytes=2048, segment_max_bytes=4096,
        )
        bridge.start("stale")
        for _ in range(2):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "stale")
        self.assertTrue(final_asr.first_finish.wait(1))
        bridge.stop("stale", flush=False, timeout=0.01)
        self.assertEqual(bridge.state()["lifecycle"], "stopping")
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                bridge.start("stale")
        self.assertTrue(bridge.state()["processing_worker_alive"])
        final_asr.release.set()
        self.assertTrue(_wait_for(lambda: bridge.state()["lifecycle"] == "stopped"))
        bridge.start("stale")
        for _ in range(2):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "stale")
        self.assertTrue(_wait_for(lambda: len(final_asr.finish_calls) == 2))
        self.assertTrue(_wait_for(lambda: memory.state()["observation_count"] == 1))
        bridge.stop("stale", flush=False)
        self.assertGreaterEqual(bridge.state()["stale_segments"], 1)

    def test_stop_cancels_active_asr_without_cancelling_microphone_buffer(self):
        entered = Event()

        class CooperativeTranscriber:
            def transcribe(self, wav_bytes, *, cancel_event):
                entered.set()
                for _ in range(400):
                    if cancel_event.is_set():
                        break
                    Event().wait(0.005)
                return "cancelled ambient text"

        final_asr = UtteranceBuffer(CooperativeTranscriber())
        final_asr.feed_audio(b"\x01\x00" * 32, sample_rate=16000, channels=1, session_id="independent-mic")
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=final_asr,
            max_feed_bytes=2048, segment_max_bytes=4096,
        )
        self.addCleanup(final_asr.close)
        self.addCleanup(bridge.stop, flush=False)
        bridge.start("ambient-cancel")
        for _ in range(2):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "ambient-cancel")
        self.assertTrue(entered.wait(1))
        stopped = bridge.stop("ambient-cancel", flush=False, timeout=1.0)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertFalse(bridge.state()["processing_worker_alive"])
        self.assertEqual(final_asr.state()["inflight_transcriptions"], 0)
        self.assertIsNotNone(final_asr.to_wav("independent-mic"))
        self.assertEqual(memory.state()["observation_count"], 0)

    def test_blocking_description_cannot_commit_after_cancel(self):
        memory = AmbientMemoryBuffer(enabled=True)
        captioner = _BlockingAudioDescription()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory,
            final_asr=_EmptyFinalASR(),
            audio_describer=AudioDescriptionService(captioner),
            segment_max_bytes=4096,
            max_feed_bytes=2048,
        )
        bridge.start("description")
        for _ in range(2):
            bridge.consume(b"\x01\x00" * 1024, 16000, 1, "description")
        self.assertTrue(captioner.entered.wait(1))
        bridge.stop("description", flush=False, timeout=0.01)
        self.assertEqual(bridge.state()["lifecycle"], "stopping")
        captioner.release.set()
        self.assertTrue(_wait_for(lambda: bridge.state()["lifecycle"] == "stopped"))
        self.assertEqual(memory.state()["observation_count"], 0)
        self.assertGreaterEqual(bridge.state()["stale_segments"], 1)

    def test_service_requires_memory_consent_and_flushes_on_explicit_stop(self):
        voice_mem = _FakeVoiceMem(final_on_feed=False)
        memory = AmbientMemoryBuffer(enabled=False)
        bridge = AmbientAudioASRBridge(voice_mem, memory)
        service = AmbientAudioService(bridge, capture=_FakeCapture())
        with self.assertRaises(AmbientAudioDisabled):
            service.start()
        memory.set_enabled(True)
        self.assertTrue(service.start()["capture"]["running"])
        service.bridge.consume(b"\x00\x00" * 1600, 16000, 1, "ambient-audio:test")
        stopped = service.stop()
        self.assertEqual(stopped["flush"]["status"], "flushed")
        self.assertEqual(memory.observations()[0]["event_id"], "ambient-flush-1")

    def test_service_stop_closes_bridge_even_when_capture_reports_crashed(self):
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(_FakeVoiceMem(final_on_feed=False), memory)
        capture = _FakeCapture()
        service = AmbientAudioService(bridge, capture=capture)
        service.start()
        bridge.consume(b"\0\0" * 1600, 16000, 1, "ambient-audio:test")
        capture.running = False
        stopped = service.stop()
        self.assertEqual(stopped["flush"]["status"], "flushed")
        self.assertEqual(bridge.state()["lifecycle"], "stopped")

    def test_pause_cancels_pending_context_and_resume_starts_bridge_before_capture(self):
        class TrackingCapture(_FakeCapture):
            def __init__(self, bridge):
                super().__init__()
                self.bridge = bridge
                self.bridge_running_at_start = []

            def start(self):
                self.bridge_running_at_start.append(self.bridge.state()["lifecycle"] == "running")
                return super().start()

        memory = AmbientMemoryBuffer(enabled=True)
        fusion = PerceptionFusion()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), memory, final_asr=_EmptyFinalASR(), perception_fusion=fusion,
        )
        capture = TrackingCapture(bridge)
        service = AmbientAudioService(bridge, capture=capture)

        service.start()
        self.assertEqual(capture.bridge_running_at_start, [True])
        fusion.note("speech", "System-audio transcript: stale words")
        paused = service.pause()
        self.assertTrue(paused["paused"])
        self.assertFalse(capture.running)
        self.assertEqual(bridge.state()["lifecycle"], "stopped")
        self.assertFalse(fusion.current_state("speech")["fresh"])

        resumed = service.resume()
        self.assertTrue(resumed["capture"]["running"])
        self.assertEqual(capture.bridge_running_at_start, [True, True])
        self.assertEqual(bridge.state()["lifecycle"], "running")
        self.assertFalse(fusion.current_state("speech")["fresh"])
        service.stop()

    def test_pause_resume_transitions_are_serialized(self):
        class BlockingStopCapture(_FakeCapture):
            def __init__(self):
                super().__init__()
                self.stop_entered = Event()
                self.release_stop = Event()

            def stop(self):
                self.stop_entered.set()
                self.release_stop.wait(2)
                return super().stop()

        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(_FakeVoiceMem(), memory)
        capture = BlockingStopCapture()
        service = AmbientAudioService(bridge, capture=capture)
        service.start()
        paused, resumed = [], []
        pause_thread = Thread(target=lambda: paused.append(service.pause()))
        pause_thread.start()
        self.assertTrue(capture.stop_entered.wait(1))
        resume_thread = Thread(target=lambda: resumed.append(service.resume()))
        resume_thread.start()
        time.sleep(0.05)
        self.assertTrue(resume_thread.is_alive(), "resume must wait for pause transition")
        capture.release_stop.set()
        pause_thread.join(2)
        resume_thread.join(2)
        self.assertFalse(pause_thread.is_alive())
        self.assertFalse(resume_thread.is_alive())
        self.assertTrue(capture.running)
        self.assertEqual(bridge.state()["lifecycle"], "running")
        self.assertFalse(service.state()["paused"])
        service.stop()

    def test_pause_invalidation_wins_over_inflight_fusion_note(self):
        class BlockingFusion(PerceptionFusion):
            def __init__(self):
                super().__init__()
                self.note_entered = Event()
                self.release_note = Event()

            def note(self, *args, **kwargs):
                self.note_entered.set()
                self.release_note.wait(2)
                return super().note(*args, **kwargs)

        fusion = BlockingFusion()
        bridge = AmbientAudioASRBridge(
            _FakeVoiceMem(), AmbientMemoryBuffer(enabled=True), perception_fusion=fusion,
        )
        bridge.start("race-test")
        state = bridge.state()
        segment = AmbientSegment(
            "segment-1", "race-test", state["active_generation"], 0,
            b"\x00\x00" * 100, 16000, 1, time.monotonic() - 0.1, time.monotonic(),
        )
        commit = Thread(target=lambda: bridge._commit_transcript(
            segment, "valid transcript", confidence=0.9, event_id="event-1",
        ))
        commit.start()
        self.assertTrue(fusion.note_entered.wait(1))
        paused = []
        stop = Thread(target=lambda: paused.append(bridge.stop("race-test", flush=False)))
        stop.start()
        time.sleep(0.05)
        self.assertTrue(stop.is_alive(), "stop must serialize behind in-flight fusion publication")
        fusion.release_note.set()
        commit.join(2)
        stop.join(2)
        self.assertFalse(commit.is_alive())
        self.assertFalse(stop.is_alive())
        self.assertFalse(fusion.current_state("speech")["fresh"])


if __name__ == "__main__":
    unittest.main()
