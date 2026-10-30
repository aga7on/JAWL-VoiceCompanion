import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from jawl_voicecompanion.yamnet_soundscape import YamnetSoundscapeDetector  # noqa: E402


class _FakeYamnet:
    def __init__(self, labels, active):
        self.labels = labels
        self.active = active

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _outputs, _inputs):
        scores = np.zeros((3, len(self.labels)), dtype=np.float32)
        scores[:, self.labels.index("Music")] = self.active.get("Music", 0.0)
        scores[:, self.labels.index("Speech")] = self.active.get("Speech", 0.0)
        for label, score in self.active.items():
            if label in self.labels:
                scores[:, self.labels.index(label)] = score
        return [scores]


class _SequenceMusicYamnet(_FakeYamnet):
    def __init__(self, labels, music_scores):
        super().__init__(labels, {})
        self.music_scores = list(music_scores)
        self.calls = 0

    def run(self, _outputs, _inputs):
        scores = np.zeros((3, len(self.labels)), dtype=np.float32)
        value = self.music_scores[min(self.calls, len(self.music_scores) - 1)]
        self.calls += 1
        scores[:, self.labels.index("Music")] = value
        scores[:, self.labels.index("Speech")] = 0.01
        return [scores]


class YamnetSoundscapeTests(unittest.TestCase):
    def build(self, active):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        model_dir = Path(temp.name)
        labels = [
            "Music", "Speech", "Silence", "Background music", "Saxophone",
            "Electronic music", "Explosion", "Synthesizer", "Crying, sobbing",
            "Baby cry, infant cry", "Aircraft", "Helicopter", "Chainsaw", "Rain",
            "Rain on surface", "Clock", "Tick-tock", "Dog",
            "Crowing, cock-a-doodle-doo", "Waves, surf", "Ocean", "Sneeze", "Fire",
            "Engine", "Vehicle", "Motor vehicle (road)",
        ]
        (model_dir / "yamnet_class_map.csv").write_text(
            "index,mid,display_name\n" + "".join(f'{i},/{i},"{label}"\n' for i, label in enumerate(labels)),
            encoding="utf-8",
        )
        return YamnetSoundscapeDetector(model_dir, session=_FakeYamnet(labels, active))

    @staticmethod
    def pcm(duration_s=4.0, amplitude=0.25):
        samples = np.full(int(16000 * duration_s), int(amplitude * 32767), dtype="<i2")
        return samples.tobytes()

    def test_persistent_music_is_emitted_with_only_stable_strong_tags(self):
        detector = self.build({"Music": 0.82, "Speech": 0.01, "Saxophone": 0.24, "Electronic music": 0.04})
        result = detector.describe(self.pcm(), sample_rate=16000, channels=1, clip_id="music")
        self.assertEqual(result["kind"], "music")
        self.assertEqual(result["music_windows"], result["windows"])
        self.assertEqual(result["tags"], ["Saxophone"])
        self.assertEqual(result["mood"], "")
        self.assertFalse(result["calibrated"])
        self.assertFalse(result["raw_audio_persisted"])

    def test_short_clip_and_speech_only_abstain(self):
        short_music = self.build({"Music": 0.99})
        short = short_music.describe(self.pcm(2.0), sample_rate=16000, channels=1)
        self.assertEqual(short["kind"], "unknown")

        speech = self.build({"Music": 0.05, "Speech": 0.95})
        result = speech.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["tags"], [])
        self.assertEqual(result["music_score_max"], 0.05)
        self.assertEqual(result["music_score_median"], 0.05)

    def test_unknown_music_probe_preserves_scores_for_gate_diagnostics(self):
        detector = self.build({"Music": 0.22, "Speech": 0.03})
        result = detector.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 0)
        self.assertEqual(result["music_score_max"], 0.22)
        self.assertEqual(result["music_score_median"], 0.22)

    def test_recurrent_sound_event_is_emitted_separately_from_music(self):
        detector = self.build({"Music": 0.05, "Speech": 0.01, "Explosion": 0.16, "Synthesizer": 0.34})
        result = detector.describe(self.pcm(4.0), sample_rate=16000, channels=1)

        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 0)
        self.assertEqual(result["event_candidates"], [{
            "label": "Explosion", "score": 0.16, "window_hits": 3,
            "windows": 3, "calibrated": False,
        }])

    def test_weak_or_musical_class_is_not_emitted_as_sound_event(self):
        detector = self.build({"Music": 0.05, "Speech": 0.01, "Explosion": 0.09, "Synthesizer": 0.34})
        result = detector.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["event_candidates"], [])

        below_gate = self.build({"Music": 0.05, "Speech": 0.01, "Explosion": 0.149})
        result = below_gate.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["event_candidates"], [])

    def test_generic_engine_and_vehicle_classes_are_not_published(self):
        detector = self.build({"Music": 0.05, "Speech": 0.01, "Engine": 0.8, "Vehicle": 0.7})
        result = detector.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["event_candidates"], [])

    def test_specific_audio_scene_classes_are_available_as_unverified_candidates(self):
        for label in (
            "Baby cry, infant cry", "Helicopter", "Chainsaw", "Rain", "Tick-tock",
            "Dog", "Crowing, cock-a-doodle-doo", "Waves, surf", "Sneeze", "Fire",
        ):
            with self.subTest(label=label):
                detector = self.build({"Music": 0.05, "Speech": 0.01, label: 0.72})
                result = detector.describe(self.pcm(4.0), sample_rate=16000, channels=1)
                emitted = [item["label"] for item in result["event_candidates"]]
                self.assertIn(label, emitted)
                self.assertTrue(all(not item["calibrated"] for item in result["event_candidates"]))

    def test_music_gate_abstains_below_the_current_score_threshold(self):
        borderline = self.build({"Music": 0.34, "Speech": 0.01})
        result = borderline.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 0)
        self.assertEqual(result["music_hypothesis"]["raw_score_max"], 0.34)
        self.assertFalse(result["music_hypothesis"]["verified"])
        self.assertFalse(result["music_hypothesis"]["calibrated"])

        accepted = self.build({"Music": 0.36, "Speech": 0.01})
        result = accepted.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "music")
        self.assertEqual(result["music_windows"], result["windows"])
        self.assertIsNone(result["music_hypothesis"])

    def test_single_two_tone_like_music_peak_is_only_a_tonal_hypothesis(self):
        detector = self.build({})
        detector.session = _SequenceMusicYamnet(
            detector.labels,
            [0.3822, 0.3021, 0.3021],
        )
        result = detector.describe(self.pcm(4.0), sample_rate=16000, channels=1)

        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 1)
        self.assertEqual(result["music_score_max"], 0.3822)
        self.assertEqual(result["music_score_median"], 0.3021)
        self.assertFalse(result["music_hypothesis"]["verified"])
        self.assertFalse(result["music_hypothesis"]["calibrated"])

    def test_digital_silence_never_becomes_music_even_with_high_model_score(self):
        detector = self.build({"Music": 0.99})
        silent = np.zeros(4 * 16000, dtype="<i2").tobytes()
        result = detector.describe(silent, sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 0)
        self.assertIsNone(result["music_hypothesis"])

    def test_requires_cpu_execution_provider(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        model_dir = Path(temp.name)
        (model_dir / "yamnet_class_map.csv").write_text(
            'index,mid,display_name\n0,/m/music,"Music"\n1,/m/speech,"Speech"\n', encoding="utf-8"
        )

        class GpuSession(_FakeYamnet):
            def get_providers(self):
                return ["CUDAExecutionProvider"]

        with self.assertRaisesRegex(RuntimeError, "CPUExecutionProvider"):
            YamnetSoundscapeDetector(model_dir, session=GpuSession(["Music", "Speech"], {}))


if __name__ == "__main__":
    unittest.main()
