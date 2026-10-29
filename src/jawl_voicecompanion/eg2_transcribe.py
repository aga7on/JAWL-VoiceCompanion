"""EmbeddingGemma 2 speech-to-text reader (eg2.haku.sh approach, Russian + English).

Pipeline (mirrors eg2.haku.sh):
1. The EmbeddingGemma 2 audio encoder stays frozen as-is.
2. Either whole-clip contextualized token states (``last_hidden_state`` at 25 Hz /
   40 ms per token, pooled into word windows in a single ONNX pass) or short
   audio slices are projected into the model's 768-D text space via a learned
   or prototype-aligned linear ``reader`` matrix ``W``.
3. Mean-centered cosine similarity against a precomputed vocabulary matrix
   selects the best token per window, with CTC-style repeat collapsing across
   adjacent frames.
4. A punctuation and casing pass turns the decoded token stream into readable
   text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import io
import re
import wave

import numpy as np

DEFAULT_VOCAB_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "models"
    / "embeddinggemma-2-onnx"
    / "vocab.txt"
)

# Bilingual core vocabulary: Russian conversational/sensory words + English starter
RUSSIAN_CORE_TOKENS = (
    "привет здравствуй как дела хорошо отлично спасибо пожалуйста да нет "
    "сейчас сегодня здесь там что где когда почему зачем кто какой "
    "экран окно монитор дисплей кадр видео аниме фильм серия сцена "
    "музыка песня трек ритм бит темп жанр пианино гитара ударные бас вокал "
    "голос речь разговор диалог тишина пауза шум звук громко тихо "
    "код редактор терминал консоль ошибка функция тест файл проект браузер "
    "игра бой персонаж уровень меню настройки компаньон аватар память задача "
    "смотри слушай скажи покажи открой запусти проверь помоги сделай стоп"
).split()

STARTER_TOKENS = (
    "hello hi how what where when why who this that here now yes no "
    "okay well just very really know think maybe want need see look "
    "and or but so because then about with for from into over under "
    + " ".join(RUSSIAN_CORE_TOKENS)
).split()


class Eg2Transcriber:
    """Zero-decoder slice and token-stream transcriber over an embedding cortex."""

    def __init__(
        self,
        cortex: Any,
        *,
        vocab: Iterable[str] | None = None,
        reader: Any | None = None,
        vocab_path: Path | None = None,
        cache_embeddings: bool = True,
        deduplicate_repeats: bool = False,
    ) -> None:
        self.cortex = cortex
        self.vocab_path = Path(vocab_path or DEFAULT_VOCAB_PATH)
        self._cache = bool(cache_embeddings)
        self.deduplicate_repeats = bool(deduplicate_repeats)
        tokens = self._load_vocab(vocab)
        if not tokens:
            raise ValueError("eg2 transcriber requires a non-empty vocabulary")
        self.vocab = tokens
        self.matrix = self._build_matrix(tokens)
        self._matrix_mean = self.matrix.mean(axis=0, keepdims=True)
        centered = self.matrix - self._matrix_mean
        norms = np.linalg.norm(centered, axis=1, keepdims=True)
        self._centered_matrix = (centered / np.maximum(norms, 1e-6)).astype(np.float32)
        self.reader = self._coerce_reader(reader)
        self._reader_bias: np.ndarray | None = None
        self._is_trained = reader is not None

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
                seen_file: set[str] = set()
                return [t for t in tokens if not (t in seen_file or seen_file.add(t))]
        seen_default: set[str] = set()
        return [t for t in STARTER_TOKENS if not (t in seen_default or seen_default.add(t))]

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
        # Note: in fit(), A @ W ≈ B, so vec @ self.reader (or self.reader.T @ vec)
        # maps row-vector audio embeddings into text embedding space.
        # For symmetric / orthogonal / eye matrices both are identical; using
        # vec @ self.reader matches np.linalg.lstsq(A.T @ A, A.T @ B).
        out = vec @ self.reader if self.reader is not None else vec
        if self._reader_bias is not None:
            out = out + self._reader_bias
        norm = float(np.linalg.norm(out)) or 1.0
        return (out / norm).astype(np.float32)

    def fit(
        self,
        pairs: list[tuple[bytes, str]],
        *,
        sample_rate: int = 16000,
        ridge_alpha: float = 1e-2,
    ) -> dict[str, Any]:
        """Fit the linear reader on aligned (audio-slice PCM16, word) pairs.

        Closed-form regularized ridge regression:
        W = argmin ||A W - B||_F^2 + alpha ||W||_F^2,
        mapping audio-slice embeddings onto their target words' text embeddings.
        """
        if not pairs:
            return {"status": "failed", "reason": "no_training_pairs", "trained": False}
        vocab_set = set(self.vocab)
        A: list[np.ndarray] = []
        B: list[np.ndarray] = []
        target_words: list[str] = []
        for pcm, word in pairs:
            word = str(word).strip()
            if not word or word not in vocab_set:
                continue
            try:
                audio_vec = np.asarray(
                    self.cortex.embed_audio_pcm16(pcm, sample_rate=sample_rate),
                    dtype=np.float32,
                )
                norm = float(np.linalg.norm(audio_vec)) or 1.0
                audio_vec = (audio_vec / norm).astype(np.float32)
            except Exception:  # noqa: BLE001 - skip unreadable slices
                continue
            word_idx = self.vocab.index(word)
            text_vec = self.matrix[word_idx]
            A.append(audio_vec)
            B.append(text_vec)
            target_words.append(word)
        if not A:
            return {"status": "failed", "reason": "no_aligned_pairs", "trained": False}
        A_mat = np.stack(A)
        B_mat = np.stack(B)
        alpha = max(1e-5, float(ridge_alpha))
        ridge = alpha * np.eye(A_mat.shape[1], dtype=np.float32)
        normal = A_mat.T @ A_mat + ridge
        solution, *_ = np.linalg.lstsq(normal, A_mat.T @ B_mat, rcond=None)
        self.reader = np.asarray(solution, dtype=np.float32)
        self._is_trained = True

        # Measure training top-1 accuracy immediately to verify minimal error
        hits = 0
        for audio_vec, expected in zip(A, target_words):
            proj = self.project(audio_vec)
            scores = self.matrix @ proj
            pred = self.vocab[int(np.argmax(scores))]
            if pred == expected:
                hits += 1
        accuracy = round(hits / max(1, len(A)), 4)
        return {
            "status": "ok",
            "trained": True,
            "pairs": len(A),
            "vocab": len(self.vocab),
            "train_accuracy": accuracy,
        }

    def save_reader(self, path: Path) -> None:
        np.save(Path(path), self.reader)

    def load_reader(self, path: Path) -> None:
        matrix = np.load(Path(path))
        self.reader = self._coerce_reader(matrix)
        self._is_trained = True

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

    def _score_vector(self, audio_vec: np.ndarray) -> np.ndarray:
        projected = self.project(audio_vec)
        raw_scores = self.matrix @ projected
        if self._is_trained:
            return raw_scores
        # When using an untrained identity reader, combine raw cosine with
        # mean-centered cosine to suppress embedding space anisotropy.
        centered_proj = projected - self._matrix_mean[0]
        c_norm = float(np.linalg.norm(centered_proj)) or 1.0
        centered_scores = self._centered_matrix @ (centered_proj / c_norm)
        return 0.65 * raw_scores + 0.35 * centered_scores

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
            scores = self._score_vector(audio_vec)
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

    def transcribe_token_stream(
        self,
        pcm: bytes,
        *,
        sample_rate: int = 16000,
        window_tokens: int = 6,
        stride_tokens: int = 4,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Haku-style single-pass token-stream decoding from ``last_hidden_state``.

        Runs the ONNX audio encoder + text model ONCE for the entire audio clip,
        pools 40 ms contextualized token vectors into word-sized windows (~240 ms),
        and projects each window onto the vocabulary matrix.
        """
        if not hasattr(self.cortex, "embed_audio_tokens"):
            return self.transcribe_pcm16(pcm, sample_rate=sample_rate, top_k=top_k)
        try:
            global_vec, token_vecs = self.cortex.embed_audio_tokens(pcm, sample_rate=sample_rate)
        except Exception:  # noqa: BLE001
            return self.transcribe_pcm16(pcm, sample_rate=sample_rate, top_k=top_k)
        token_arr = np.asarray(token_vecs, dtype=np.float32)
        if token_arr.ndim != 2 or token_arr.shape[0] == 0:
            return []
        n_tokens = token_arr.shape[0]
        win = max(1, min(int(window_tokens), n_tokens))
        stride = max(1, int(stride_tokens))
        results: list[dict[str, Any]] = []
        slice_idx = 0
        for start in range(0, max(1, n_tokens - win + 1), stride):
            window_vec = token_arr[start : start + win].mean(axis=0)
            # Blend local contextual token window with global clip context
            blended = 0.75 * window_vec + 0.25 * np.asarray(global_vec, dtype=np.float32)
            norm = float(np.linalg.norm(blended)) or 1.0
            blended = (blended / norm).astype(np.float32)
            scores = self._score_vector(blended)
            order = np.argsort(-scores)[: max(1, min(int(top_k), len(self.vocab)))]
            best = [
                {"token": self.vocab[int(i)], "score": round(float(scores[int(i)]), 4)}
                for i in order
            ]
            start_s = start * 0.04
            end_s = min(n_tokens, start + win) * 0.04
            results.append(
                {
                    "slice_index": slice_idx,
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "candidates": best,
                }
            )
            slice_idx += 1
        return results

    def top_tokens(
        self, embedding: Any, *, top_k: int = 8, min_score: float | None = None
    ) -> list[dict[str, Any]]:
        """Score one embedding against the full vocabulary."""
        scores = self._score_vector(np.asarray(embedding, dtype=np.float32))
        order = np.argsort(-scores)[: max(1, min(int(top_k), len(self.vocab)))]
        result = [
            {"token": self.vocab[int(i)], "score": round(float(scores[int(i)]), 4)}
            for i in order
        ]
        if min_score is not None:
            result = [item for item in result if item["score"] >= float(min_score)]
        return result

    def transcribe_image_vectors(
        self,
        global_vec: Any,
        token_vecs: Any,
        *,
        window_tokens: int = 6,
        stride_tokens: int = 4,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Decode already-extracted image tokens against the full vocabulary."""
        token_arr = np.asarray(token_vecs, dtype=np.float32)
        if token_arr.ndim != 2 or token_arr.shape[0] == 0:
            return []
        n_tokens = token_arr.shape[0]
        win = max(1, min(int(window_tokens), n_tokens))
        stride = max(1, int(stride_tokens))
        results: list[dict[str, Any]] = []
        region_idx = 0
        for start in range(0, max(1, n_tokens - win + 1), stride):
            window_vec = token_arr[start : start + win].mean(axis=0)
            blended = 0.75 * window_vec + 0.25 * np.asarray(global_vec, dtype=np.float32)
            norm = float(np.linalg.norm(blended)) or 1.0
            blended = (blended / norm).astype(np.float32)
            scores = self._score_vector(blended)
            order = np.argsort(-scores)[: max(1, min(int(top_k), len(self.vocab)))]
            best = [
                {"token": self.vocab[int(i)], "score": round(float(scores[int(i)]), 4)}
                for i in order
            ]
            results.append(
                {
                    "region_index": region_idx,
                    "region_start": start,
                    "region_end": min(n_tokens, start + win),
                    "candidates": best,
                }
            )
            region_idx += 1
        return results

    def transcribe_image_tokens(
        self,
        image_bytes: bytes,
        *,
        window_tokens: int = 6,
        stride_tokens: int = 4,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Haku-style image-token stream decoding against the full vocabulary."""
        if not hasattr(self.cortex, "embed_image_tokens"):
            return []
        try:
            global_vec, token_vecs = self.cortex.embed_image_tokens(image_bytes)
        except Exception:  # noqa: BLE001 - vision may be unavailable
            return []
        return self.transcribe_image_vectors(
            global_vec,
            token_vecs,
            window_tokens=window_tokens,
            stride_tokens=stride_tokens,
            top_k=top_k,
        )

    def visual_transcript(
        self,
        slices: list[dict[str, Any]],
        *,
        global_candidates: list[dict[str, Any]] | None = None,
        min_score: float = 0.44,
        max_words: int = 14,
    ) -> str:
        """Compose a bounded word sequence from open-vocabulary candidates."""
        words: list[str] = []
        seen: set[str] = set()
        pattern = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё' -]{1,30}$")

        def add(token: Any, score: Any) -> None:
            text = str(token or "").strip()
            if not text or not pattern.fullmatch(text):
                return
            if float(score) < float(min_score):
                return
            key = text.casefold()
            if key in seen:
                return
            seen.add(key)
            words.append(text)

        for item in global_candidates or []:
            add(item.get("token"), item.get("score", 0.0))
            if len(words) >= max_words:
                break
        for slice_item in slices:
            for candidate in slice_item.get("candidates", [])[:1]:
                add(candidate.get("token"), candidate.get("score", 0.0))
                if len(words) >= max_words:
                    break
            if len(words) >= max_words:
                break
        return " ".join(words)

    def fit_image_pairs(
        self,
        pairs: list[tuple[bytes, str]],
        *,
        ridge_alpha: float = 1e-2,
    ) -> dict[str, Any]:
        """Fit the reader on aligned (image, word) pairs.

        This is the vision counterpart of :meth:`fit`: a closed-form ridge map
        from image embeddings to the text embeddings of the paired words.
        """
        if not pairs:
            return {"status": "failed", "reason": "no_training_pairs", "trained": False}
        if not hasattr(self.cortex, "embed_image_bytes"):
            return {"status": "failed", "reason": "vision_encoder_unavailable", "trained": False}
        vocab_set = set(self.vocab)
        A: list[np.ndarray] = []
        B: list[np.ndarray] = []
        target_words: list[str] = []
        for image_bytes, word in pairs:
            word = str(word).strip()
            if not word or word not in vocab_set:
                continue
            try:
                image_vec = np.asarray(
                    self.cortex.embed_image_bytes(image_bytes), dtype=np.float32
                )
                norm = float(np.linalg.norm(image_vec)) or 1.0
                image_vec = (image_vec / norm).astype(np.float32)
            except Exception:  # noqa: BLE001 - skip unreadable frames
                continue
            word_idx = self.vocab.index(word)
            A.append(image_vec)
            B.append(self.matrix[word_idx])
            target_words.append(word)
        if not A:
            return {"status": "failed", "reason": "no_aligned_pairs", "trained": False}
        A_mat = np.stack(A)
        B_mat = np.stack(B)
        alpha = max(1e-5, float(ridge_alpha))
        normal = A_mat.T @ A_mat + alpha * np.eye(A_mat.shape[1], dtype=np.float32)
        solution, *_ = np.linalg.lstsq(normal, A_mat.T @ B_mat, rcond=None)
        self.reader = np.asarray(solution, dtype=np.float32)
        self._is_trained = True
        hits = 0
        for image_vec, expected in zip(A, target_words):
            scores = self.matrix @ self.project(image_vec)
            if self.vocab[int(np.argmax(scores))] == expected:
                hits += 1
        return {
            "status": "ok",
            "trained": True,
            "pairs": len(A),
            "vocab": len(self.vocab),
            "train_accuracy": round(hits / max(1, len(A)), 4),
        }

    def transcribe_wav(self, wav_bytes: bytes, **kwargs: Any) -> list[dict[str, Any]]:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        return self.transcribe_pcm16(pcm, sample_rate=sample_rate, **kwargs)

    def transcript_text(
        self,
        slices: list[dict[str, Any]],
        *,
        collapse_repeats: bool | None = None,
        min_score: float | None = None,
    ) -> str:
        dedup = self.deduplicate_repeats if collapse_repeats is None else bool(collapse_repeats)
        words: list[str] = []
        for s in slices:
            candidates = s.get("candidates")
            if not candidates:
                continue
            top = candidates[0]
            if min_score is not None and float(top.get("score", 0.0)) < float(min_score):
                continue
            token = str(top["token"]).strip()
            if not token:
                continue
            if dedup and words and words[-1].lower() == token.lower():
                continue
            words.append(token)
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
        if lowered in {"да", "нет", "ну", "вот", "однако", "зато", "причём"} and i > 0:
            out[-1] = out[-1].rstrip(",") + ","
        out.append(lowered)
    result = " ".join(out)
    if not result.endswith((".", "!", "?")):
        result += "."
    return result


__all__ = [
    "DEFAULT_VOCAB_PATH",
    "Eg2Transcriber",
    "RUSSIAN_CORE_TOKENS",
    "STARTER_TOKENS",
    "punctuate",
]
