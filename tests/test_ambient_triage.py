import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_triage import (  # noqa: E402
    TRIAGE_SCHEMA,
    AmbientTriageUnavailable,
    OllamaTriageProvider,
    OpenAICompatibleTriageProvider,
    validate_triage_result,
)


class _MockResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AmbientTriageTests(unittest.TestCase):
    def test_schema_allows_up_to_256_source_event_ids(self):
        self.assertEqual(TRIAGE_SCHEMA["properties"]["source_event_ids"]["maxItems"], 256)

    def test_validate_triage_result_preserves_40_event_ids(self):
        event_ids = [f"e{i}" for i in range(40)]
        result = {
            "importance": "retain",
            "summary": "Coalesced 40 observations into an episode",
            "topics": ["batch"],
            "confidence": 0.85,
            "source": "mixed",
            "source_event_ids": event_ids,
        }
        validated = validate_triage_result(result, set(event_ids))
        self.assertEqual(len(validated["source_event_ids"]), 40)
        self.assertEqual(validated["source_event_ids"], event_ids)

    def test_validate_triage_result_rejects_unknown_event(self):
        event_ids = ["e1", "e2"]
        result = {
            "importance": "retain",
            "summary": "Valid summary",
            "topics": ["test"],
            "confidence": 0.8,
            "source": "system_audio",
            "source_event_ids": ["e1", "unknown_e3"],
        }
        with self.assertRaises(AmbientTriageUnavailable):
            validate_triage_result(result, set(event_ids))

    def test_validate_triage_result_rejects_duplicate_events(self):
        event_ids = ["e1", "e2"]
        result = {
            "importance": "retain",
            "summary": "Valid summary",
            "topics": ["test"],
            "confidence": 0.8,
            "source": "system_audio",
            "source_event_ids": ["e1", "e1"],
        }
        with self.assertRaises(AmbientTriageUnavailable):
            validate_triage_result(result, set(event_ids))

    def test_ollama_provider_triage_with_40_observations(self):
        observations = [
            {
                "event_id": f"e{i}",
                "payload": {
                    "stream": "system_audio",
                    "text": f"Phrase {i}",
                    "confidence": 0.9,
                    "verified": False,
                },
            }
            for i in range(40)
        ]
        source_event_ids = [f"e{i}" for i in range(40)]
        mock_chat_response = {
            "message": {
                "content": json.dumps(
                    {
                        "importance": "retain",
                        "summary": "Summarized 40 phrases",
                        "topics": ["speech"],
                        "confidence": 0.88,
                        "source": "system_audio",
                        "source_event_ids": source_event_ids,
                    }
                )
            }
        }

        def fake_opener(request, timeout=None):
            return _MockResponse(mock_chat_response)

        provider = OllamaTriageProvider("qwen2.5:3b", opener=fake_opener)
        triage_out = provider.triage(observations)
        self.assertEqual(len(triage_out["source_event_ids"]), 40)
        self.assertEqual(triage_out["source_event_ids"], source_event_ids)

    def test_openai_compatible_provider_triage_with_40_observations(self):
        observations = [
            {
                "event_id": f"e{i}",
                "payload": {
                    "stream": "screen",
                    "text": f"Visual observation {i}",
                    "confidence": 0.8,
                    "verified": True,
                },
            }
            for i in range(40)
        ]
        source_event_ids = [f"e{i}" for i in range(40)]
        mock_api_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "importance": "promote_candidate",
                                "summary": "Detected 40 visual changes",
                                "topics": ["screen"],
                                "confidence": 0.92,
                                "source": "screen",
                                "source_event_ids": source_event_ids,
                            }
                        )
                    }
                }
            ]
        }

        def fake_opener(request, timeout=None):
            return _MockResponse(mock_api_response)

        provider = OpenAICompatibleTriageProvider(
            "http://127.0.0.1:8080", "model-1", opener=fake_opener
        )
        triage_out = provider.triage(observations)
        self.assertEqual(len(triage_out["source_event_ids"]), 40)
        self.assertEqual(triage_out["source_event_ids"], source_event_ids)


if __name__ == "__main__":
    unittest.main()
