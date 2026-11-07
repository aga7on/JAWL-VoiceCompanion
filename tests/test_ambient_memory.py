import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer, AmbientTriageScheduler  # noqa: E402
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


class _IgnoreTriage:
    name = "ignore-model"

    def triage(self, observations):
        return {
            "importance": "ignore",
            "summary": "The model attempted to suppress this observation.",
            "topics": ["guard"],
            "confidence": 0.99,
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
    def test_audio_timestamp_sources_survive_normalization_and_triage(self):
        memory = AmbientMemoryBuffer(enabled=True)
        for index, source in enumerate(("host_callback_receipt_monotonic", "host_pipe_receipt_monotonic",
                                        "consumer_receipt_monotonic")):
            result = memory.ingest_system_audio("В игре начался новый квест", event_id=f"src-{index}",
                                                timestamp_source=source, now=100 + index)
            self.assertEqual(result["observation"]["payload"]["timestamp_source"], source)
        result = memory.ingest_system_audio("Ещё одна фраза из игры", event_id="legacy", now=104)
        self.assertNotIn("timestamp_source", result["observation"]["payload"])
        episode = memory.triage(now=105)["episodes"][0]["payload"]
        self.assertEqual(set(episode["timestamp_sources"]), {
            "host_callback_receipt_monotonic", "host_pipe_receipt_monotonic",
            "consumer_receipt_monotonic", "unknown",
        })

    def test_timestamp_source_roundtrip_and_unrecognized_value(self):
        original = AmbientMemoryBuffer(enabled=True)
        record = original.ingest_system_audio("В игре звучит речь", event_id="timed",
                   timestamp_source="consumer_receipt_monotonic", now=100)["observation"]
        # AmbientMemoryBuffer is in-memory; this exercises its JSON event
        # normalization contract, not a persistence/reload implementation.
        decoded = json.loads(json.dumps(record, ensure_ascii=False))
        recreated = AmbientMemoryBuffer(enabled=True)
        result = recreated.ingest(decoded, now=101)
        self.assertEqual(result["observation"]["payload"]["timestamp_source"], "consumer_receipt_monotonic")
        result = recreated.ingest_system_audio("Другая игровая реплика", event_id="bad",
                                             timestamp_source="imaginary_hardware_clock", now=102)
        self.assertEqual(result["observation"]["payload"]["timestamp_source"], "unknown")

    def test_audio_description_preserves_timestamp_source(self):
        memory = AmbientMemoryBuffer(enabled=True)
        result = memory.ingest_audio_description({
            "schema_version": 1, "clip_id": "music-clip", "kind": "music",
            "description": "Слышна тихая музыка", "tags": [], "mood": "",
            "confidence": 0.7, "duration_seconds": 2.0,
        }, timestamp_source="host_pipe_receipt_monotonic", now=100)
        self.assertEqual(result["status"], "retained")
        self.assertEqual(result["observation"]["payload"]["timestamp_source"], "host_pipe_receipt_monotonic")

    def test_provider_triage_keeps_audio_timestamp_sources(self):
        memory = AmbientMemoryBuffer(enabled=True, triage_provider=_FakeTriage())
        memory.ingest_system_audio("В игре появился важный квест", event_id="source",
                                   timestamp_source="host_callback_receipt_monotonic", now=100)
        episode = memory.triage(now=101)["episodes"][0]
        self.assertEqual(episode["payload"]["timestamp_sources"], ["host_callback_receipt_monotonic"])

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
        self.assertEqual(episode["payload"]["importance"], "retain")
        self.assertFalse(episode["payload"]["verified"])
        self.assertEqual(episode["payload"]["source"], "mixed")
        self.assertEqual(episode["payload"]["source_event_ids"], ["audio-1", "screen-1"])
        self.assertFalse(episode["payload"]["raw_audio_persisted"])
        self.assertFalse(episode["payload"]["raw_frame_persisted"])

    def test_audio_description_is_text_only_ambient_evidence(self):
        memory = AmbientMemoryBuffer(enabled=True)
        result = memory.ingest_audio_description({
            "schema_version": 1,
            "clip_id": "music-1",
            "kind": "music",
            "description": "Энергичный фрагмент с ударными.",
            "tags": ["музыка", "ударные"],
            "mood": "энергичное",
            "confidence": 0.86,
            "duration_seconds": 4.5,
        }, event_id="music-description")
        self.assertEqual(result["status"], "retained")
        payload = memory.observations()[0]["payload"]
        self.assertEqual(payload["audio_kind"], "music")
        self.assertEqual(payload["tags"], ["музыка", "ударные"])
        self.assertEqual(payload["duration_seconds"], 4.5)
        self.assertFalse(payload["raw_audio_persisted"])

    def test_ambient_ingest_sanitizes_unknown_mixed_speech_and_sound_bypasses(self):
        for index, kind in enumerate(("unknown", "mixed", "speech", "sound")):
            memory = AmbientMemoryBuffer(enabled=True)
            result = memory.ingest({
                "schema_version": 1,
                "event_id": f"unsafe-audio-{index}",
                "session_id": "test",
                "type": "AMBIENT_AUDIO_OBSERVATION",
                "payload": {
                    "text": "energetic cinematic music, 120 BPM, tense",
                    "confidence": 0.99,
                    "audio_kind": kind,
                    "tags": ["music", "120 BPM", "C major"],
                    "mood": "tense",
                },
            })
            self.assertEqual(result["status"], "retained")
            payload = memory.observations()[0]["payload"]
            self.assertNotIn("energetic cinematic music", payload["text"].lower())
            self.assertEqual(payload["tags"], [])
            self.assertNotIn("mood", payload)
            self.assertEqual(payload["confidence"], 0.0)
            if kind == "mixed":
                self.assertEqual(payload["audio_kind"], "unknown")

    def test_tentative_rhythm_cue_stays_machine_readable_as_sound(self):
        from jawl_voicecompanion.audio_understanding import TENTATIVE_RHYTHM_CUE
        from jawl_voicecompanion.perception_fusion import PerceptionFusion

        memory = AmbientMemoryBuffer(enabled=True)
        result = memory.ingest_audio_description({
            "kind": "sound", "description": TENTATIVE_RHYTHM_CUE,
            "tags": [], "mood": "", "confidence": 0.0, "duration_seconds": 1,
        }, event_id="tentative-rhythm")
        self.assertEqual(result["status"], "retained")
        payload = memory.observations()[0]["payload"]
        self.assertEqual(payload["audio_kind"], "sound")
        self.assertEqual(payload["text"], TENTATIVE_RHYTHM_CUE)
        self.assertEqual(payload["confidence"], 0.0)
        self.assertEqual(payload["tags"], [])

        fusion = PerceptionFusion()
        fusion.note("sound", payload["text"], now=10)
        composed = fusion.compose(now=11)
        self.assertIn("not independently verified", composed)
        self.assertNotIn("music:", composed.lower())

    def test_private_duplicate_and_unknown_events_are_not_retained(self):
        memory = AmbientMemoryBuffer(enabled=True)
        private = memory.ingest_system_audio("Password token: secret", event_id="private", now=1)
        sensitive_window = memory.ingest_visual(
            "На экране обычный текст", source_app="Password Manager", event_id="sensitive-window", now=1
        )
        unknown = memory.ingest({"type": "USER_FINAL", "payload": {"text": "not ambient"}}, now=1)
        first = memory.ingest_visual("обычное наблюдение", event_id="same", now=1)
        duplicate = memory.ingest_visual("обычное наблюдение", event_id="same", now=2)
        self.assertEqual(private["status"], "suppressed")
        self.assertEqual(sensitive_window, {"status": "suppressed", "reason": "ambient_source_sensitive"})
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

    def test_unscored_asr_remains_unverified_even_when_salient(self):
        memory = AmbientMemoryBuffer(enabled=True, triage_provider=_IgnoreTriage())
        memory.ingest_system_audio(
            "Важный error: deadline сегодня, запомни.",
            confidence=0.9,
            event_id="guarded-important",
            now=10,
        )
        result = memory.triage(now=20)
        self.assertEqual(result["status"], "processed")
        payload = result["episodes"][0]["payload"]
        self.assertEqual(payload["importance"], "retain")
        self.assertFalse(payload["verified"])
        self.assertTrue(payload["summary"].startswith("Непроверенная ASR-расшифровка:"))

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

    def test_triage_scheduler_is_opt_in_and_stops_without_duplicate_workers(self):
        import threading

        completed = threading.Event()

        class Memory:
            def __init__(self):
                self.calls = 0

            def triage(self):
                self.calls += 1
                completed.set()
                return {"status": "processed", "episodes": [{"id": self.calls}]}

        memory = Memory()
        scheduler = AmbientTriageScheduler(memory, interval_seconds=1)
        self.assertFalse(scheduler.state()["running"])
        scheduler.start()
        scheduler.start()
        self.assertTrue(completed.wait(2.5))
        self.assertEqual(memory.calls, 1)
        self.assertEqual(scheduler.state()["status"], "processed")
        stopped = scheduler.stop()
        self.assertFalse(stopped["running"])

    def test_background_triage_keeps_unverified_evidence_as_candidate(self):
        import time

        memory = AmbientMemoryBuffer(enabled=True)
        memory.ingest_system_audio("В игре появилась красная дверь", event_id="audio-evidence")
        memory.ingest_visual("На экране видна дверь", event_id="visual-evidence")
        scheduler = AmbientTriageScheduler(memory, interval_seconds=1)
        try:
            scheduler.start()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not memory.episodes():
                time.sleep(0.05)
            episodes = memory.episodes()
            self.assertEqual(len(episodes), 1)
            self.assertFalse(episodes[0]["payload"]["verified"])
            self.assertEqual(set(episodes[0]["payload"]["source_event_ids"]), {"audio-evidence", "visual-evidence"})
            self.assertEqual(memory.state()["handed_off_count"], 0)
        finally:
            scheduler.stop()

    def test_forty_observations_retain_full_provenance_and_cascade_redact(self):
        memory = AmbientMemoryBuffer(enabled=True, max_observations=256)
        for i in range(40):
            memory.ingest_system_audio(
                f"observation phrase {i}",
                confidence=0.8,
                event_id=f"e{i}",
            )
        result = memory.triage(max_items=256)
        self.assertEqual(result["status"], "processed")
        episodes = memory.episodes()
        self.assertEqual(len(episodes), 1)
        source_ids = episodes[0]["payload"]["source_event_ids"]
        self.assertEqual(len(source_ids), 40)
        self.assertEqual(source_ids, [f"e{i}" for i in range(40)])

        # Redact e39: episode containing phrase 39 must be completely redacted
        redact_res = memory.redact(["e39"])
        self.assertEqual(redact_res["status"], "redacted")
        self.assertEqual(redact_res["episodes"], 1)
        self.assertEqual(redact_res["observations"], 1)
        self.assertEqual(len(memory.episodes()), 0)

    def test_canonical_memory_keys_cascade_redact_episode(self):
        # 1. Test promoted_memory_key cascade
        memory = AmbientMemoryBuffer(enabled=True)
        memory.ingest_system_audio("quest completed remember this", confidence=0.9, event_id="ev-prom")
        memory.triage()
        episode_id = memory.episodes()[0]["event_id"]
        memory.mark_promoted(episode_id, "canon-promoted-key-1")
        self.assertEqual(len(memory.episodes()), 1)
        redacted = memory.redact(["canon-promoted-key-1"])
        self.assertEqual(redacted["episodes"], 1)
        self.assertEqual(len(memory.episodes()), 0)

        # 2. Test handed_off_memory_key cascade
        memory.ingest_system_audio("second dialogue important context", confidence=0.9, event_id="ev-hand")
        memory.triage()
        episode_id2 = memory.episodes()[0]["event_id"]
        memory.mark_handed_off(episode_id2, "canon-handed-off-key-2")
        self.assertEqual(len(memory.episodes()), 1)
        redacted2 = memory.redact(["canon-handed-off-key-2"])
        self.assertEqual(redacted2["episodes"], 1)
        self.assertEqual(len(memory.episodes()), 0)


if __name__ == "__main__":
    unittest.main()
