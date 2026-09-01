import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge  # noqa: E402
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
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


class AmbientAudioTests(unittest.TestCase):
    def test_loopback_pcm_is_resampled_and_final_only_enters_ambient_memory(self):
        voice_mem = _FakeVoiceMem()
        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(voice_mem, memory, max_feed_bytes=2048)
        result = bridge.consume(b"\x01\x00" * 4800 * 2, 48000, 2, "speaker")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["ingested"], 1)
        self.assertEqual(len(memory.observations()), 1)
        self.assertEqual(memory.observations()[0]["payload"]["stream"], "system_audio")
        self.assertTrue(voice_mem.calls)
        self.assertTrue(all(rate == 16000 for _, rate, _ in voice_mem.calls))
        self.assertTrue(all(session == "ambient-audio:speaker" for _, _, session in voice_mem.calls))
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

    def test_unavailable_sidecar_degrades_without_emitting_a_user_turn(self):
        class BrokenVoiceMem(_FakeVoiceMem):
            def feed_audio(self, *_args, **_kwargs):
                raise VoiceMemUnavailable("offline")

        memory = AmbientMemoryBuffer(enabled=True)
        bridge = AmbientAudioASRBridge(BrokenVoiceMem(), memory)
        result = bridge.consume(b"\x00\x00" * 100, 16000, 1, "offline")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["error"], "voicemem_unavailable")
        self.assertEqual(memory.state()["observation_count"], 0)


if __name__ == "__main__":
    unittest.main()
