"""EmbeddingGemma 2 speech-to-text reader (eg2.haku.sh approach, Russian).

Pipeline (mirrors eg2):
1. The EmbeddingGemma 2 audio encoder stays exactly as it is.
2. A small linear ``reader`` projects each short audio-slice embedding into
   the model's text space.
3. The closest vocabulary entry (cosine over a precomputed word-embedding
   matrix) wins; slices become a transcript.
4. A heuristic punctuation pass adds capitals/pauses until a trained tiny
   punctuation model replaces it.

Only the reader is trained (ridge/least-squares on aligned audio-text
pairs). The base model is never modified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import io
import wave

import numpy as np

DEFAULT_VOCAB_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "models"
    / "embeddinggemma-2-onnx"
    / "vocab.txt"
)

# English starter: EG2's embedding space is densest around English speech
# corpora, so an English vocabulary gives the strongest reader signal while
# the brain LLM translates the transcript into Russian for voice output.
STARTER_TOKENS = (
    "hello hi how what where when why who this that here now yes no "
    "okay well just very really know think maybe want need see look "
    "and or but so because then about with for from into over under"
).split()


class Eg2Transcriber:
    """Slice-level zero-decoder transcriber over an embedding cortex."""

    def __init__(
        self,
        cortex: Any,
        *,
        vocab: Iterable[str] | None = None,
        reader: Any | None = None,
        vocab_path: Path | None = None,
        cache_embeddings: bool = True,
    ) -> None:
        self.cortex = cortex
        self.vocab_path = Path(vocab_path or DEFAULT_VOCAB_PATH)
        self._cache = bool(cache_embeddings)
        tokens = self._load_vocab(vocab)
        if not tokens:
            raise ValueError("eg2 transcriber requires a non-empty vocabulary")
        self.vocab = tokens
        self.matrix = self._build_matrix(tokens)
        self.reader = self._coerce_reader(reader)

    # ---------------------------------------------------------------- vocab

    def _load_vocab(self, vocab: Iterable[str] | None) -> list[str]:
        if vocab is not None:
            tokens = [str(token).strip() for token in vocab if str(token).strip()]
            seen: set[str] = set()
            return [t for t in tokens if not (t in seen or seen.add(t))]
        path = self.vocab_path
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            tokens = [line.strip().split("\t")[0] for line in lines]
            tokens = [t for t in tokens if t][:200_000]
            if tokens:
                return tokens
        return list(STARTER_TOKENS)

    def _build_matrix(self, tokens: list[str]) -> np.ndarray:
        cache_path = self.vocab_path.with_suffix(".npy")
        if self._cache and cache_path.is_file():
            try:
                cached = np.load(cache_path)
                if cached.shape == (len(tokens), self._dim):
                    return cached
            except Exception:  # noqa: BLE001 - rebuild on any cache mismatch
                pass
        rows = [self._embed_text(f"title: none | text: {token}") for token in tokens]
        matrix = np.stack(rows).astype(np.float32)
        if self._cache:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(cache_path, matrix)
            except Exception:  # noqa: BLE001 - cache is best-effort
                pass
        return matrix

    @property
    def _dim(self) -> int:
        return int(getattr(self.cortex, "_dim", 0) or 768)

    def _embed_text(self, text: str) -> np.ndarray:
        vec = np.asarray(self.cortex.embed_text(text), dtype=np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        return (vec / norm).astype(np.float32)

    # --------------------------------------------------------------- reader

    @staticmethod
    def _coerce_reader(reader: Any | None) -> np.ndarray:
        if reader is None:
            return np.eye(768, dtype=np.float32)
        matrix = np.asarray(reader, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != 768 or matrix.shape[1] != 768:
            raise ValueError("reader must be a 768x768 linear projection")
        return matrix

    def project(self, embedding: Any) -> np.ndarray:
        vec = np.asarray(embedding, dtype=np.float32)
        if vec.shape != (768,):
            raise ValueError("audio slice embedding must be 768-d")
        out = self.reader @ vec if self.reader is not None else vec
        norm = float(np.linalg.norm(out)) or 1.0
        return (out / norm).astype(np.float32)

    def fit(self, pairs: list[tuple[bytes, str]]) -> dict[str, Any]:
        """Fit the reader on aligned (audio-slice PCM16, word) pairs.

        Closed-form ridge regression: W = argmin ||A W - B||^2 + a||W||^2,
        mapping audio-slice embeddings onto their words' text embeddings.
        """
        if not pairs:
            return {"status": "failed", "reason": "no_training_pairs", "trained": False}
        A: list[np.ndarray] = []
        B: list[np.ndarray] = []
        for pcm, word in pairs:
            word = str(word).strip()
            if not word or word not in set(self.vocab):
                continue
            try:
                audio_vec = np.asarray(self.cortex.embed_audio_pcm16(pcm), dtype=np.float32)
            except Exception:  # noqa: BLE001 - skip unreadable slices
                continue
            text_vec = self._embed_text(f"title: none | text: {word}")
            A.append(audio_vec)
            B.append(text_vec)
        if not A:
            return {"status": "failed", "reason": "no_aligned_pairs", "trained": False}
        A_mat = np.stack(A)
        B_mat = np.stack(B)
        ridge = 1e-3 * np.eye(A_mat.shape[1], dtype=np.float32)
        normal = A_mat.T @ A_mat + ridge
        solution, *_ = np.linalg.lstsq(normal, A_mat.T @ B_mat, rcond=None)
        self.reader = np.asarray(solution, dtype=np.float32)
        return {
            "status": "ok",
            "trained": True,
            "pairs": len(A),
            "vocab": len(self.vocab),
        }

    def save_reader(self, path: Path) -> None:
        np.save(Path(path), self.reader)

    def load_reader(self, path: Path) -> None:
        matrix = np.load(Path(path))
        self.reader = self._coerce_reader(matrix)

    # ------------------------------------------------------------ decoding

    def _slices(self, pcm: bytes, sample_rate: int, slice_seconds: float) -> list[bytes]:
        total = len(pcm) // 2
        slice_len = max(1, int(sample_rate * slice_seconds))
        out: list[bytes] = []
        for start in range(0, total, slice_len):
            chunk = pcm[start * 2 : (start + slice_len) * 2]
            if len(chunk) < 512:
                continue
            out.append(chunk)
        return out

    def transcribe_pcm16(
        self,
        pcm: bytes,
        *,
        sample_rate: int = 16000,
        slice_seconds: float = 0.5,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index, chunk in enumerate(self._slices(pcm, sample_rate, slice_seconds)):
            start_s = index * slice_seconds
            try:
                audio_vec = np.asarray(
                    self.cortex.embed_audio_pcm16(chunk, sample_rate=sample_rate),
                    dtype=np.float32,
                )
            except Exception:  # noqa: BLE001 - keep remaining slices
                continue
            projected = self.project(audio_vec)
            scores = self.matrix @ projected
            order = np.argsort(-scores)[: max(1, min(int(top_k), len(self.vocab)))]
            best = [
                {"token": self.vocab[int(i)], "score": round(float(scores[int(i)]), 4)}
                for i in order
            ]
            results.append(
                {
                    "slice_index": index,
                    "start_s": round(start_s, 3),
                    "end_s": round(start_s + slice_seconds, 3),
                    "candidates": best,
                }
            )
        return results

    def transcribe_wav(self, wav_bytes: bytes, **kwargs: Any) -> list[dict[str, Any]]:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        return self.transcribe_pcm16(pcm, sample_rate=sample_rate, **kwargs)

    def transcript_text(self, slices: list[dict[str, Any]]) -> str:
        words = [s["candidates"][0]["token"] for s in slices if s.get("candidates")]
        return punctuate(" ".join(words))


def punctuate(text: str) -> str:
    """Heuristic punctuation/capitalisation; a trained model replaces later."""
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    words = clean.split(" ")
    out: list[str] = []
    for i, word in enumerate(words):
        lowered = word.lower()
        if i == 0:
            out.append(lowered.capitalize())
            continue
        if lowered in {"да", "нет", "ну", "вот"} and i > 0:
            out[-1] = out[-1].rstrip(",") + ","
        out.append(lowered)
    result = " ".join(out)
    if not result.endswith((".", "!", "?")):
        result += "."
    return result


__all__ = ["Eg2Transcriber", "punctuate", "DEFAULT_VOCAB_PATH", "STARTER_TOKENS"]
