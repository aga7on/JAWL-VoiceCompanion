"""Deterministic contracts for positive-scene and coarse-to-fine audio analysis."""
from __future__ import annotations

import ast
import hashlib
import io
import math
import re
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.eg2_describer import (  # noqa: E402
    AUDIO_SCENE_BANK,
    MUSIC_BASS_BANK,
    MUSIC_DRUMS_BANK,
    MUSIC_ELECTRONIC_BANK,
    MUSIC_GENRE_BANK,
    MUSIC_VOCAL_BANK,
    SPEECH_STYLE_BANK,
    DetailedSensoryDescriber,
)


class FakeCortex:
    _np = np
    _screen_labels = ["screen"]
    _audio_labels = ["legacy_audio"]
    _screen_emotions = {"screen": "neutral"}
    _audio_emotions = {"legacy_audio": "neutral"}

    def __init__(self, model_root: Path) -> None:
        self.model_root = model_root
        self.embed_calls = 0
        self._screen_matrix = np.ones((1, 32), dtype=np.float32) / math.sqrt(32)
        self._audio_matrix = np.ones((1, 32), dtype=np.float32) / math.sqrt(32)

    @staticmethod
    def _vector(seed: bytes) -> np.ndarray:
        value = int.from_bytes(hashlib.sha256(seed).digest()[:8], "little")
        vector = np.random.default_rng(value).normal(size=32).astype(np.float32)
        return vector / max(float(np.linalg.norm(vector)), 1e-8)

    def embed_text(self, text: str) -> np.ndarray:
        return self._vector(text.encode("utf-8"))

    def embed_audio_pcm16(self, pcm16: bytes, sample_rate: int = 16000) -> np.ndarray:
        self.embed_calls += 1
        return self._vector(sample_rate.to_bytes(4, "little") + pcm16)


def _wav(*, duration_s: float = 4.25, amplitude: int = 8000, channels: int = 1) -> bytes:
    rate = 16_000
    frames = int(rate * duration_s)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(rate)
        raw = bytearray()
        for index in range(frames):
            value = int(amplitude * math.sin(2 * math.pi * 220 * index / rate))
            for _ in range(channels):
                raw.extend(value.to_bytes(2, "little", signed=True))
        target.writeframes(raw)
    return buffer.getvalue()


class AudioCoarseToFineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="jawl-audio-bank-")
        cortex = FakeCortex(Path(self._temp.name))
        self.cortex = cortex
        self.describer = DetailedSensoryDescriber(cortex)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_l1_scene_prompts_are_positive_multiclass_descriptions(self) -> None:
        labels = {item[0] for item in AUDIO_SCENE_BANK}
        self.assertEqual(
            labels,
            {"music_present", "speech_dominant", "environmental_sounds", "speech_and_music"},
        )
        prompts = [
            prompt
            for _label, prompt_set, _emotion in AUDIO_SCENE_BANK
            for prompt in (prompt_set if isinstance(prompt_set, tuple) else (prompt_set,))
        ]
        audio_banks = (
            AUDIO_SCENE_BANK,
            MUSIC_GENRE_BANK,
            SPEECH_STYLE_BANK,
            MUSIC_VOCAL_BANK,
            MUSIC_DRUMS_BANK,
            MUSIC_BASS_BANK,
            MUSIC_ELECTRONIC_BANK,
        )
        for _bank in audio_banks:
            for _label, prompt_set, _emotion in _bank:
                prompts.extend(prompt_set if isinstance(prompt_set, tuple) else (prompt_set,))
        for prompt in prompts:
            lowered = prompt.casefold()
            self.assertIsNone(
                re.search(r"\b(?:without|no\s+(?:music|speech|vocals?)|music\s+absent)\b", lowered)
            )
        self.assertNotIn("silence_quiet", {item[0] for item in MUSIC_GENRE_BANK})

        probe_path = ROOT / "scripts" / "probe_clap_prompt_bank.py"
        tree = ast.parse(probe_path.read_text(encoding="utf-8"))
        prompt_node = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PROMPT_BANKS" for target in node.targets)
        )
        probe_prompts = ast.literal_eval(prompt_node)
        for family in probe_prompts.values():
            for phrase_set in family.values():
                for phrase in phrase_set:
                    lowered = phrase.casefold()
                    self.assertIsNone(
                        re.search(r"\b(?:without|no\s+(?:music|speech|vocals?)|music\s+absent)\b", lowered)
                    )

    def test_l2_refines_l1_with_independent_details_and_window_changes(self) -> None:
        observation = self.describer.describe_audio_detailed(_wav())

        self.assertEqual(len(observation.level1["scene_candidates"]), 4)
        self.assertNotIn("music_genre", observation.level1)
        self.assertEqual(len(observation.level2["context_concepts"]), 3)
        self.assertEqual(len(observation.level2["window_features"]), 4)
        self.assertEqual(len(observation.level2["window_changes"]), 3)
        for bank in ("music_vocals", "music_drums", "music_bass", "music_electronic"):
            self.assertTrue(observation.level2["specialist_candidates"][bank])
            self.assertTrue(observation.level2["window_features"][0]["specialist_candidates"][bank])
        self.assertIn("temporal_summary", observation.level3)
        self.assertEqual(observation.level3["temporal_summary"]["window_count"], 4)
        self.assertIn("music_genre", observation.level3["temporal_summary"]["feature_top_window_support"])
        self.assertEqual(
            set(observation.level3["stage_latency_ms"]),
            {"capture", "embedding", "L1", "L2", "L3"},
        )
        self.assertIsNone(observation.level3["stage_latency_ms"]["capture"])
        self.assertGreaterEqual(self.cortex.embed_calls, 4)
        self.assertIn("level3", observation.to_dict())

    def test_specialist_heads_abstain_on_digital_silence_by_signal_energy(self) -> None:
        observation = self.describer.describe_audio_detailed(_wav(amplitude=0))

        self.assertEqual(observation.level0, "unknown_audio")
        self.assertEqual(observation.level1["scene_candidates"], [])
        self.assertEqual(observation.level2["specialist_candidates"]["music_vocals"], [])
        self.assertTrue(all(not row["specialist_candidates"]["music_bass"] for row in observation.level2["window_features"]))


if __name__ == "__main__":
    unittest.main()
