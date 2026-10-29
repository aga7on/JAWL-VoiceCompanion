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


class YamnetSoundscapeTests(unittest.TestCase):
    def build(self, active):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        model_dir = Path(temp.name)
        labels = ["Music", "Speech", "Silence", "Background music", "Saxophone", "Electronic music"]
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

    def test_music_gate_abstains_below_the_current_score_threshold(self):
        borderline = self.build({"Music": 0.34, "Speech": 0.01})
        result = borderline.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 0)

        accepted = self.build({"Music": 0.36, "Speech": 0.01})
        result = accepted.describe(self.pcm(4.0), sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "music")
        self.assertEqual(result["music_windows"], result["windows"])

    def test_digital_silence_never_becomes_music_even_with_high_model_score(self):
        detector = self.build({"Music": 0.99})
        silent = np.zeros(4 * 16000, dtype="<i2").tobytes()
        result = detector.describe(silent, sample_rate=16000, channels=1)
        self.assertEqual(result["kind"], "unknown")
        self.assertEqual(result["music_windows"], 0)

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
