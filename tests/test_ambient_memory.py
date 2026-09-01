import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402


class AmbientMemoryTests(unittest.TestCase):
    def test_capture_is_disabled_by_default(self):
        memory = AmbientMemoryBuffer()
        result = memory.ingest_system_audio("не должен сохраниться", event_id="off", now=1)
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(memory.state(now=1)["enabled"])

    def test_audio_and_visual_observations_coalesce_without_raw_media(self):
        memory = AmbientMemoryBuffer(enabled=True, episode_window_seconds=60, episode_ttl_seconds=600)
        audio = memory.ingest_system_audio(
            "В игре появился важный квест.", confidence=0.9, event_id="audio-1", now=100
        )
        visual = memory.ingest_visual(
            "На экране видна цель квеста.", confidence=0.8, event_id="screen-1", now=110
        )
        self.assertEqual(audio["status"], "retained")
        self.assertEqual(visual["status"], "retained")
        result = memory.triage(now=120)
        self.assertEqual(result["status"], "processed")
        self.assertEqual(len(result["episodes"]), 1)
        episode = result["episodes"][0]
        self.assertEqual(episode["type"], "AMBIENT_EPISODE_CANDIDATE")
        self.assertEqual(episode["payload"]["importance"], "promote_candidate")
        self.assertEqual(episode["payload"]["source"], "mixed")
        self.assertEqual(episode["payload"]["source_event_ids"], ["audio-1", "screen-1"])
        self.assertFalse(episode["payload"]["raw_audio_persisted"])
        self.assertFalse(episode["payload"]["raw_frame_persisted"])

    def test_private_duplicate_and_unknown_events_are_not_retained(self):
        memory = AmbientMemoryBuffer(enabled=True)
        private = memory.ingest_system_audio("Password token: secret", event_id="private", now=1)
        unknown = memory.ingest({"type": "USER_FINAL", "payload": {"text": "not ambient"}}, now=1)
        first = memory.ingest_visual("обычное наблюдение", event_id="same", now=1)
        duplicate = memory.ingest_visual("обычное наблюдение", event_id="same", now=2)
        self.assertEqual(private["status"], "suppressed")
        self.assertEqual(unknown["status"], "ignored")
        self.assertEqual(first["status"], "retained")
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(memory.state(now=2)["observation_count"], 1)

    def test_ttl_and_clear_remove_working_and_episode_data(self):
        memory = AmbientMemoryBuffer(enabled=True, observation_ttl_seconds=10, episode_ttl_seconds=60)
        self.assertEqual(memory.ingest_system_audio("обычный контекст", event_id="ttl", now=100)["status"], "retained")
        self.assertEqual(memory.state(now=111)["observation_count"], 0)
        memory.ingest_system_audio("важная цель", confidence=0.9, event_id="episode", now=120)
        self.assertEqual(len(memory.triage(now=120)["episodes"]), 1)
        self.assertEqual(memory.clear()["status"], "cleared")
        self.assertEqual(memory.state(now=121)["episode_count"], 0)


if __name__ == "__main__":
    unittest.main()
