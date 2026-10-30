"""Unit and live-ONNX tests for EmbeddingGemma 2 sensory cortex."""

from __future__ import annotations

import io
import math
from pathlib import Path
import sys
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.eg2_sensory import (
    DEFAULT_EG2_ONNX_ROOT,
    EmbeddingGemmaSensoryCortex,
    EpisodicVectorMemory,
    RollingMediaBuffer,
    RussianEg2Reader,
)


def _make_png(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (320, 224), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_wav(freq: float = 440.0, duration: float = 0.5) -> bytes:
    sr = 16000
    n = int(sr * duration)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        samples = bytearray()
        for i in range(n):
            v = int(6000 * math.sin(2 * math.pi * freq * i / sr))
            samples.extend(v.to_bytes(2, "little", signed=True))
        w.writeframes(samples)
    return buf.getvalue()


@unittest.skipUnless(
    (DEFAULT_EG2_ONNX_ROOT / "onnx" / "model_q4.onnx").is_file(),
    "EmbeddingGemma 2 ONNX weights not downloaded",
)
class EmbeddingGemmaSensoryCortexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cortex = EmbeddingGemmaSensoryCortex(
            DEFAULT_EG2_ONNX_ROOT,
            scene_change_threshold=0.92,
        )

    def test_describe_displays_builds_combined_text(self) -> None:
        cortex = self.cortex

        class FakeObs:
            def __init__(self, label, score):
                self.top_label = label
                self.top_score = score

        original = cortex.classify_screen
        try:
            cortex.classify_screen = lambda image_bytes: FakeObs("code_ide_terminal", 0.9)
            text = cortex.describe_displays([b"a", b"b"])
            self.assertIn("Дисплей 1: code_ide_terminal", text)
            self.assertIn("Дисплей 2: code_ide_terminal", text)
        finally:
            cortex.classify_screen = original

    def test_text_embedding_is_normalized_768d(self) -> None:
        vec = self.cortex.embed_text("task: search result | query: Привет")
        self.assertEqual(vec.shape, (768,))
        self.assertAlmostEqual(float((vec * vec).sum()), 1.0, places=4)

    def test_screen_classification_and_scene_change_detection(self) -> None:
        self.cortex._last_screen_embedding = None
        frame1 = _make_png((12, 24, 36))
        obs1 = self.cortex.classify_screen(frame1)
        self.assertEqual(obs1.modality, "vision")
        self.assertTrue(obs1.scene_changed)
        self.assertIsNone(obs1.scene_similarity)
        self.assertIn(obs1.top_label, obs1.scores)

        # Identical second frame -> high similarity, scene_changed = False
        obs2 = self.cortex.classify_screen(frame1)
        self.assertIsNotNone(obs2.scene_similarity)
        self.assertGreater(obs2.scene_similarity or 0.0, 0.99)
        self.assertFalse(obs2.scene_changed)

    def test_audio_wav_classification_produces_valid_observation(self) -> None:
        wav_path = ROOT / "runtime" / "live-fifine-test.wav"
        wav_bytes = wav_path.read_bytes() if wav_path.is_file() else _make_wav()
        obs = self.cortex.classify_audio_wav(wav_bytes)
        self.assertEqual(obs.modality, "audio")
        self.assertIn(obs.top_label, obs.scores)
        self.assertGreater(obs.latency_ms, 0.0)

    def test_multimodal_observation_and_vibe_fusion(self) -> None:
        frame = _make_png((12, 24, 36))
        wav = _make_wav()
        obs = self.cortex.classify_multimodal(frame, wav)
        self.assertEqual(obs.modality, "audio_visual")
        self.assertIsNotNone(obs.audio_top_label)
        self.assertIsNotNone(obs.vibe_score)
        self.assertIn("reflex", obs.to_dict())
        vibe = self.cortex.vibe_fusion(frame, wav)
        self.assertIn("screen_label", vibe)
        self.assertIn("audio_label", vibe)
        self.assertIn("co_watching_etiquette", vibe)

    def test_latent_reflex_and_scene_change_event(self) -> None:
        frame = _make_png((12, 24, 36))
        obs = self.cortex.classify_screen(frame)
        reflex = self.cortex.latent_reflex_from_observation(obs)
        self.assertIn(reflex["emotion"], {"attentive", "happy", "excited", "relaxed", "neutral", "surprised"})
        self.assertEqual(reflex["latency_budget_ms"], 20)
        event = self.cortex.scene_change_event(obs)
        self.assertIn(event["status"], {"triggered", "stable"})

    def test_episodic_memory_cross_modal_search(self) -> None:
        memory = EpisodicVectorMemory(max_items=4, dimensions=768)
        vec = self.cortex.embed_text("screen code editor")
        memory.add(vec, modality="vision", summary="code editor", source="eg2", timestamp=1.0)
        results = memory.search(vec, top_k=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["modality"], "vision")
        self.assertEqual(memory.state()["items"], 1)

    def test_russian_eg2_reader_returns_bounded_tokens(self) -> None:
        reader = RussianEg2Reader(self.cortex)
        wav = _make_wav()
        tokens = reader.read(wav, top_k=3)
        self.assertEqual(len(tokens), 3)
        self.assertTrue(all("token" in item and "score" in item for item in tokens))



class Eg2CapabilityTests(unittest.TestCase):
    def test_episodic_memory_rejects_wrong_dimensions(self) -> None:
        memory = EpisodicVectorMemory(max_items=2, dimensions=2)
        with self.assertRaises(ValueError):
            memory.add([1.0, 2.0, 3.0], modality="vision")
        with self.assertRaises(ValueError):
            memory.search([1.0], top_k=1)

    def test_russian_reader_requires_tokens(self) -> None:
        class FakeCortex:
            def embed_text(self, text):
                import numpy as np
                return np.ones(4, dtype=np.float32) / 2.0

            _np = __import__("numpy")

        with self.assertRaises(ValueError):
            RussianEg2Reader(FakeCortex(), tokens=("",))


class RollingMediaBufferTests(unittest.TestCase):
    def test_rolling_window_prunes_old_items_and_groups_modalities(self) -> None:
        buffer = RollingMediaBuffer(window_seconds=10.0, max_items=10, dimensions=4)
        buffer.observe({"top_label": "screen"}, modality="vision", summary="screen frame", now=1.0, vector=[1.0, 0.0, 0.0, 0.0])
        buffer.observe({"top_label": "speech"}, modality="audio", summary="spoken words", now=2.0, vector=[0.0, 1.0, 0.0, 0.0])
        buffer.observe({"top_label": "music"}, modality="audio", summary="calm music", now=3.0, vector=[0.0, 0.0, 1.0, 0.0])
        snapshot = buffer.snapshot(seconds=10.0, now=4.0)
        self.assertEqual(snapshot["count"], 3)
        self.assertEqual(set(snapshot["modalities"]), {"audio", "vision"})
        self.assertEqual(snapshot["latest_by_modality"]["vision"]["summary"], "screen frame")
        self.assertFalse(snapshot["raw_media_persisted"])
        old_snapshot = buffer.snapshot(seconds=1.0, now=4.0)
        self.assertEqual(old_snapshot["count"], 1)

    def test_cross_modal_search_returns_recent_compact_hits(self) -> None:
        buffer = RollingMediaBuffer(window_seconds=300.0, max_items=10, dimensions=4)
        buffer.observe({"top_label": "screen"}, modality="vision", summary="code editor", now=1.0, vector=[1.0, 0.0, 0.0, 0.0])
        buffer.observe({"top_label": "audio"}, modality="audio", summary="spoken words", now=2.0, vector=[0.0, 1.0, 0.0, 0.0])
        results = buffer.search([1.0, 0.0, 0.0, 0.0], top_k=2, now=3.0)
        self.assertEqual(results[0]["summary"], "code editor")
        self.assertNotIn("vector", results[0])
        self.assertEqual(buffer.state(now=3.0)["counts_by_modality"]["vision"], 1)


if __name__ == "__main__":
    unittest.main()
