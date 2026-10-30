import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.audio_understanding import (  # noqa: E402
    AUDIO_DESCRIPTION_SCHEMA,
    AudioDescriptionService,
    AudioDescriptionUnavailable,
    safe_detailed_audio_claim,
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

    def test_unknown_is_an_abstention_and_discards_music_claims(self):
        result = validate_audio_description(
            {
                "kind": "unknown",
                "description": "Energetic cinematic music, 120 BPM in C major.",
                "tags": ["music", "energetic", "120 BPM", "C major"],
                "mood": "tense",
                "confidence": 0.99,
                "duration_seconds": 1,
            },
            clip_id="silence",
            duration_seconds=1,
        )
        self.assertEqual(result["description"], "No reliable audio event detected.")
        self.assertEqual(result["tags"], [])
        self.assertEqual(result["mood"], "")

    def test_unknown_keeps_bounded_ranked_hypotheses_separate_from_facts(self):
        result = validate_audio_description(
            {
                "kind": "unknown",
                "description": "untrusted free-form claim",
                "tags": ["music"],
                "mood": "tense",
                "confidence": 0.99,
                "duration_seconds": 1,
                "candidate_hypotheses": [{
                    "category": "music_genre",
                    "candidates": [
                        {"label": "cinematic_orchestral", "similarity": 0.68912},
                        {"label": "hip_hop_beat", "similarity": 0.6778},
                    ],
                }],
                "ignored": "must be dropped",
            },
            clip_id="ambiguous-audio",
            duration_seconds=1,
        )

        self.assertEqual(result["description"], "No reliable audio event detected.")
        self.assertEqual(result["tags"], [])
        self.assertEqual(result["mood"], "")
        self.assertEqual(result["candidate_hypotheses"][0]["category"], "music_genre")
        self.assertEqual(
            result["candidate_hypotheses"][0]["candidates"][0],
            {"label": "cinematic_orchestral", "similarity": 0.6891},
        )
        self.assertNotIn("ignored", result)

    def test_invalid_candidate_hypotheses_fail_closed(self):
        with self.assertRaises(AudioDescriptionUnavailable):
            validate_audio_description(
                {
                    "kind": "unknown", "description": "unknown", "tags": [], "mood": "",
                    "confidence": 0.0, "duration_seconds": 1,
                    "candidate_hypotheses": [{"category": "genre", "candidates": [
                        {"label": "jazz", "similarity": 2.0},
                    ]}],
                },
                clip_id="invalid-hypothesis",
                duration_seconds=1,
            )

    def test_speech_noise_mixed_and_music_claim_projection(self):
        def observation(*, speech, music, rms=-20.0):
            return SimpleNamespace(
                level2={"dsp": {"is_speech_likely": speech, "is_music_likely": music,
                                 "rms_dbfs": rms, "duration_s": 1.0, "bpm": 120,
                                 "pulse_clarity": 0.8, "key": "C", "mode": "major"}},
                level1={"genre": "energetic_action_music", "genre_confident": True,
                        "mood": "tense", "mood_confident": True},
                description="raw classifier text",
            )

        # A16-noise-only-negative: both DSP flags true, RMS -35.1 and pulse
        # clarity 1.0. Without ASR text, neither speech nor music is established.
        overlap = safe_detailed_audio_claim(observation(speech=True, music=True, rms=-35.1))
        self.assertEqual(overlap["kind"], "unknown")
        self.assertEqual(overlap["tags"], [])
        self.assertEqual(overlap["mood"], "")
        self.assertEqual(overlap["confidence"], 0.0)
        self.assertNotIn("rhythmic", overlap["description"])

        transcript = safe_detailed_audio_claim(
            observation(speech=True, music=True, rms=-35.1), transcript="Привет"
        )
        self.assertEqual(transcript["kind"], "speech")
        self.assertEqual(transcript["description"], "Привет")
        self.assertEqual(transcript["tags"], [])

        noise = safe_detailed_audio_claim(observation(speech=False, music=False))
        self.assertEqual(noise["kind"], "sound")
        self.assertEqual(noise["tags"], [])
        self.assertNotIn("raw classifier", noise["description"])

        silence = safe_detailed_audio_claim(observation(speech=False, music=False, rms=-80))
        self.assertEqual(silence["kind"], "unknown")
        self.assertEqual(silence["tags"], [])

        music = safe_detailed_audio_claim(observation(speech=False, music=True))
        self.assertEqual(music["kind"], "sound")
        self.assertEqual(music["tags"], [])
        self.assertIn("Possible rhythmic sound", music["description"])
        self.assertEqual(music["confidence"], 0.0)

    def test_mixed_is_rejected_without_independent_overlap_detector(self):
        with self.assertRaises(AudioDescriptionUnavailable):
            validate_audio_description(
                {"kind": "mixed", "description": "music and speech", "tags": ["music"],
                 "mood": "tense", "confidence": 0.9},
                clip_id="mixed", duration_seconds=1,
            )

    def test_non_music_kinds_cannot_carry_model_music_or_sfx_text(self):
        for kind in ("speech", "sound", "unknown"):
            result = validate_audio_description(
                {"kind": kind, "description": "dramatic tension music, 120 BPM, C major",
                 "tags": ["dramatic_tension_sfx", "120 BPM"], "mood": "tense",
                 "confidence": 0.99},
                clip_id=kind, duration_seconds=1,
            )
            self.assertEqual(result["tags"], [])
            self.assertEqual(result["mood"], "")
            self.assertEqual(result["confidence"], 0.0)
            self.assertNotIn("dramatic", result["description"])


if __name__ == "__main__":
    unittest.main()
