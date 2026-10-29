import base64
import json
import math
import sys
import time
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.gemma_sensory import (  # noqa: E402
    GemmaSensoryClient,
    LatestObservation,
    build_request_payload,
    normalize_observation,
    pcm16_to_wav,
)


class GemmaSensoryContractTests(unittest.TestCase):
    def test_request_contains_image_audio_and_no_thinking(self):
        image = b"\xff\xd8fake-jpeg"
        audio = b"RIFFfake-wav"
        payload = build_request_payload("gemma4-e4b", image_bytes=image, audio_wav_bytes=audio)
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(payload["max_tokens"], 160)
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        content = payload["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[2]["type"], "input_audio")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_observation_is_normalized_and_evidence_is_code_owned(self):
        frame = normalize_observation(
            {
                "scene": "  человек закрыл ноутбук  ",
                "changes": ["экран погас"],
                "audio": {
                    "speech": "на сегодня хватит",
                    "speech_lang": "ru",
                    "events": ["щелчок"],
                    "music": "тихая музыка",
                    "voice_tone": "спокойный",
                    "uncertain": ["причина ухода"],
                },
                "uncertainty": 0.4,
            },
            source="combined",
            observed_interval=[100.0, 104.0],
            observed_at=100.0,
            processed_at=104.0,
            model="gemma4-e4b",
            quant="q2",
        )
        self.assertEqual(frame["scene"], "человек закрыл ноутбук")
        self.assertEqual(frame["source"], "combined")
        self.assertEqual(frame["age_ms"], 4000.0)
        self.assertTrue(frame["schema_valid"])
        self.assertFalse(frame["raw_media_persisted"])
        self.assertEqual(frame["audio"]["speech_lang"], "ru")

    def test_invalid_payload_becomes_unknown_but_marks_schema_invalid(self):
        frame = normalize_observation(
            {"scene": 7},
            source="audio",
            observed_interval=[0, 1],
            observed_at=0,
            processed_at=1,
            model="gemma4-e4b",
            quant="q4",
        )
        self.assertFalse(frame["schema_valid"])
        self.assertEqual(frame["scene"], "7")
        self.assertEqual(frame["audio"]["speech_lang"], "unknown")

    def test_pcm_to_wav_normalizes_stereo_48k(self):
        stereo = b"\x00\x00\x00\x00" * 48000
        wav = pcm16_to_wav(stereo, 48000, 2)
        with wave.open(__import__("io").BytesIO(wav), "rb") as handle:
            self.assertEqual(handle.getnchannels(), 1)
            self.assertEqual(handle.getframerate(), 16000)
            self.assertEqual(handle.getsampwidth(), 2)

    def test_latest_observation_keeps_only_newest(self):
        slot = LatestObservation()
        slot.update_image(b"first", time.time())
        slot.update_image(b"second", time.time())
        item = slot.take(max_age_s=10)
        self.assertEqual(item["image"], b"second")
        self.assertEqual(item["source"], "screen")
        self.assertIsNone(slot.take(max_age_s=10))


class GemmaSensoryClientTests(unittest.TestCase):
    def test_client_rejects_http_errors_without_raising(self):
        client = GemmaSensoryClient("http://127.0.0.1:1", timeout=1)
        result = client.describe(image_bytes=b"\xff\xd8x")
        self.assertIn(result["status"], {"request_error", "http_error"})
        self.assertIn("total_ms", result)


if __name__ == "__main__":
    unittest.main()
