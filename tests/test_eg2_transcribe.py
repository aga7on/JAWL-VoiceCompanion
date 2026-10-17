"""Unit tests for the eg2-style transcriber (no ONNX required)."""

from __future__ import annotations

import io
import sys
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.eg2_transcribe import Eg2Transcriber, punctuate  # noqa: E402


def _wav(freq: float = 220.0, seconds: float = 1.0, sr: int = 16000) -> bytes:
    n = int(sr * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            value = int(6000 * np.sin(2 * np.pi * freq * i / sr))
            frames.extend(value.to_bytes(2, "little", signed=True))
        w.writeframes(frames)
    return buf.getvalue()


class FakeCortex:
    """Deterministic cortex: word-tagged audio maps to the word embedding."""

    _dim = 768

    def _vec(self, seed: str) -> np.ndarray:
        digest = int.from_bytes(
            __import__("hashlib").sha256(seed.encode("utf-8")).digest()[:8],
            "little",
        )
        rng = np.random.default_rng(digest)
        vec = rng.standard_normal(768).astype(np.float32)
        return (vec / np.linalg.norm(vec)).astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        # Strip the eg2 prompt wrapper: the raw token is the seed.
        seed = str(text).replace("title: none | text:", "").strip()
        return self._vec("text:" + seed)

    def embed_audio_pcm16(self, pcm: bytes, sample_rate: int = 16000) -> np.ndarray:
        # Audio slices tagged "audio:<word>\x00": map to that word's text
        # embedding so the reader fit has a learnable target.
        try:
            tag = bytes(pcm[:96].split(b"\x00", 1)[0]).decode("utf-8")
        except UnicodeDecodeError:
            tag = ""
        if tag.startswith("audio:"):
            return self._vec("text:" + tag[len("audio:") :])
        digest = int.from_bytes(
            __import__("hashlib").sha256(pcm[:64]).digest()[:8], "little"
        )
        return self._vec(f"raw:{digest}")


class Eg2TranscriberTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cortex = FakeCortex()
        self.vocab = ["hello", "how", "what", "okay", "know"]
        self.transcriber = Eg2Transcriber(
            self.cortex,
            vocab=self.vocab,
            cache_embeddings=False,
        )

    def test_vocab_dedup_and_order(self):
        self.assertEqual(self.transcriber.vocab, self.vocab)

    def test_transcribe_wav_returns_slices_with_candidates(self):
        slices = self.transcriber.transcribe_wav(_wav(), slice_seconds=0.5, top_k=3)
        self.assertEqual(len(slices), 2)
        for item in slices:
            self.assertEqual(len(item["candidates"]), 3)
            self.assertIn(item["candidates"][0]["token"], self.vocab)

    def test_project_normalises_output(self):
        vec = self.cortex.embed_audio_pcm16(b"\x01\x02" * 800)
        projected = self.transcriber.project(vec)
        self.assertAlmostEqual(float((projected * projected).sum()), 1.0, places=5)

    def test_transcript_text_applies_punctuation(self):
        text = punctuate("hello how what")
        self.assertEqual(text[0], "H")
        self.assertTrue(text.endswith("."))

    def test_fit_rejects_empty_pairs(self):
        result = self.transcriber.fit([])
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["trained"])

    def test_fit_identity_reader_on_consistent_pairs(self):
        # Word-tagged audio slices: fit must map them back to the same word.
        target = "hello"
        pcm = b"audio:" + target.encode("utf-8") + b"\x00" + b"\x01" * 1024
        pairs = [(pcm, target)] * 4
        result = self.transcriber.fit(pairs)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["trained"])
        audio_vec = self.cortex.embed_audio_pcm16(pcm)
        projected = self.transcriber.project(audio_vec)
        scores = self.transcriber.matrix @ projected
        self.assertEqual(
            self.transcriber.vocab[int(np.argmax(scores))],
            target,
        )


if __name__ == "__main__":
    unittest.main()
