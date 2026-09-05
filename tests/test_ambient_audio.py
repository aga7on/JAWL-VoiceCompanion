import sys
import time
import unittest
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
from jawl_voicecompanion.asr import ASRUnavailable  # noqa: E402
from jawl_voicecompanion.audio_understanding import AudioDescriptionService  # noqa: E402
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

    def feed_audio(self, pcm16, *, sample_rate, channels, session_id):
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
        }


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

    def feed_audio(self, pcm16, *, sample_rate, channels, session_id):
        self.feed_calls.append((pcm16, sample_rate, channels, session_id))
        return {"status": "buffered", "bytes": len(pcm16)}

    def finish(self, session_id):
        self.finish_calls.append(session_id)
        if self.release is not None:
            self.release.wait(2)
        if self.fail_finishes:
            self.fail_finishes -= 1
            raise ASRUnavailable("synthetic ASR failure")
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

    def test_speech_transcript_and_audio_description_are_parallel_ambient_evidence(self):
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
        self.assertEqual(bridge.state()["conversation_turns_emitted"], 0)

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


if __name__ == "__main__":
    unittest.main()
