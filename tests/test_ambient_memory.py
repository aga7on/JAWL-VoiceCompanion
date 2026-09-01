import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
from jawl_voicecompanion.ambient_triage import (  # noqa: E402
    OllamaTriageProvider,
    OpenAICompatibleTriageProvider,
)


class _FakeTriage:
    name = "fake"

    def triage(self, observations):
        return {
            "importance": "retain",
            "summary": "Сжатый контекст из наблюдения",
            "topics": ["context"],
            "confidence": 0.91,
            "source": "system_audio",
            "source_event_ids": [observations[0]["event_id"]],
        }


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        import json

        return json.dumps(self.payload).encode("utf-8")


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

    def test_explicit_model_provider_is_delayed_and_provenance_is_preserved(self):
        memory = AmbientMemoryBuffer(enabled=True, triage_provider=_FakeTriage())
        memory.ingest_system_audio("В игре объявлен новый контекст", event_id="audio-provider", now=10)
        result = memory.triage(now=20)
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["provider"], "fake")
        self.assertEqual(result["episodes"][0]["payload"]["triage_provider"], "fake")
        self.assertEqual(result["episodes"][0]["payload"]["source_event_ids"], ["audio-provider"])

    def test_invalid_provider_output_fails_closed_and_keeps_observation_pending(self):
        class BadProvider:
            name = "bad"

            def triage(self, _observations):
                return {"importance": "retain", "summary": "unknown provenance"}

        memory = AmbientMemoryBuffer(enabled=True, triage_provider=BadProvider())
        memory.ingest_visual("Контекст экрана", event_id="bad-provider", now=10)
        result = memory.triage(now=20)
        self.assertEqual(result["status"], "provider_error")
        self.assertEqual(result["provider"], "bad")
        self.assertEqual(memory.state(now=20)["episode_count"], 0)
        self.assertEqual(memory.triage(now=21)["status"], "provider_error")

    def test_ollama_provider_uses_cpu_and_structured_output(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return _Response(
                {
                    "message": {
                        "content": '{"importance":"retain","summary":"Наблюдение сжато","topics":["context"],"confidence":0.8,"source":"system_audio","source_event_ids":["ollama-1"]}'
                    }
                }
            )

        provider = OllamaTriageProvider("triage-model", opener=opener)
        result = provider.triage(
            [
                {
                    "event_id": "ollama-1",
                    "payload": {
                        "stream": "system_audio",
                        "text": "Важный контекст",
                        "confidence": 0.8,
                    },
                }
            ]
        )
        self.assertEqual(result["importance"], "retain")
        self.assertEqual(len(requests), 1)
        import json

        body = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertEqual(body["options"]["num_gpu"], 0)
        self.assertEqual(body["format"]["type"], "object")
        self.assertEqual(body["keep_alive"], 0)

    def test_openai_compatible_provider_uses_schema_and_validates_provenance(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return _Response({
                "choices": [{"message": {"content":
                    '{"importance":"retain","summary":"Compact observation","topics":["context"],'
                    '"confidence":0.75,"source":"system_audio","source_event_ids":["compat-1"]}'
                }}]
            })

        provider = OpenAICompatibleTriageProvider(
            "http://127.0.0.1:8981/v1", "Bonsai-1.7B", api_key="test-key", opener=opener,
        )
        result = provider.triage([{
            "event_id": "compat-1",
            "payload": {"stream": "system_audio", "text": "A bounded observation", "confidence": 0.8},
        }])
        self.assertEqual(result["importance"], "retain")
        self.assertEqual(requests[0][0].full_url, "http://127.0.0.1:8981/v1/chat/completions")
        self.assertEqual(requests[0][0].get_header("Authorization"), "Bearer test-key")
        body = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertEqual(body["response_format"]["type"], "json_schema")


if __name__ == "__main__":
    unittest.main()
