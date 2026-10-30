"""EmbeddingGemma 2 multimodal sensory cortex (System 1).

Provides sub-150ms CPU-only ONNX inference for:
1. Text intent and concept classification (~13 ms on CPU);
2. Direct audio/music/speech classification from 16 kHz PCM (~60-110 ms);
3. Zero-decoder visual screen classification and scene-change detection
   (cosine similarity between consecutive frames, ~100-150 ms) without calling
   a heavy autoregressive VLM;
4. Latent VRM emotion reflex mapping directly from screen/audio embeddings.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import time
from typing import Any
import wave


DEFAULT_EG2_ONNX_ROOT = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "models"
    / "embeddinggemma-2-onnx"
)

_BOA_TOKEN_ID = 256000
_BOI_TOKEN_ID = 255999
_AUDIO_TOKEN_ID = 258881
_IMAGE_TOKEN_ID = 258880
_EOA_TOKEN_ID = 258883
_EOI_TOKEN_ID = 258882


@dataclass(frozen=True)
class SensoryObservation:
    """Bounded multimodal observation produced by EmbeddingGemma 2."""

    modality: str  # "text" | "audio" | "vision" | "audio_visual"
    top_label: str
    top_score: float
    scores: dict[str, float]
    latency_ms: float
    scene_similarity: float | None = None
    scene_changed: bool = False
    reflex_emotion: str = "neutral"
    audio_top_label: str | None = None
    vibe_score: float | None = None
    reflex: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality": self.modality,
            "top_label": self.top_label,
            "top_score": round(self.top_score, 4),
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "latency_ms": round(self.latency_ms, 1),
            "scene_similarity": (
                round(self.scene_similarity, 4)
                if self.scene_similarity is not None
                else None
            ),
            "scene_changed": self.scene_changed,
            "reflex_emotion": self.reflex_emotion,
            "audio_top_label": self.audio_top_label,
            "vibe_score": (
                round(self.vibe_score, 4) if self.vibe_score is not None else None
            ),
            "reflex": self.reflex,
        }


DEFAULT_SCREEN_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    (
        "code_ide_terminal",
        "title: none | text: source code editor IDE terminal window with programming text",
        "attentive",
    ),
    (
        "anime_movie_video",
        "title: none | text: anime episode or movie video scene playing on screen",
        "happy",
    ),
    (
        "game_combat_action",
        "title: none | text: dynamic video game combat action boss fight scene",
        "excited",
    ),
    (
        "companion_avatar_ui",
        "title: none | text: 3D anime girl character avatar in a dark companion interface",
        "relaxed",
    ),
    (
        "web_browser_article",
        "title: none | text: web browser page with articles documentation or social media",
        "neutral",
    ),
)

DEFAULT_AUDIO_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    (
        "human_speech_ru",
        "title: none | text: человек говорит голосом на русском языке",
        "attentive",
    ),
    (
        "calm_melancholic_music",
        "title: none | text: спокойная мелодичная музыка пианино или эмбиент саундтрек",
        "relaxed",
    ),
    (
        "energetic_action_music",
        "title: none | text: быстрая энергичная рок или электронная музыка и экшен",
        "excited",
    ),
    (
        "dramatic_tension_sfx",
        "title: none | text: тревожный драматичный звук взрыв или внезапный удар",
        "surprised",
    ),
    (
        "quiet_room_silence",
        "title: none | text: тишина и слабый фоновый шум комнаты",
        "neutral",
    ),
)


class EmbeddingGemmaSensoryCortex:
    """Zero-decoder multimodal sensory engine backed by EmbeddingGemma 2 ONNX."""

    def __init__(
        self,
        model_root: Path | None = None,
        *,
        scene_change_threshold: float = 0.88,
        load_vision: bool = True,
        load_audio: bool = True,
        intra_op_num_threads: int = 1,
    ) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        self.model_root = Path(model_root or DEFAULT_EG2_ONNX_ROOT).resolve()
        self.scene_change_threshold = float(scene_change_threshold)
        self.intra_op_num_threads = max(1, min(32, int(intra_op_num_threads)))
        self._last_screen_embedding: Any = None
        self._last_multimodal_screen_embedding: Any = None

        onnx_dir = self.model_root / "onnx"
        self.tokenizer = Tokenizer.from_file(str(self.model_root / "tokenizer.json"))
        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = self.intra_op_num_threads
        session_options.inter_op_num_threads = 1
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.text_session = ort.InferenceSession(
            str(onnx_dir / "model_q4.onnx"),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        self.vision_session = (
            ort.InferenceSession(
                str(onnx_dir / "vision_encoder_q4.onnx"),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            if load_vision and (onnx_dir / "vision_encoder_q4.onnx").is_file()
            else None
        )
        self.audio_session = (
            ort.InferenceSession(
                str(onnx_dir / "audio_encoder_q4.onnx"),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            if load_audio and (onnx_dir / "audio_encoder_q4.onnx").is_file()
            else None
        )
        self._empty = np.zeros((0, 512), dtype=np.float32)

        # Precompute concept banks in RAM once (~60 ms total at init)
        self._screen_labels = [item[0] for item in DEFAULT_SCREEN_CONCEPTS]
        self._screen_emotions = {item[0]: item[2] for item in DEFAULT_SCREEN_CONCEPTS}
        self._screen_matrix = np.stack(
            [self.embed_text(item[1]) for item in DEFAULT_SCREEN_CONCEPTS]
        )

        self._audio_labels = [item[0] for item in DEFAULT_AUDIO_CONCEPTS]
        self._audio_emotions = {item[0]: item[2] for item in DEFAULT_AUDIO_CONCEPTS}
        self._audio_matrix = np.stack(
            [self.embed_text(item[1]) for item in DEFAULT_AUDIO_CONCEPTS]
        )
        self._mel_filterbank = self._build_mel_filterbank(16000, 512, 128, 8000.0)

    def _build_mel_filterbank(
        self, sr: int, n_fft: int, n_mels: int, fmax: float
    ):
        np = self._np
        mels = np.linspace(0.0, 2595.0 * np.log10(1.0 + fmax / 700.0), n_mels + 2)
        hz = 700.0 * (10.0 ** (mels / 2595.0) - 1.0)
        bins = np.floor((n_fft + 1) * hz / sr).astype(int)
        fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
        for m in range(1, n_mels + 1):
            f0, f1, f2 = bins[m - 1], bins[m], bins[m + 1]
            for k in range(f0, f1):
                fb[m - 1, k] = (k - f0) / max(1, f1 - f0)
            for k in range(f1, f2):
                fb[m - 1, k] = (f2 - k) / max(1, f2 - f1)
        return fb

    def embed_text(self, text: str):
        np = self._np
        ids = np.array([[2] + self.tokenizer.encode(text).ids + [1]], dtype=np.int64)
        vec = self.text_session.run(
            ["sentence_embedding"],
            {
                "input_ids": ids,
                "attention_mask": np.ones_like(ids),
                "image_features": self._empty,
                "video_features": self._empty,
                "audio_features": self._empty,
            },
        )[0][0]
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm

    def embed_audio_pcm16(self, pcm16_bytes: bytes, sample_rate: int = 16000):
        if self.audio_session is None:
            raise RuntimeError("Audio encoder is not loaded")
        np = self._np
        pcm = (
            np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )
        if sample_rate != 16000 and len(pcm) > 0:
            ratio = sample_rate / 16000.0
            idx = (np.arange(int(len(pcm) / ratio)) * ratio).astype(int)
            pcm = pcm[idx]
        win_len, hop_len, n_fft = 320, 160, 512
        if len(pcm) < win_len:
            pcm = np.pad(pcm, (0, win_len - len(pcm)))
        window = np.hanning(win_len).astype(np.float32)
        n_frames = 1 + (len(pcm) - win_len) // hop_len
        frames = (
            np.lib.stride_tricks.as_strided(
                pcm,
                shape=(n_frames, win_len),
                strides=(pcm.strides[0] * hop_len, pcm.strides[0]),
            )
            * window
        )
        spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1)) ** 2
        mel = np.log(np.maximum(np.dot(spec, self._mel_filterbank.T), 0.001)).astype(
            np.float32
        )
        a_feats = self.audio_session.run(
            ["audio_features"],
            {
                "input_features": mel[None, :, :],
                "input_features_mask": np.ones((1, mel.shape[0]), dtype=bool),
            },
        )[0]
        ids = np.array(
            [[2, _BOA_TOKEN_ID] + [_AUDIO_TOKEN_ID] * a_feats.shape[0] + [_EOA_TOKEN_ID, 1]],
            dtype=np.int64,
        )
        vec = self.text_session.run(
            ["sentence_embedding"],
            {
                "input_ids": ids,
                "attention_mask": np.ones_like(ids),
                "image_features": self._empty,
                "video_features": self._empty,
                "audio_features": a_feats,
            },
        )[0][0]
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm

    def embed_image_bytes(self, image_bytes: bytes):
        if self.vision_session is None:
            raise RuntimeError("Vision encoder is not loaded")
        np = self._np
        from PIL import Image

        # 21x30 patches (480x336) is divisible by pooling_kernel_size=3 -> 70 soft tokens,
        # and pixel_position_ids must be (pos_x, pos_y) for Gemma4 axial RoPE.
        gh, gw = 21, 30
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((gw * 16, gh * 16))
        arr = np.asarray(img, dtype=np.float32) / 255.0
        patches = (
            arr.reshape(gh, 16, gw, 16, 3)
            .transpose(0, 2, 1, 3, 4)
            .reshape(1, gh * gw, 768)
        )
        pos_y, pos_x = np.meshgrid(np.arange(gh), np.arange(gw), indexing="ij")
        pixel_pos = np.stack([pos_x.ravel(), pos_y.ravel()], axis=-1)[
            None, :, :
        ].astype(np.int64)
        v_feats = self.vision_session.run(
            ["image_features"],
            {"pixel_values": patches, "pixel_position_ids": pixel_pos},
        )[0]
        ids = np.array(
            [[2, _BOI_TOKEN_ID] + [_IMAGE_TOKEN_ID] * v_feats.shape[0] + [_EOI_TOKEN_ID, 1]],
            dtype=np.int64,
        )
        vec = self.text_session.run(
            ["sentence_embedding"],
            {
                "input_ids": ids,
                "attention_mask": np.ones_like(ids),
                "image_features": v_feats,
                "video_features": self._empty,
                "audio_features": self._empty,
            },
        )[0][0]
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm

    def embed_image_tokens(self, image_bytes: bytes):
        """Return the global image embedding plus its 70 contextualized tokens."""
        if self.vision_session is None:
            raise RuntimeError("Vision encoder is not loaded")
        np = self._np
        from PIL import Image

        gh, gw = 21, 30
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize(
            (gw * 16, gh * 16)
        )
        arr = np.asarray(img, dtype=np.float32) / 255.0
        patches = (
            arr.reshape(gh, 16, gw, 16, 3)
            .transpose(0, 2, 1, 3, 4)
            .reshape(1, gh * gw, 768)
        )
        pos_y, pos_x = np.meshgrid(np.arange(gh), np.arange(gw), indexing="ij")
        pixel_pos = np.stack([pos_x.ravel(), pos_y.ravel()], axis=-1)[
            None, :, :
        ].astype(np.int64)
        v_feats = self.vision_session.run(
            ["image_features"],
            {"pixel_values": patches, "pixel_position_ids": pixel_pos},
        )[0]
        ids = np.array(
            [[2, _BOI_TOKEN_ID] + [_IMAGE_TOKEN_ID] * v_feats.shape[0] + [_EOI_TOKEN_ID, 1]],
            dtype=np.int64,
        )
        last_hidden, sentence = self.text_session.run(
            ["last_hidden_state", "sentence_embedding"],
            {
                "input_ids": ids,
                "attention_mask": np.ones_like(ids),
                "image_features": v_feats,
                "video_features": self._empty,
                "audio_features": self._empty,
            },
        )
        token_vecs = np.asarray(
            last_hidden[0, 2 : 2 + v_feats.shape[0], :], dtype=np.float32
        )
        token_norms = np.linalg.norm(token_vecs, axis=1, keepdims=True)
        token_vecs = token_vecs / np.maximum(token_norms, 1e-6)
        global_vec = np.asarray(sentence[0], dtype=np.float32)
        global_vec = global_vec / max(float(np.linalg.norm(global_vec)), 1e-6)
        return global_vec, token_vecs

    def classify_screen(self, image_bytes: bytes) -> SensoryObservation:
        np = self._np
        t0 = time.perf_counter()
        emb = self.embed_image_bytes(image_bytes)
        scores_arr = np.dot(self._screen_matrix, emb)
        scores = {
            self._screen_labels[i]: float(scores_arr[i])
            for i in range(len(self._screen_labels))
        }
        top_label = max(scores, key=scores.get)
        scene_sim: float | None = None
        changed = True
        if self._last_screen_embedding is not None:
            scene_sim = float(np.dot(self._last_screen_embedding, emb))
            changed = scene_sim < self.scene_change_threshold
        self._last_screen_embedding = emb
        return SensoryObservation(
            modality="vision",
            top_label=top_label,
            top_score=scores[top_label],
            scores=scores,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            scene_similarity=scene_sim,
            scene_changed=changed,
            reflex_emotion=self._screen_emotions.get(top_label, "neutral"),
        )

    def classify_displays(self, image_bytes_list: list[bytes]) -> list[SensoryObservation]:
        """Classify each display frame with the zero-decoder vision encoder."""
        results: list[SensoryObservation] = []
        for image_bytes in image_bytes_list or []:
            try:
                results.append(self.classify_screen(image_bytes))
            except Exception:  # noqa: BLE001 - keep remaining displays
                results.append(
                    SensoryObservation(
                        modality="vision",
                        top_label="unknown_display",
                        top_score=0.0,
                        scores={},
                        latency_ms=0.0,
                        reflex_emotion="neutral",
                    )
                )
        return results

    def describe_displays(self, image_bytes_list: list[bytes], *, audio_wav_bytes: bytes | None = None) -> str:
        """Build a compact Russian description of all captured displays and audio."""
        observations = self.classify_displays(image_bytes_list)
        parts = []
        if observations:
            for index, obs in enumerate(observations, start=1):
                parts.append(f"Дисплей {index}: {obs.top_label} ({obs.top_score:.2f})")
        else:
            parts.append("Дисплеи: нет данных")
        if audio_wav_bytes:
            try:
                audio_obs = self.classify_audio_wav(audio_wav_bytes)
                parts.append(f"Звук: {audio_obs.top_label} ({audio_obs.top_score:.2f})")
                if image_bytes_list:
                    try:
                        vibe = self.vibe_fusion(image_bytes_list[0], audio_wav_bytes)
                        if isinstance(vibe, dict):
                            mood = vibe.get("mood")
                            if mood:
                                parts.append(f"настроение={mood}")
                            etiquette = vibe.get("co_watching_etiquette")
                            if etiquette:
                                parts.append(f"этикет={etiquette}")
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                parts.append(f"Звук: ошибка ({str(exc)[:80]})")
        return "; ".join(parts)

    def classify_audio_wav(self, wav_bytes: bytes) -> SensoryObservation:
        np = self._np
        t0 = time.perf_counter()
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            sr = w.getframerate()
            pcm = w.readframes(w.getnframes())
        emb = self.embed_audio_pcm16(pcm, sample_rate=sr)
        scores_arr = np.dot(self._audio_matrix, emb)
        scores = {
            self._audio_labels[i]: float(scores_arr[i])
            for i in range(len(self._audio_labels))
        }
        top_label = max(scores, key=scores.get)
        return SensoryObservation(
            modality="audio",
            top_label=top_label,
            top_score=scores[top_label],
            scores=scores,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            reflex_emotion=self._audio_emotions.get(top_label, "neutral"),
        )


    def classify_multimodal(
        self, image_bytes: bytes, audio_wav_bytes: bytes
    ) -> SensoryObservation:
        """Fuse screen and system-audio embeddings into one bounded observation."""
        np = self._np
        started = time.perf_counter()
        screen_embedding = self.embed_image_bytes(image_bytes)
        audio_embedding = self._embed_audio_wav(audio_wav_bytes)
        screen_scores = {
            self._screen_labels[i]: float(np.dot(self._screen_matrix[i], screen_embedding))
            for i in range(len(self._screen_labels))
        }
        audio_scores = {
            self._audio_labels[i]: float(np.dot(self._audio_matrix[i], audio_embedding))
            for i in range(len(self._audio_labels))
        }
        screen_top = max(screen_scores, key=screen_scores.get)
        audio_top = max(audio_scores, key=audio_scores.get)
        vibe = float(np.dot(screen_embedding, audio_embedding))
        combined = screen_embedding + audio_embedding
        norm = float(np.linalg.norm(combined)) or 1.0
        combined = combined / norm
        combined_scores = {
            **{f"screen:{key}": value for key, value in screen_scores.items()},
            **{f"audio:{key}": value for key, value in audio_scores.items()},
        }
        top_score = max(screen_scores[screen_top], audio_scores[audio_top])
        top_label = screen_top if screen_scores[screen_top] >= audio_scores[audio_top] else audio_top
        scene_similarity: float | None = None
        changed = True
        if self._last_multimodal_screen_embedding is not None:
            scene_similarity = float(np.dot(self._last_multimodal_screen_embedding, screen_embedding))
            changed = scene_similarity < self.scene_change_threshold
        self._last_multimodal_screen_embedding = screen_embedding
        reflex = self.latent_reflex(
            screen_embedding=screen_embedding,
            audio_embedding=audio_embedding,
            screen_label=screen_top,
            audio_label=audio_top,
            scene_changed=changed,
        )
        return SensoryObservation(
            modality="audio_visual",
            top_label=top_label,
            top_score=top_score,
            scores=combined_scores,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            scene_similarity=scene_similarity,
            scene_changed=changed,
            reflex_emotion=reflex["emotion"],
            audio_top_label=audio_top,
            vibe_score=vibe,
            reflex=reflex,
        )

    def vibe_fusion(self, image_bytes: bytes, audio_wav_bytes: bytes) -> dict[str, Any]:
        """Return bounded audio-visual agreement and co-watching etiquette."""
        screen = self.embed_image_bytes(image_bytes)
        audio = self._embed_audio_wav(audio_wav_bytes)
        np = self._np
        screen_top = max(
            (label for label in self._screen_labels),
            key=lambda label: float(np.dot(self._screen_matrix[self._screen_labels.index(label)], screen)),
        )
        np = self._np
        audio_top = max(
            (label for label in self._audio_labels),
            key=lambda label: float(np.dot(self._audio_matrix[self._audio_labels.index(label)], audio)),
        )
        vibe = float(np.dot(screen, audio))
        emotion = self._audio_emotions.get(audio_top) or self._screen_emotions.get(screen_top, "neutral")
        return {
            "screen_label": screen_top,
            "audio_label": audio_top,
            "vibe_score": vibe,
            "mood": emotion,
            "co_watching_etiquette": (
                "react_visually_during_dialogue_speak_in_pauses"
                if audio_top in {"human_speech_ru"}
                else "comment_briefly"
            ),
            "raw_media_persisted": False,
        }

    def latent_reflex(
        self,
        *,
        screen_embedding: Any | None = None,
        audio_embedding: Any | None = None,
        screen_label: str | None = None,
        audio_label: str | None = None,
        scene_changed: bool = False,
    ) -> dict[str, Any]:
        """Map embeddings/labels to a bounded VRM emotion and look target."""
        np = self._np
        screen_score = 0.0
        audio_score = 0.0
        if screen_embedding is not None:
            screen_scores = {
                label: float(np.dot(self._screen_matrix[i], screen_embedding))
                for i, label in enumerate(self._screen_labels)
            }
            screen_label = screen_label or max(screen_scores, key=screen_scores.get)
            screen_score = screen_scores.get(screen_label or "", 0.0)
        if audio_embedding is not None:
            audio_scores = {
                label: float(np.dot(self._audio_matrix[i], audio_embedding))
                for i, label in enumerate(self._audio_labels)
            }
            audio_label = audio_label or max(audio_scores, key=audio_scores.get)
            audio_score = audio_scores.get(audio_label or "", 0.0)
        emotion = (
            self._audio_emotions.get(audio_label or "")
            or self._screen_emotions.get(screen_label or "")
            or "neutral"
        )
        intensity = max(0.0, min(1.0, max(screen_score, audio_score)))
        return {
            "emotion": emotion,
            "intensity": intensity,
            "look_target": "screen" if scene_changed else "avatar",
            "latency_budget_ms": 20,
            "llm_bypass": True,
        }

    def latent_reflex_from_observation(self, observation: SensoryObservation) -> dict[str, Any]:
        return self.latent_reflex(
            screen_label=observation.top_label if observation.modality in {"vision", "audio_visual"} else None,
            audio_label=observation.audio_top_label,
            scene_changed=observation.scene_changed,
        )

    def scene_change_event(self, observation: SensoryObservation) -> dict[str, Any]:
        return {
            "status": "triggered" if observation.scene_changed else "stable",
            "scene_similarity": observation.scene_similarity,
            "top_label": observation.top_label,
            "raw_frame_persisted": False,
        }

    def _embed_audio_wav(self, wav_bytes: bytes):
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        return self.embed_audio_pcm16(pcm, sample_rate=sample_rate)


class EpisodicVectorMemory:
    """Compact cross-modal vector memory without raw media."""

    def __init__(self, *, max_items: int = 3600, dimensions: int = 768) -> None:
        self.max_items = max(1, min(int(max_items), 100000))
        self.dimensions = max(1, int(dimensions))
        self._items: list[dict[str, Any]] = []

    def add(
        self,
        vector: Any,
        *,
        modality: str = "unknown",
        summary: str = "",
        source: str = "eg2",
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        values = [float(item) for item in vector]
        if len(values) != self.dimensions:
            raise ValueError("vector dimensions do not match episodic memory")
        norm = (sum(value * value for value in values) ** 0.5) or 1.0
        item = {
            "vector": [value / norm for value in values],
            "modality": str(modality)[:40],
            "summary": str(summary or "")[:500],
            "source": str(source or "eg2")[:80],
            "timestamp": float(time.time() if timestamp is None else timestamp),
        }
        self._items.append(item)
        if len(self._items) > self.max_items:
            self._items.pop(0)
        return {"status": "retained", "count": len(self._items), "raw_media_persisted": False}

    def search(self, query_vector: Any, *, top_k: int = 5, modality: str | None = None) -> list[dict[str, Any]]:
        values = [float(item) for item in query_vector]
        if len(values) != self.dimensions:
            raise ValueError("query vector dimensions do not match episodic memory")
        norm = (sum(value * value for value in values) ** 0.5) or 1.0
        query = [value / norm for value in values]
        results: list[dict[str, Any]] = []
        for item in self._items:
            if modality is not None and item["modality"] != modality:
                continue
            score = sum(a * b for a, b in zip(query, item["vector"]))
            results.append(
                {
                    "score": score,
                    "modality": item["modality"],
                    "summary": item["summary"],
                    "source": item["source"],
                    "timestamp": item["timestamp"],
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[: max(1, min(int(top_k), 100))]

    def state(self) -> dict[str, Any]:
        return {
            "items": len(self._items),
            "dimensions": self.dimensions,
            "max_items": self.max_items,
            "raw_media_persisted": False,
        }


    def read_audio_tokens(self, audio_wav_bytes: bytes, *, top_k: int = 5) -> list[dict[str, Any]]:
        """Read fast Russian token candidates from an audio slice."""
        return RussianEg2Reader(self).read(audio_wav_bytes, top_k=top_k)

    def project_audio_tokens(self, audio_wav_bytes: bytes) -> list[float]:
        """Project an audio slice into Russian token logits."""
        with wave.open(io.BytesIO(audio_wav_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        embedding = self.embed_audio_pcm16(pcm, sample_rate=sample_rate)
        return RussianEg2Reader(self).project(embedding)



class RussianEg2Reader:
    """Bounded linear reader from audio embeddings to Russian token candidates.

    The reader uses a fixed token-prototype matrix as its linear projection
    layer.  A trained projector can replace this prototype matrix later without
    changing the public API.
    """

    DEFAULT_TOKENS = (
        "экран", "окно", "код", "ошибка", "музыка", "речь", "пауза", "игра",
        "кнопка", "текст", "файл", "браузер",
    )

    def __init__(self, cortex: "EmbeddingGemmaSensoryCortex", tokens: Iterable[str] | None = None) -> None:
        self.cortex = cortex
        self.tokens = tuple(str(token).strip()[:40] for token in (tokens or self.DEFAULT_TOKENS) if str(token).strip())
        if not self.tokens:
            raise ValueError("Russian eg2 reader requires at least one token")
        self._matrix = __import__("numpy").stack([cortex.embed_text(f"title: none | text: {token}") for token in self.tokens])

    def project(self, embedding: Any) -> list[float]:
        """Project an audio embedding into token logits."""
        vector = [float(item) for item in embedding]
        if len(vector) != self._matrix.shape[1]:
            raise ValueError("audio embedding dimensions do not match the reader")
        return [float(score) for score in self._np.dot(self._matrix, vector)]

    def read_embedding(self, embedding: Any, *, top_k: int = 5) -> list[dict[str, Any]]:
        scores = self.project(embedding)
        order = sorted(range(len(self.tokens)), key=lambda i: scores[i], reverse=True)
        return [
            {"token": self.tokens[i], "score": scores[i]}
            for i in order[: max(1, min(int(top_k), len(self.tokens)))]
        ]

    def read(self, audio_wav_bytes: bytes, *, top_k: int = 5) -> list[dict[str, Any]]:
        with wave.open(io.BytesIO(audio_wav_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        embedding = self.cortex.embed_audio_pcm16(pcm, sample_rate=sample_rate)
        return self.read_embedding(embedding, top_k=top_k)

    @property
    def _np(self):
        return self.cortex._np



class RollingMediaBuffer:
    """Bounded rolling buffer for compact media observations.

    The buffer keeps the recent sensory timeline (about five minutes by default)
    without raw audio/video.  It stores normalized EG2 vectors and compact
    metadata so an agent can quickly recall what was on screen, in audio, or in
    music without replaying or archiving media.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 300.0,
        max_items: int = 1800,
        dimensions: int = 768,
    ) -> None:
        self.window_seconds = max(10.0, min(float(window_seconds), 3600.0))
        self.max_items = max(1, min(int(max_items), 100000))
        self.dimensions = max(1, int(dimensions))
        self._items: list[dict[str, Any]] = []

    def observe(
        self,
        observation: Any,
        *,
        now: float | None = None,
        modality: str | None = None,
        summary: str | None = None,
        vector: Any | None = None,
        source: str = "eg2",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = float(time.time() if now is None else now)
        payload = observation.to_dict() if hasattr(observation, "to_dict") else (
            observation if isinstance(observation, dict) else {"summary": str(observation or "")}
        )
        kind = str(modality or payload.get("modality") or "media")[:40]
        text = str(summary if summary is not None else payload.get("summary") or payload.get("top_label") or "")[:500]
        normalized_vector: list[float] | None = None
        if vector is not None:
            values = [float(item) for item in vector]
            if len(values) != self.dimensions:
                raise ValueError("media buffer vector dimensions do not match")
            norm = (sum(value * value for value in values) ** 0.5) or 1.0
            normalized_vector = [value / norm for value in values]
        item = {
            "timestamp": timestamp,
            "modality": kind,
            "summary": text,
            "source": str(source or "eg2")[:80],
            "top_label": str(payload.get("top_label") or "")[:120],
            "audio_top_label": str(payload.get("audio_top_label") or "")[:120] or None,
            "vibe_score": payload.get("vibe_score"),
            "scene_changed": bool(payload.get("scene_changed", False)),
            "reflex_emotion": str(payload.get("reflex_emotion") or "neutral")[:40],
            "metadata": dict(metadata or {}),
            "vector": normalized_vector,
            "raw_media_persisted": False,
        }
        self._items.append(item)
        self._prune(timestamp)
        if len(self._items) > self.max_items:
            self._items.pop(0)
        return self.state(now=timestamp)

    def snapshot(
        self,
        *,
        seconds: float | None = None,
        modalities: Iterable[str] | None = None,
        limit: int = 100,
        now: float | None = None,
        include_vectors: bool = False,
    ) -> dict[str, Any]:
        moment = float(time.time() if now is None else now)
        window = self.window_seconds if seconds is None else max(1.0, min(float(seconds), self.window_seconds))
        cutoff = moment - window
        allowed = {str(item).strip() for item in modalities} if modalities else None
        selected = [
            item for item in self._items
            if item["timestamp"] >= cutoff and (allowed is None or item["modality"] in allowed)
        ]
        selected = selected[-max(1, min(int(limit), 1000)):]
        latest: dict[str, dict[str, Any]] = {}
        for item in selected:
            latest[item["modality"]] = self._compact(item, include_vectors=include_vectors)
        return {
            "window_seconds": window,
            "now": moment,
            "count": len(selected),
            "modalities": sorted({item["modality"] for item in selected}),
            "latest_by_modality": latest,
            "items": [self._compact(item, include_vectors=include_vectors) for item in selected],
            "raw_media_persisted": False,
        }

    def latest(self, modality: str, *, now: float | None = None) -> dict[str, Any] | None:
        moment = float(time.time() if now is None else now)
        cutoff = moment - self.window_seconds
        for item in reversed(self._items):
            if item["timestamp"] >= cutoff and item["modality"] == str(modality):
                return self._compact(item)
        return None

    def search(
        self,
        query_vector: Any,
        *,
        top_k: int = 5,
        modalities: Iterable[str] | None = None,
        seconds: float | None = None,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        moment = float(time.time() if now is None else now)
        window = self.window_seconds if seconds is None else max(1.0, min(float(seconds), self.window_seconds))
        cutoff = moment - window
        values = [float(item) for item in query_vector]
        if len(values) != self.dimensions:
            raise ValueError("query vector dimensions do not match media buffer")
        norm = (sum(value * value for value in values) ** 0.5) or 1.0
        query = [value / norm for value in values]
        allowed = {str(item).strip() for item in modalities} if modalities else None
        results: list[dict[str, Any]] = []
        for item in self._items:
            if item["timestamp"] < cutoff or item["vector"] is None:
                continue
            if allowed is not None and item["modality"] not in allowed:
                continue
            score = sum(a * b for a, b in zip(query, item["vector"]))
            results.append({"score": score, **self._compact(item)})
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[: max(1, min(int(top_k), 100))]

    def state(self, *, now: float | None = None) -> dict[str, Any]:
        moment = float(time.time() if now is None else now)
        self._prune(moment)
        counts: dict[str, int] = {}
        for item in self._items:
            counts[item["modality"]] = counts.get(item["modality"], 0) + 1
        return {
            "window_seconds": self.window_seconds,
            "items": len(self._items),
            "max_items": self.max_items,
            "counts_by_modality": counts,
            "oldest_timestamp": self._items[0]["timestamp"] if self._items else None,
            "newest_timestamp": self._items[-1]["timestamp"] if self._items else None,
            "raw_media_persisted": False,
        }

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._items = [item for item in self._items if item["timestamp"] >= cutoff]

    @staticmethod
    def _compact(item: dict[str, Any], *, include_vectors: bool = False) -> dict[str, Any]:
        result = {
            "timestamp": item["timestamp"],
            "modality": item["modality"],
            "summary": item["summary"],
            "source": item["source"],
            "top_label": item["top_label"],
            "audio_top_label": item["audio_top_label"],
            "vibe_score": item["vibe_score"],
            "scene_changed": item["scene_changed"],
            "reflex_emotion": item["reflex_emotion"],
            "metadata": item["metadata"],
            "raw_media_persisted": False,
        }
        if include_vectors and item["vector"] is not None:
            result["vector"] = item["vector"]
        return result



__all__ = [
    "DEFAULT_EG2_ONNX_ROOT",
    "EmbeddingGemmaSensoryCortex",
    "EpisodicVectorMemory",
    "RollingMediaBuffer",
    "RussianEg2Reader",
    "SensoryObservation",
]
