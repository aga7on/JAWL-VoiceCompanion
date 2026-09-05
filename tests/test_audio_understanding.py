import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.audio_understanding import (  # noqa: E402
    AUDIO_DESCRIPTION_SCHEMA,
    AudioDescriptionService,
    AudioDescriptionUnavailable,
    validate_audio_description,
)


class _Provider:
    name = "fake-audio-captioner"

    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "kind": "music",
            "description": "Короткий музыкальный фрагмент с ударными и синтезатором.",
            "tags": ["музыка", "ударные", "синтезатор"],
            "mood": "энергичное",
            "confidence": 0.88,
            "duration_seconds": 999,
            "secret": "must be dropped",
        }

    def describe(self, pcm16, *, sample_rate, channels, clip_id):
        self.calls.append((pcm16, sample_rate, channels, clip_id))
        return self.result


class AudioUnderstandingTests(unittest.TestCase):
    def test_service_bounds_input_and_output_without_persisting_pcm(self):
        provider = _Provider()
        service = AudioDescriptionService(provider)
        pcm = b"\x00\x00" * 1600
        result = service.describe(pcm, sample_rate=16000, channels=1, clip_id="clip-1")
        self.assertEqual(result["kind"], "music")
        self.assertEqual(result["duration_seconds"], 0.1)
        self.assertFalse(result["raw_audio_persisted"])
        self.assertNotIn("secret", result)
        self.assertEqual(provider.calls[0][1:], (16000, 1, "clip-1"))

    def test_invalid_provider_result_fails_closed(self):
        provider = _Provider({
            "kind": "not-a-kind",
            "description": "bad",
            "tags": [],
            "mood": "",
            "confidence": 0.5,
        })
        with self.assertRaises(AudioDescriptionUnavailable):
            AudioDescriptionService(provider).describe(
                b"\x00\x00" * 1600, sample_rate=16000, channels=1, clip_id="bad"
            )

    def test_long_clip_is_rejected_before_provider_call(self):
        provider = _Provider()
        service = AudioDescriptionService(provider, max_clip_seconds=2)
        with self.assertRaises(ValueError):
            service.describe(b"\x00\x00" * 16000 * 3, sample_rate=16000, channels=1, clip_id="long")
        self.assertFalse(provider.calls)

    def test_schema_is_strict_and_validation_uses_explicit_clip_duration(self):
        self.assertTrue(AUDIO_DESCRIPTION_SCHEMA["additionalProperties"] is False)
        result = validate_audio_description(
            {
                "kind": "sound",
                "description": "Слышен короткий сигнал.",
                "tags": ["сигнал"],
                "mood": "",
                "confidence": 0.7,
                "duration_seconds": 99,
            },
            clip_id="sound-1",
            duration_seconds=1.25,
        )
        self.assertEqual(result["duration_seconds"], 1.25)
        self.assertEqual(result["clip_id"], "sound-1")


if __name__ == "__main__":
    unittest.main()
