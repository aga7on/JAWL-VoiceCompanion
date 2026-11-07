"""Affective and Turn-Taking Engine for JAWL VoiceCompanion.

Implements:
1. Russell's Circumplex Model (Valence & Arousal) in [-1.0, 1.0].
2. Real-time acoustic energy (RMS, dBFS) and dynamic arousal tracking from PCM16 stream.
3. Natural dialogue gap detection (>= 1.5s silence) for respectful turn-taking without interrupting.
4. FireRedChat / Full-Duplex-Bench style backchanneling triggers (micro-reactions during active playback).
5. Direct mapping from (Valence, Arousal) to VRM BlendShapes (happy, relaxed, angry, sad, surprised, neutral).
"""

from __future__ import annotations

import collections
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Standard Backchannel Cues mapped to emotional quadrants
BACKCHANNEL_CUES: Dict[str, List[str]] = {
    "surprised": ["Ого!", "Ничего себе!", "Да ладно?!", "Вот это да!"],
    "happy": ["Класс!", "Круто!", "Отлично!", "Хах, здорово!"],
    "angry": ["Жесть...", "Ну и дела...", "Серьёзно?!", "Вот подстава..."],
    "sad": ["Эх...", "Печально...", "Жаль...", "Грустно..."],
    "relaxed": ["Хм...", "М-м...", "Понятно...", "Так-так..."],
    "neutral": ["Угу", "Хм", "Да", "Ясно"],
}


class AffectiveEngine:
    """Computes real-time emotional state and turn-taking opportunity from audio and scene cues."""

    def __init__(
        self,
        *,
        silence_threshold_db: float = -45.0,
        min_gap_seconds: float = 1.5,
        history_len: int = 50,
        decay_rate: float = 0.05,
        episodic_memory: Any | None = None,
        smtc_adapter: Any | None = None,
    ) -> None:
        self.silence_threshold_db = float(silence_threshold_db)
        self.min_gap_seconds = max(0.05, float(min_gap_seconds))
        self.history_len = max(10, int(history_len))
        self.decay_rate = max(0.001, min(float(decay_rate), 0.5))
        self.episodic_memory = episodic_memory
        self.smtc_adapter = smtc_adapter

        self._lock = threading.RLock()
        self._valence: float = 0.0
        self._arousal: float = -0.2  # default gentle calm
        self._last_rms: float = 0.0
        self._last_db: float = -90.0
        self._last_centroid: float = 0.0
        self._last_hnr: float = 0.0
        self._last_dsp_valence: float = 0.0

        # Dynamics buffers
        self._rms_history: collections.deque[float] = collections.deque(maxlen=self.history_len)
        self._last_chunk_time: float = time.monotonic()
        self._silence_start_time: Optional[float] = None
        self._last_sound_time: float = time.monotonic()
        self._backchannel_cooldown: float = 0.0
        self._last_backchannel_time: float = 0.0
        self._last_taste_sample_time: float = 0.0

    @property
    def valence(self) -> float:
        with self._lock:
            return self._valence

    @property
    def arousal(self) -> float:
        with self._lock:
            return self._arousal

    def set_valence(self, valence: float) -> None:
        """Update valence based on semantic/visual scene evaluation [-1.0, 1.0]."""
        with self._lock:
            self._valence = max(-1.0, min(float(valence), 1.0))

    def process_pcm_chunk(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 44100,
        channels: int = 2,
    ) -> dict[str, Any]:
        """Process incoming raw PCM16 chunk, calculate acoustic arousal and silence gap."""
        if not pcm_bytes:
            return self.get_state()

        now = time.monotonic()
        with self._lock:
            # Convert PCM16 bytes to float32 samples [-1.0, 1.0]
            try:
                samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            except Exception as exc:
                logger.warning("Failed to decode PCM chunk: %s", exc)
                return self.get_state()

            if samples.size == 0:
                return self.get_state()

            # Root Mean Square energy
            rms = float(np.sqrt(np.mean(samples ** 2)))
            self._last_rms = rms

            # dBFS calculation (avoid log(0))
            db = 20.0 * math.log10(max(rms, 1e-6))
            self._last_db = round(db, 2)
            self._rms_history.append(rms)

            # Silence and Turn-Taking tracking
            is_silent = db < self.silence_threshold_db
            if is_silent:
                if self._silence_start_time is None:
                    self._silence_start_time = now
                silence_duration = now - self._silence_start_time
            else:
                self._silence_start_time = None
                self._last_sound_time = now
                silence_duration = 0.0

            is_dialogue_gap = silence_duration >= self.min_gap_seconds

            # Dynamic Arousal estimation:
            # Map dBFS [-60.0, 0.0] to raw target arousal [-1.0, 1.0]
            norm_arousal = max(-1.0, min(1.0, (db + 35.0) / 25.0))

            # Detect acoustic energy spikes (short-term vs rolling baseline)
            baseline_rms = float(np.mean(self._rms_history)) if self._rms_history else rms
            spike_delta = max(0.0, rms - baseline_rms)

            # Smoothly update arousal
            target_arousal = min(1.0, norm_arousal + spike_delta * 2.0)
            self._arousal = round(self._arousal * 0.7 + target_arousal * 0.3, 3)

            # DSP Spectral Centroid & HNR Analysis (< 0.2ms)
            if not is_silent and len(samples) >= 128:
                centroid, hnr, dsp_valence = self._compute_dsp_features(samples, sample_rate)
                self._last_centroid = round(centroid, 1)
                self._last_hnr = round(hnr, 3)
                self._last_dsp_valence = round(dsp_valence, 3)
                # Gently blend DSP valence into current valence
                self._valence = round(max(-1.0, min(1.0, self._valence * 0.90 + dsp_valence * 0.10)), 3)
            elif is_silent:
                # Slowly relax valence toward neutral 0.0 in deep silence
                self._valence = round(self._valence * (1.0 - self.decay_rate), 3)

            # Periodic Music Taste sampling (>= 10s cooldown)
            if not is_silent:
                try:
                    self.sample_music_taste(samples)
                except Exception:
                    pass

            # Determine backchannel eligibility
            backchannel_ready = False
            backchannel_cue: Optional[str] = None
            instant_arousal = max(self._arousal, target_arousal if spike_delta > 0.05 else self._arousal)
            dominant_expr, blend_weights = self._compute_expressions(self._valence, instant_arousal)

            # Condition: high arousal / spike, active playback (not in silence gap), and cooldown passed (>= 4s)
            if (
                not is_dialogue_gap
                and (spike_delta > 0.08 or self._arousal > 0.6)
                and (now - self._last_backchannel_time >= 4.0)
            ):
                backchannel_ready = True
                self._last_backchannel_time = now
                cues = BACKCHANNEL_CUES.get(dominant_expr, BACKCHANNEL_CUES["neutral"])
                # Deterministic selection based on timestamp
                idx = int(now * 10) % len(cues)
                backchannel_cue = cues[idx]

            self._last_chunk_time = now

            return {
                "valence": self._valence,
                "arousal": self._arousal,
                "rms": round(rms, 5),
                "dbfs": self._last_db,
                "centroid_hz": self._last_centroid,
                "hnr": self._last_hnr,
                "dsp_valence": self._last_dsp_valence,
                "silence_duration_sec": round(silence_duration, 2),
                "is_dialogue_gap": is_dialogue_gap,
                "backchannel_ready": backchannel_ready,
                "backchannel_cue": backchannel_cue,
                "dominant_expression": dominant_expr,
                "blend_weights": blend_weights,
            }

    @staticmethod
    def _compute_dsp_features(samples: np.ndarray | bytes, sample_rate: int = 44100) -> Tuple[float, float, float]:
        """Compute Spectral Centroid (Hz), HNR, and DSP Valence [-1.0, 1.0] in < 0.2ms."""
        if isinstance(samples, (bytes, bytearray)):
            try:
                samples = np.frombuffer(samples, dtype=np.int16).astype(np.float32) / 32768.0
            except Exception:
                return 0.0, 0.0, 0.0
        if not isinstance(samples, np.ndarray) or len(samples) < 128:
            return 0.0, 0.0, 0.0

        # Hanning window to prevent edge spectral leakage
        win = np.hanning(len(samples))
        w_samples = samples * win

        fft_vals = np.abs(np.fft.rfft(w_samples))
        freqs = np.fft.rfftfreq(len(samples), 1.0 / sample_rate)
        sum_mag = np.sum(fft_vals)
        if sum_mag < 1e-5:
            return 0.0, 0.0, 0.0

        centroid = float(np.sum(freqs * fft_vals) / sum_mag)

        # Normalized autocorrelation for periodic harmonic detection (pitch region 75Hz - 1200Hz)
        corr = np.correlate(samples, samples, mode="full")
        mid = len(corr) // 2
        r_zero = corr[mid]
        if r_zero < 1e-6:
            hnr = 0.0
        else:
            min_lag = max(1, int(sample_rate / 1200))
            max_lag = max(min_lag + 1, int(sample_rate / 75))
            valid_corr = corr[mid + min_lag : mid + min_lag + max_lag]
            if len(valid_corr) > 0:
                max_r = float(np.max(valid_corr))
                hnr = max(0.0, min(1.0, max_r / r_zero))
            else:
                hnr = 0.0

        if centroid < 250.0:
            centroid_score = -0.6
        elif centroid > 5000.0:
            centroid_score = -0.8
        elif 600.0 <= centroid <= 3200.0:
            centroid_score = 0.5
        else:
            centroid_score = 0.0

        if centroid > 5000.0 or centroid < 250.0:
            # Extreme piercing screamer or sub-bass drone induces tension / negative valence
            dsp_valence = max(-1.0, min(-0.1, centroid_score * 0.7 + (hnr - 0.5) * 0.3))
        else:
            hnr_score = (hnr - 0.35) * 1.4
            dsp_valence = max(-1.0, min(1.0, centroid_score * 0.5 + hnr_score * 0.5))
        return centroid, hnr, dsp_valence

    def update_semantic_valence(self, text: str, *, weight: float = 0.35) -> float:
        """Classify Russian speech text sentiment and blend into valence."""
        if not text or not text.strip():
            return self._valence

        lower = text.lower()
        pos_words = {
            "отлично", "круто", "класс", "красиво", "победа", "ура", "супер",
            "чудесно", "люблю", "прекрасно", "кайф", "счастье", "восторг", "успех",
            "здорово", "молодец", "хорошо", "радость", "весело", "приятно"
        }
        neg_words = {
            "грустно", "печаль", "боль", "страх", "ужас", "кошмар", "смерть",
            "провал", "плохо", "жесть", "беда", "ошибка", "ненавижу", "зло",
            "враг", "мрак", "тревога", "убит", "крик", "отстой", "ужасно"
        }

        tokens = set(lower.replace(".", " ").replace("!", " ").replace("?", " ").replace(",", " ").split())
        pos_hits = len(tokens & pos_words)
        neg_hits = len(tokens & neg_words)

        if pos_hits == 0 and neg_hits == 0:
            return self._valence

        target_valence = (pos_hits - neg_hits) / max(1.0, float(pos_hits + neg_hits))
        with self._lock:
            w = max(0.05, min(float(weight), 0.9))
            self._valence = round(max(-1.0, min(1.0, self._valence * (1.0 - w) + target_valence * w)), 3)
            return self._valence

    def sample_music_taste(
        self,
        samples: np.ndarray | None = None,
        smtc_info: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Sample current music playback and save taste record to episodic memory (10s interval)."""
        now = time.monotonic()
        if not force and (now - self._last_taste_sample_time < 10.0):
            return None

        track = smtc_info
        if track is None and self.smtc_adapter is not None:
            track = self.smtc_adapter.poll()

        if not track or not track.get("has_active_playback"):
            return None

        self._last_taste_sample_time = now

        # Compute 16-dim acoustic vector: [rms, dbfs/100, centroid/5000, hnr, valence, arousal, 10-band FFT]
        vec = [
            float(self._last_rms),
            float(self._last_db / 100.0),
            float(min(1.0, self._last_centroid / 5000.0)),
            float(self._last_hnr),
            float(self._valence),
            float(self._arousal),
        ]

        if samples is not None and len(samples) >= 64:
            fft_mag = np.abs(np.fft.rfft(samples[:256]))
            step = max(1, len(fft_mag) // 10)
            for i in range(10):
                band = fft_mag[i * step : (i + 1) * step]
                val = float(np.mean(band)) if len(band) > 0 else 0.0
                vec.append(round(min(1.0, val / 10.0), 3))
        else:
            vec.extend([0.0] * 10)

        vec = vec[:16]

        if self.episodic_memory is not None and hasattr(self.episodic_memory, "save_taste_record"):
            return self.episodic_memory.save_taste_record(
                track_info=track,
                audio_vector=vec,
                valence=self._valence,
                arousal=self._arousal,
            )

        return {"status": "sampled", "track": track.get("title", ""), "audio_vector": vec}

    @staticmethod
    def _compute_expressions(v: float, a: float) -> Tuple[str, Dict[str, float]]:
        """Map 2D (Valence, Arousal) to 5 VRM BlendShape weights."""
        pos_v = max(0.0, v)
        neg_v = max(0.0, -v)
        pos_a = max(0.0, a)
        neg_a = max(0.0, -a)

        weights = {
            "happy": round(pos_v * pos_a, 3),
            "relaxed": round(pos_v * neg_a, 3),
            "angry": round(neg_v * pos_a, 3),
            "sad": round(neg_v * neg_a, 3),
            "surprised": round(pos_a * (1.0 - abs(v)), 3),
        }

        # Find dominant expression
        max_name = "neutral"
        max_val = 0.08  # threshold below which character stays neutral
        for name, val in weights.items():
            if val > max_val:
                max_val = val
                max_name = name

        return max_name, weights

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            silence_duration = 0.0
            if self._silence_start_time is not None:
                silence_duration = now - self._silence_start_time

            dominant_expr, blend_weights = self._compute_expressions(self._valence, self._arousal)
            return {
                "valence": self._valence,
                "arousal": self._arousal,
                "last_rms": round(self._last_rms, 5),
                "last_dbfs": self._last_db,
                "last_centroid_hz": self._last_centroid,
                "last_hnr": self._last_hnr,
                "last_dsp_valence": self._last_dsp_valence,
                "silence_duration_sec": round(silence_duration, 2),
                "is_dialogue_gap": silence_duration >= self.min_gap_seconds,
                "dominant_expression": dominant_expr,
                "blend_weights": blend_weights,
            }
