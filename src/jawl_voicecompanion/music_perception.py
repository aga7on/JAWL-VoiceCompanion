"""Lightweight CPU/RAM music harmonic and emotional analyzer.

Strict adherence to JAWL resource invariants:
- Pure CPU/RAM execution using standard NumPy DSP (no PyTorch, zero GPU VRAM allocation).
- Implements AudioDescriptionProvider protocol for bounded audio understanding.
- Negative controls: silence (< -55 dBFS), pure noise, and speech-only audio are strictly
  rejected from producing spurious musical key, BPM, or emotion labels.
- Independent overlap detector for mixed speech+music signals.
- Computes Krumhansl-Schmuckler chroma key correlation, spectral flux BPM tracking,
  and Russell circumplex valence/arousal/mood mappings.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import enum
import math
import time
from typing import Any

import numpy as np

# Pitches in 12-TET semitone order starting at C
PITCH_CLASSES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"
)

# Krumhansl-Schmuckler key profiles
KRUMHANSL_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
    dtype=np.float64,
)
KRUMHANSL_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    dtype=np.float64,
)


@dataclass(frozen=True)
class MusicPerceptionResult:
    """Rich acoustic and musical perception result for living companion cognitive loops."""

    schema_version: int = 1
    clip_id: str = ""
    is_music: bool = False
    kind: str = "unknown"  # "music", "speech", "sound", "unknown"
    confidence: float = 0.0
    bpm: float | None = None
    tempo_confidence: float = 0.0
    key: str | None = None
    key_confidence: float = 0.0
    mode: str | None = None  # "major", "minor", or None
    valence: float = 0.0  # [-1.0, 1.0]: negative=somber/sad, positive=bright/uplifting
    arousal: float = 0.0  # [0.0, 1.0]: calm/gentle vs intense/energetic
    mood: str = ""  # "calm", "energetic", "melancholic", "dramatic", "reflective"
    tags: tuple[str, ...] = ()
    description: str = ""
    duration_seconds: float = 0.0
    rms_dbfs: float = -100.0
    spectral_flatness: float = 0.0
    spectral_centroid_hz: float = 0.0
    harmonicity: float = 0.0
    speech_overlap: bool = False
    candidate_hypotheses: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "clip_id": self.clip_id,
            "is_music": self.is_music,
            "kind": self.kind,
            "confidence": round(self.confidence, 4),
            "bpm": round(self.bpm, 1) if self.bpm is not None else None,
            "tempo_confidence": round(self.tempo_confidence, 4),
            "key": self.key,
            "key_confidence": round(self.key_confidence, 4),
            "mode": self.mode,
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "mood": self.mood,
            "tags": list(self.tags),
            "description": self.description,
            "duration_seconds": round(self.duration_seconds, 3),
            "rms_dbfs": round(self.rms_dbfs, 2),
            "spectral_flatness": round(self.spectral_flatness, 4),
            "spectral_centroid_hz": round(self.spectral_centroid_hz, 1),
            "harmonicity": round(self.harmonicity, 4),
            "speech_overlap": self.speech_overlap,
            "candidate_hypotheses": [dict(h) for h in self.candidate_hypotheses],
        }


class MusicPerceptionAnalyzer:
    """CPU-only music, harmonic, rhythmic, and emotion perception engine.

    Implements AudioDescriptionProvider protocol.
    """

    def __init__(
        self,
        *,
        name: str = "cpu-music-perception",
        silence_threshold_dbfs: float = -55.0,
        noise_flatness_threshold: float = 0.55,
        min_music_key_corr: float = 0.52,
        min_chroma_concentration: float = 0.42,
        min_duration_seconds: float = 0.1,
        max_duration_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.silence_threshold_dbfs = silence_threshold_dbfs
        self.noise_flatness_threshold = noise_flatness_threshold
        self.min_music_key_corr = min_music_key_corr
        self.min_chroma_concentration = min_chroma_concentration
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds

    @staticmethod
    def _to_mono_float(pcm16: bytes, channels: int) -> np.ndarray:
        if not pcm16 or channels not in (1, 2):
            return np.empty(0, dtype=np.float32)
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if channels == 2:
            return 0.5 * (samples[0::2] + samples[1::2])
        return samples

    @staticmethod
    def _compute_rms_dbfs(samples: np.ndarray) -> float:
        if len(samples) == 0:
            return -100.0
        mean_sq = float(np.mean(samples ** 2))
        if mean_sq <= 1e-12:
            return -100.0
        return float(20.0 * math.log10(math.sqrt(mean_sq)))

    @staticmethod
    def _compute_stft_frames(
        samples: np.ndarray,
        sample_rate: int,
        fft_size: int = 2048,
        hop_size: int = 1024,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute STFT magnitudes, frequencies, and frame count."""
        total_len = len(samples)
        if total_len < fft_size:
            padded = np.zeros(fft_size, dtype=np.float32)
            padded[:total_len] = samples
            samples = padded
            total_len = fft_size

        num_frames = max(1, (total_len - fft_size) // hop_size + 1)
        window = np.hanning(fft_size).astype(np.float32)
        freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate).astype(np.float32)

        frames = []
        for i in range(num_frames):
            start = i * hop_size
            end = start + fft_size
            if end <= len(samples):
                seg = samples[start:end] * window
            else:
                seg = np.zeros(fft_size, dtype=np.float32)
                tail = samples[start:]
                seg[: len(tail)] = tail * window[: len(tail)]
            spec = np.abs(np.fft.rfft(seg))
            frames.append(spec)

        return np.array(frames, dtype=np.float32), freqs, freqs[1:]

    @classmethod
    def _compute_spectral_stats(
        cls, magnitudes: np.ndarray, freqs: np.ndarray
    ) -> tuple[float, float, float]:
        """Compute average spectral flatness, spectral centroid, and harmonicity."""
        num_frames = len(magnitudes)
        if num_frames == 0:
            return 1.0, 0.0, 0.0

        mean_mag = np.mean(magnitudes, axis=0)
        pos_mag = np.maximum(mean_mag, 1e-12)

        geom_mean = float(np.exp(np.mean(np.log(pos_mag))))
        arith_mean = float(np.mean(pos_mag))
        flatness = float(geom_mean / (arith_mean + 1e-12))

        sum_mag = float(np.sum(mean_mag))
        if sum_mag > 1e-12:
            centroid = float(np.sum(freqs * mean_mag) / sum_mag)
        else:
            centroid = 0.0

        band_mask = (freqs >= 80.0) & (freqs <= 2500.0)
        if np.any(band_mask):
            band_vals = mean_mag[band_mask]
            peak = float(np.max(band_vals))
            avg = float(np.mean(band_vals)) + 1e-12
            harmonicity = min(1.0, max(0.0, (peak / avg - 1.0) / 12.0))
        else:
            harmonicity = 0.0

        return flatness, centroid, harmonicity

    @classmethod
    def _detect_chroma_and_key(
        cls, magnitudes: np.ndarray, freqs: np.ndarray
    ) -> tuple[str | None, str | None, float, np.ndarray, float]:
        """Map STFT magnitudes to 12-TET chroma, compute concentration, and match key profiles."""
        chroma = np.zeros(12, dtype=np.float64)
        mean_mag = np.mean(magnitudes, axis=0)

        for f, mag in zip(freqs, mean_mag):
            if 65.0 <= f <= 2100.0:
                pitch_class = int(round(69.0 + 12.0 * math.log2(f / 440.0))) % 12
                chroma[pitch_class] += float(mag)

        chroma_sum = float(np.sum(chroma))
        if chroma_sum <= 1e-9:
            return None, None, 0.0, chroma, 0.0

        chroma_norm = chroma / chroma_sum
        top3_concentration = float(np.sum(np.sort(chroma_norm)[::-1][:3]))

        std_val = float(np.std(chroma_norm))
        if std_val < 1e-6:
            return None, None, 0.0, chroma_norm, top3_concentration

        c_standardized = (chroma_norm - np.mean(chroma_norm)) / std_val

        best_key: str | None = None
        best_mode: str | None = None
        best_corr: float = -1.0

        for root in range(12):
            for mode_name, profile in (("major", KRUMHANSL_MAJOR), ("minor", KRUMHANSL_MINOR)):
                shifted = np.roll(profile, root)
                shifted_std = (shifted - np.mean(shifted)) / np.std(shifted)
                corr = float(np.dot(c_standardized, shifted_std) / 12.0)
                if corr > best_corr:
                    best_corr = corr
                    best_mode = mode_name
                    best_key = f"{PITCH_CLASSES[root]} {mode_name}"

        return best_key, best_mode, max(0.0, min(1.0, best_corr)), chroma_norm, top3_concentration

    @classmethod
    def _estimate_tempo(
        cls, magnitudes: np.ndarray, sample_rate: int, hop_size: int = 1024
    ) -> tuple[float | None, float]:
        """Estimate BPM and tempo confidence from spectral flux autocorrelation."""
        if len(magnitudes) < 16:
            return None, 0.0

        diffs = np.maximum(0.0, magnitudes[1:] - magnitudes[:-1])
        onset_env = np.sum(diffs, axis=1)

        onset_std = float(np.std(onset_env))
        if onset_std < 1e-6:
            return None, 0.0

        env_norm = (onset_env - np.mean(onset_env)) / onset_std
        acorr = np.correlate(env_norm, env_norm, mode="full")
        acorr = acorr[len(acorr) // 2 :]

        fps = float(sample_rate) / float(hop_size)
        min_lag = max(1, int(fps * 60.0 / 180.0))
        max_lag = min(len(acorr) - 1, int(fps * 60.0 / 60.0))

        if min_lag >= max_lag:
            return None, 0.0

        search_slice = acorr[min_lag : max_lag + 1]
        best_idx = int(np.argmax(search_slice))
        peak_lag = min_lag + best_idx
        peak_val = float(search_slice[best_idx])
        baseline = float(np.mean(search_slice))

        prominence = max(0.0, peak_val - baseline) / (acorr[0] + 1e-6)
        if prominence < 0.08:
            return None, 0.0

        bpm = (60.0 * fps) / float(peak_lag)
        tempo_conf = min(1.0, max(0.0, prominence * 2.5))
        return bpm, tempo_conf

    @classmethod
    def _detect_speech_features(
        cls, magnitudes: np.ndarray, freqs: np.ndarray, sample_rate: int
    ) -> tuple[bool, float, float]:
        """Check for speech syllabic modulation (2.0 to 7.0 Hz envelope fluctuations).

        Returns:
            (is_speech, confidence, modulation_index)
        """
        if len(magnitudes) < 8:
            return False, 0.0, 0.0

        speech_band = (freqs >= 300.0) & (freqs <= 3400.0)
        if not np.any(speech_band):
            return False, 0.0, 0.0

        band_energies = np.sum(magnitudes[:, speech_band] ** 2, axis=1)
        mean_energy = float(np.mean(band_energies))
        if mean_energy < 1e-9:
            return False, 0.0, 0.0

        mod_index = float(np.std(band_energies) / mean_energy)
        is_speech = mod_index >= 0.45
        conf = min(1.0, max(0.0, (mod_index - 0.25) / 0.75))
        return is_speech, conf, mod_index

    @classmethod
    def _estimate_emotion(
        cls,
        *,
        mode: str | None,
        key_corr: float,
        bpm: float | None,
        rms_dbfs: float,
        centroid_hz: float,
    ) -> tuple[float, float, str]:
        """Map musical characteristics onto Russell Circumplex (valence, arousal, mood)."""
        valence_bias = 0.0
        if mode == "major":
            valence_bias = 0.45 * key_corr
        elif mode == "minor":
            valence_bias = -0.45 * key_corr

        timbre_shift = max(-0.2, min(0.2, (centroid_hz - 1500.0) / 4000.0))
        valence = float(np.clip(valence_bias + timbre_shift, -1.0, 1.0))

        loudness_norm = float(np.clip((rms_dbfs - (-55.0)) / 45.0, 0.0, 1.0))

        if bpm is not None:
            tempo_norm = float(np.clip((bpm - 60.0) / 100.0, 0.0, 1.0))
        else:
            tempo_norm = 0.5

        bright_norm = float(np.clip((centroid_hz - 500.0) / 3500.0, 0.0, 1.0))
        arousal = float(np.clip(0.45 * loudness_norm + 0.35 * tempo_norm + 0.20 * bright_norm, 0.0, 1.0))

        if arousal >= 0.55:
            if valence >= 0.15:
                mood = "energetic"
            elif valence < -0.15:
                mood = "dramatic"
            else:
                mood = "tense"
        else:
            if valence >= 0.15:
                mood = "calm"
            elif valence < -0.15:
                mood = "melancholic"
            else:
                mood = "reflective"

        return valence, arousal, mood

    def analyze_pcm16(
        self,
        pcm16: bytes,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        clip_id: str = "",
    ) -> MusicPerceptionResult:
        """Analyze PCM16 audio bytes purely on CPU with strict negative control guarantees."""
        samples = self._to_mono_float(pcm16, channels)
        duration = float(len(samples)) / float(max(1, sample_rate))
        rms_dbfs = self._compute_rms_dbfs(samples)

        # 1. Negative control: Silence
        if rms_dbfs < self.silence_threshold_dbfs or duration < self.min_duration_seconds:
            return MusicPerceptionResult(
                clip_id=clip_id,
                is_music=False,
                kind="unknown",
                confidence=0.0,
                mood="",
                description="No reliable audio event detected.",
                duration_seconds=duration,
                rms_dbfs=rms_dbfs,
            )

        # Compute STFT
        magnitudes, freqs, _ = self._compute_stft_frames(samples, sample_rate)
        flatness, centroid_hz, harmonicity = self._compute_spectral_stats(magnitudes, freqs)

        # 2. Negative control: Noise (high spectral flatness, low harmonicity)
        if flatness > self.noise_flatness_threshold and harmonicity < 0.18:
            return MusicPerceptionResult(
                clip_id=clip_id,
                is_music=False,
                kind="sound",
                confidence=0.0,
                mood="",
                description="Audio event not identified.",
                duration_seconds=duration,
                rms_dbfs=rms_dbfs,
                spectral_flatness=flatness,
                spectral_centroid_hz=centroid_hz,
                harmonicity=harmonicity,
            )

        # Compute musical & vocal features
        key, mode, key_corr, _, top3_conc = self._detect_chroma_and_key(magnitudes, freqs)
        bpm, tempo_conf = self._estimate_tempo(magnitudes, sample_rate)
        is_speech, speech_conf, mod_index = self._detect_speech_features(magnitudes, freqs, sample_rate)

        # Diatonic chord concentration criterion:
        # Music requires discrete pitch classes (top 3 bins >= concentration threshold)
        has_chromatic_chords = top3_conc >= self.min_chroma_concentration and key_corr >= self.min_music_key_corr
        music_conf = 0.0
        if has_chromatic_chords and flatness < 0.50:
            music_conf = float(np.clip(key_corr * 0.7 + harmonicity * 0.3, 0.0, 1.0))

        has_music_traits = music_conf >= 0.40
        has_speech_traits = is_speech and speech_conf >= 0.40

        # Overlap detector: BOTH independent speech modulation AND independent musical chord structure
        speech_overlap = bool(has_music_traits and (has_speech_traits or mod_index >= 0.12))

        # 3. Negative control: Speech-only (vocal envelope without sustained chords/key)
        if has_speech_traits and not has_music_traits:
            return MusicPerceptionResult(
                clip_id=clip_id,
                is_music=False,
                kind="speech",
                confidence=speech_conf,
                mood="",
                tags=("speech",),
                description="Speech detected; background music is not independently confirmed.",
                duration_seconds=duration,
                rms_dbfs=rms_dbfs,
                spectral_flatness=flatness,
                spectral_centroid_hz=centroid_hz,
                harmonicity=harmonicity,
                speech_overlap=False,
            )

        # 4. Confirmed Music (standalone or concurrent with speech)
        if has_music_traits:
            valence, arousal, mood = self._estimate_emotion(
                mode=mode,
                key_corr=key_corr,
                bpm=bpm,
                rms_dbfs=rms_dbfs,
                centroid_hz=centroid_hz,
            )

            tags_list = ["music"]
            if key:
                tags_list.append(key.lower())
            if mood:
                tags_list.append(mood)
            if speech_overlap:
                tags_list.append("mixed-speech")

            desc_parts = [f"Music in {key}" if key else "Musical composition"]
            if bpm is not None:
                desc_parts.append(f"at approx {round(bpm)} BPM")
            if mood:
                desc_parts.append(f"with {mood} mood")
            if speech_overlap:
                desc_parts.append("(concurrent speech detected)")

            hypotheses: list[dict[str, Any]] = []
            if key:
                hypotheses.append({
                    "category": "musical_key",
                    "candidates": [{"label": key, "similarity": round(key_corr, 3)}],
                })
            if mood:
                hypotheses.append({
                    "category": "musical_mood",
                    "candidates": [{"label": mood, "similarity": round(music_conf, 3)}],
                })

            return MusicPerceptionResult(
                clip_id=clip_id,
                is_music=True,
                kind="music",
                confidence=music_conf,
                bpm=bpm,
                tempo_confidence=tempo_conf,
                key=key,
                key_confidence=key_corr,
                mode=mode,
                valence=valence,
                arousal=arousal,
                mood=mood,
                tags=tuple(tags_list),
                description=" ".join(desc_parts) + ".",
                duration_seconds=duration,
                rms_dbfs=rms_dbfs,
                spectral_flatness=flatness,
                spectral_centroid_hz=centroid_hz,
                harmonicity=harmonicity,
                speech_overlap=speech_overlap,
                candidate_hypotheses=tuple(hypotheses),
            )

        # 5. Fallback non-music sound
        return MusicPerceptionResult(
            clip_id=clip_id,
            is_music=False,
            kind="sound",
            confidence=0.0,
            mood="",
            description="Audio event not identified.",
            duration_seconds=duration,
            rms_dbfs=rms_dbfs,
            spectral_flatness=flatness,
            spectral_centroid_hz=centroid_hz,
            harmonicity=harmonicity,
            speech_overlap=False,
        )

    def describe(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        channels: int,
        clip_id: str,
    ) -> dict[str, Any]:
        """Adapter implementing AudioDescriptionProvider protocol."""
        res = self.analyze_pcm16(pcm16, sample_rate=sample_rate, channels=channels, clip_id=clip_id)
        return {
            "schema_version": res.schema_version,
            "clip_id": res.clip_id,
            "kind": res.kind,
            "description": res.description,
            "tags": list(res.tags),
            "mood": res.mood,
            "confidence": res.confidence,
            "duration_seconds": res.duration_seconds,
            "raw_audio_persisted": False,
            "candidate_hypotheses": [dict(h) for h in res.candidate_hypotheses],
        }


class MusicSectionKind(str, enum.Enum):
    """Structural section of a musical composition."""

    INTRO = "intro"
    VERSE = "verse"
    BUILDUP = "buildup"
    DROP = "drop"
    CHORUS = "chorus"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"
    AMBIENT = "ambient"


@dataclass(frozen=True)
class MusicTrajectoryPoint:
    """Instantaneous or windowed observation along musical time."""

    timestamp: float
    rms_dbfs: float
    spectral_centroid_hz: float
    valence: float
    arousal: float
    harmonicity: float
    key: str = "unknown"
    bpm: float = 0.0

    @classmethod
    def from_perception_result(
        cls,
        res: MusicPerceptionResult,
        timestamp: float | None = None,
    ) -> MusicTrajectoryPoint:
        ts = time.time() if timestamp is None else float(timestamp)
        return cls(
            timestamp=ts,
            rms_dbfs=float(res.rms_dbfs),
            spectral_centroid_hz=float(res.spectral_centroid_hz),
            valence=float(res.valence),
            arousal=float(res.arousal),
            harmonicity=float(res.harmonicity),
            key=res.key if res.is_music else "unknown",
            bpm=float(res.bpm) if res.is_music else 0.0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 3),
            "rms_dbfs": round(self.rms_dbfs, 2),
            "spectral_centroid_hz": round(self.spectral_centroid_hz, 1),
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "harmonicity": round(self.harmonicity, 3),
            "key": self.key,
            "bpm": round(self.bpm, 1),
        }


@dataclass(frozen=True)
class MusicDropEvent:
    """Detected electronic/cinematic drop or major dynamic release."""

    timestamp: float
    intensity: float
    buildup_duration_s: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 3),
            "intensity": round(self.intensity, 3),
            "buildup_duration_s": round(self.buildup_duration_s, 2),
            "description": self.description,
        }


@dataclass(frozen=True)
class MusicCritique:
    """Rich companion aesthetic evaluation, genre categorization, and voice remarks."""

    overall_score: float
    estimated_genre: str
    harmonic_depth_score: float
    rhythmic_energy_score: float
    emotional_resonance_score: float
    highlights: tuple[str, ...]
    criticisms: tuple[str, ...]
    conversational_remark: str
    language: str = "ru"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 1),
            "estimated_genre": self.estimated_genre,
            "harmonic_depth_score": round(self.harmonic_depth_score, 1),
            "rhythmic_energy_score": round(self.rhythmic_energy_score, 1),
            "emotional_resonance_score": round(self.emotional_resonance_score, 1),
            "highlights": list(self.highlights),
            "criticisms": list(self.criticisms),
            "conversational_remark": self.conversational_remark,
            "language": self.language,
        }


class DynamicMusicFlowTracker:
    """CPU-only sliding-window tracker for music dynamics, drops, and harmonic progressions."""

    def __init__(
        self,
        *,
        max_history_seconds: float = 120.0,
        max_points: int = 600,
    ) -> None:
        self.max_history_seconds = max(10.0, float(max_history_seconds))
        self.max_points = max(10, int(max_points))
        self._history: deque[MusicTrajectoryPoint] = deque(maxlen=self.max_points)
        self._detected_drops: list[MusicDropEvent] = []

    def record_point(self, point: MusicTrajectoryPoint) -> None:
        """Append a trajectory point and prune points older than max_history_seconds."""
        self._history.append(point)
        self._prune(point.timestamp)

    def record_result(
        self,
        res: MusicPerceptionResult,
        timestamp: float | None = None,
    ) -> MusicTrajectoryPoint:
        """Convert a MusicPerceptionResult into a trajectory point and record it."""
        pt = MusicTrajectoryPoint.from_perception_result(res, timestamp=timestamp)
        self.record_point(pt)
        return pt

    def _prune(self, now: float) -> None:
        cutoff = now - self.max_history_seconds
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    @property
    def points(self) -> list[MusicTrajectoryPoint]:
        return list(self._history)

    def clear(self) -> None:
        self._history.clear()
        self._detected_drops.clear()

    def detect_drops(self, lookback_seconds: float = 15.0) -> list[MusicDropEvent]:
        """Detect buildup-to-drop transitions within the recent sliding window."""
        if len(self._history) < 3:
            return []

        now = self._history[-1].timestamp
        cutoff = now - max(2.0, float(lookback_seconds))
        pts = [p for p in self._history if p.timestamp >= cutoff]
        if len(pts) < 3:
            return []

        found_drops: list[MusicDropEvent] = []
        last_drop_ts = -999.0

        for i in range(1, len(pts)):
            prev = pts[i - 1]
            curr = pts[i]
            ts = curr.timestamp

            if ts - last_drop_ts < 3.0:
                continue

            rms_delta = curr.rms_dbfs - prev.rms_dbfs

            # Buildup lookback: check points prior to curr within 0.5 to 8.0 seconds
            buildup_pts = [p for p in pts if 0.5 <= (ts - p.timestamp) <= 8.0]
            if not buildup_pts:
                continue

            min_prev_rms = min(p.rms_dbfs for p in buildup_pts)
            total_rise = curr.rms_dbfs - min_prev_rms

            bass_surge = (rms_delta >= 2.0) and (curr.spectral_centroid_hz < prev.spectral_centroid_hz * 0.90)
            is_drop = (
                (rms_delta >= 3.5 and curr.arousal >= 0.50)
                or (rms_delta >= 2.0 and total_rise >= 4.0 and curr.arousal >= 0.55)
                or bass_surge
            )

            if is_drop and curr.rms_dbfs > -38.0:
                buildup_duration = max(1.0, ts - buildup_pts[0].timestamp)
                raw_intensity = float(np.clip((rms_delta / 8.0) * 0.5 + curr.arousal * 0.5, 0.2, 1.0))
                desc = (
                    f"Powerful bass/energy drop (+{rms_delta:.1f} dB) after {buildup_duration:.1f}s buildup"
                    if bass_surge
                    else f"Dynamic drop release (+{rms_delta:.1f} dB) with arousal {curr.arousal:.2f}"
                )
                drop_evt = MusicDropEvent(
                    timestamp=ts,
                    intensity=raw_intensity,
                    buildup_duration_s=buildup_duration,
                    description=desc,
                )
                found_drops.append(drop_evt)
                last_drop_ts = ts

        for d in found_drops:
            if not any(abs(d.timestamp - existing.timestamp) < 1.0 for existing in self._detected_drops):
                self._detected_drops.append(d)
        return found_drops

    def current_section(self, lookback_seconds: float = 8.0) -> MusicSectionKind:
        """Infer current compositional section from recent dynamics and trajectory."""
        if not self._history:
            return MusicSectionKind.AMBIENT

        now = self._history[-1].timestamp
        cutoff = now - max(2.0, float(lookback_seconds))
        pts = [p for p in self._history if p.timestamp >= cutoff]
        if not pts:
            pts = list(self._history)[-3:]

        avg_rms = sum(p.rms_dbfs for p in pts) / len(pts)
        if avg_rms < -48.0 or all(p.key == "unknown" and p.bpm <= 0.0 for p in pts):
            return MusicSectionKind.AMBIENT

        recent_drops = self.detect_drops(lookback_seconds=4.0)
        if recent_drops:
            return MusicSectionKind.DROP

        first_ts = self._history[0].timestamp
        if (now - first_ts) <= 6.0 and avg_rms < -28.0:
            return MusicSectionKind.INTRO

        e_trend = self.energy_trend(lookback_seconds=lookback_seconds)
        last_pt = pts[-1]

        if e_trend > 0.03 and last_pt.arousal > 0.4:
            return MusicSectionKind.BUILDUP

        if e_trend < -0.04 and last_pt.rms_dbfs < -32.0:
            return MusicSectionKind.OUTRO

        if e_trend < -0.06 and last_pt.arousal < 0.35:
            return MusicSectionKind.BREAKDOWN

        if last_pt.arousal >= 0.58 and last_pt.rms_dbfs >= -24.0:
            return MusicSectionKind.CHORUS

        return MusicSectionKind.VERSE

    def harmonic_progression(self, lookback_seconds: float = 60.0) -> list[str]:
        """Sequence of consecutive distinct keys/chords detected over time."""
        if not self._history:
            return []

        now = self._history[-1].timestamp
        cutoff = now - max(5.0, float(lookback_seconds))
        pts = [p for p in self._history if p.timestamp >= cutoff]

        progression: list[str] = []
        for p in pts:
            k = p.key.strip()
            if not k or k.lower() == "unknown":
                continue
            if not progression or progression[-1] != k:
                progression.append(k)

        return progression

    def energy_trend(self, lookback_seconds: float = 10.0) -> float:
        """Linear slope of arousal over time (rate of change per second)."""
        if len(self._history) < 2:
            return 0.0

        now = self._history[-1].timestamp
        cutoff = now - max(2.0, float(lookback_seconds))
        pts = [p for p in self._history if p.timestamp >= cutoff]
        if len(pts) < 2:
            return 0.0

        times = np.array([p.timestamp for p in pts], dtype=np.float64)
        arousals = np.array([p.arousal for p in pts], dtype=np.float64)
        t_span = times[-1] - times[0]
        if t_span <= 0.01:
            return 0.0

        times = times - times[0]
        cov = np.cov(times, arousals)
        slope = float(cov[0, 1] / max(1e-6, cov[0, 0]))
        return slope

    def valence_trend(self, lookback_seconds: float = 10.0) -> float:
        """Linear slope of valence over time (rate of emotional shift)."""
        if len(self._history) < 2:
            return 0.0

        now = self._history[-1].timestamp
        cutoff = now - max(2.0, float(lookback_seconds))
        pts = [p for p in self._history if p.timestamp >= cutoff]
        if len(pts) < 2:
            return 0.0

        times = np.array([p.timestamp for p in pts], dtype=np.float64)
        valences = np.array([p.valence for p in pts], dtype=np.float64)
        t_span = times[-1] - times[0]
        if t_span <= 0.01:
            return 0.0

        times = times - times[0]
        cov = np.cov(times, valences)
        slope = float(cov[0, 1] / max(1e-6, cov[0, 0]))
        return slope

    def stats(self) -> dict[str, Any]:
        """Telemetry snapshot of current musical flow."""
        current_sec = self.current_section()
        prog = self.harmonic_progression()
        bpms = [p.bpm for p in self._history if p.bpm > 0.0]
        mean_bpm = round(float(np.mean(bpms)), 1) if bpms else 0.0

        return {
            "point_count": len(self._history),
            "current_section": current_sec.value,
            "harmonic_progression": prog,
            "energy_trend": round(self.energy_trend(), 4),
            "valence_trend": round(self.valence_trend(), 4),
            "mean_bpm": mean_bpm,
            "drops_detected_total": len(self._detected_drops),
        }


class MusicCritiqueEngine:
    """CPU-only companion aesthetic critic: evaluates track composition, harmony, and rhythm."""

    def __init__(self, *, default_language: str = "ru") -> None:
        self.default_language = "ru" if default_language.lower().startswith("ru") else "en"

    def evaluate(
        self,
        *,
        tracker: DynamicMusicFlowTracker | None = None,
        latest_result: MusicPerceptionResult | None = None,
        language: str | None = None,
    ) -> MusicCritique:
        lang = (language or self.default_language).lower()
        is_ru = lang.startswith("ru")

        progression: list[str] = tracker.harmonic_progression() if tracker else []
        drops: list[MusicDropEvent] = tracker.detect_drops(lookback_seconds=30.0) if tracker else []
        current_section = tracker.current_section() if tracker else MusicSectionKind.VERSE

        bpm = latest_result.bpm if latest_result and latest_result.is_music else (
            tracker.points[-1].bpm if (tracker and tracker.points) else 0.0
        )
        mode = latest_result.mode if latest_result and latest_result.is_music else ""
        key = latest_result.key if latest_result and latest_result.is_music else (
            tracker.points[-1].key if (tracker and tracker.points) else "unknown"
        )
        if not mode and key != "unknown":
            mode = "minor" if "minor" in key.lower() else "major"

        arousal = latest_result.arousal if latest_result else (
            tracker.points[-1].arousal if (tracker and tracker.points) else 0.5
        )
        valence = latest_result.valence if latest_result else (
            tracker.points[-1].valence if (tracker and tracker.points) else 0.0
        )
        centroid = latest_result.spectral_centroid_hz if latest_result else (
            tracker.points[-1].spectral_centroid_hz if (tracker and tracker.points) else 1500.0
        )
        harmonicity = latest_result.harmonicity if latest_result else (
            tracker.points[-1].harmonicity if (tracker and tracker.points) else 0.5
        )

        # 1. Genre estimation
        if bpm >= 120 and arousal >= 0.48 and (drops or centroid > 1800):
            genre = "EDM / Electronic"
        elif centroid >= 2300 and arousal >= 0.55 and harmonicity < 0.65:
            genre = "Rock / Metal"
        elif 65 <= bpm <= 110 and mode == "minor" and arousal <= 0.5:
            genre = "Lofi / Downtempo"
        elif harmonicity >= 0.62 and bpm < 125:
            genre = "Classical / Orchestral"
        elif mode == "major" and bpm >= 105 and arousal >= 0.48:
            genre = "Pop / Dance"
        elif bpm < 85 and arousal < 0.4:
            genre = "Ambient / Chillout"
        else:
            genre = "Modern Melodic / Indie"

        # 2. Harmonic depth score (1.0 - 10.0)
        unique_chords = len(set(progression))
        base_h = 5.0
        if unique_chords >= 4:
            base_h += 3.5
        elif unique_chords >= 2:
            base_h += 2.0
        elif unique_chords == 1:
            base_h += 0.5
        if harmonicity > 0.55:
            base_h += 1.0
        harmonic_depth = float(np.clip(base_h, 1.0, 10.0))

        # 3. Rhythmic energy score (1.0 - 10.0)
        base_r = 4.0
        if bpm > 0:
            bpm_contrib = np.clip((bpm - 60.0) / 80.0, 0.0, 1.0) * 3.0
            base_r += bpm_contrib
        base_r += float(arousal) * 3.0
        if drops:
            base_r += 1.0
        rhythmic_energy = float(np.clip(base_r, 1.0, 10.0))

        # 4. Emotional resonance score (1.0 - 10.0)
        base_e = 5.0
        base_e += abs(float(valence)) * 2.5
        if abs(float(arousal) - 0.5) > 0.2:
            base_e += 1.5
        if mode == "minor" and valence < 0:
            base_e += 1.0
        emotional_resonance = float(np.clip(base_e, 1.0, 10.0))

        # 5. Overall score
        overall_score = float(np.clip(
            0.35 * rhythmic_energy + 0.35 * harmonic_depth + 0.30 * emotional_resonance,
            1.0,
            10.0,
        ))

        # 6. Highlights & Criticisms
        highlights: list[str] = []
        criticisms: list[str] = []

        if is_ru:
            if drops:
                highlights.append("Мощный динамический дроп с выверенным нарастанием")
            if rhythmic_energy >= 7.0:
                highlights.append("Отличный ритмический драйв и плотный грув")
            if harmonic_depth >= 7.0:
                highlights.append(f"Выразительная последовательность гармоний ({' -> '.join(progression[:4])})")
            elif mode == "minor":
                highlights.append("Глубокая минорная гармония с тёплым эмоциональным окрасом")
            if emotional_resonance >= 7.0:
                highlights.append("Яркая передача настроения и атмосферный звуковой дизайн")

            if not highlights:
                highlights.append("Сбалансированное фоновое звучание")

            if unique_chords <= 1 and tracker and len(tracker.points) > 10:
                criticisms.append("Ограниченное гармоническое развитие (минимальная смена аккордов)")
            if rhythmic_energy < 4.5 and bpm > 0:
                criticisms.append("Несколько сглаженная ритмическая секция")
            if not criticisms:
                criticisms.append("Стилистически выдержанная структура трека")
        else:
            if drops:
                highlights.append("Powerful dynamic drop with strong tension release")
            if rhythmic_energy >= 7.0:
                highlights.append("Tight rhythmic drive and compelling groove")
            if harmonic_depth >= 7.0:
                highlights.append(f"Expressive harmonic progression ({' -> '.join(progression[:4])})")
            elif mode == "minor":
                highlights.append("Deep minor harmony with warm emotional texture")
            if emotional_resonance >= 7.0:
                highlights.append("Vivid emotional mood with immersive sound design")

            if not highlights:
                highlights.append("Balanced ambient soundscape")

            if unique_chords <= 1 and tracker and len(tracker.points) > 10:
                criticisms.append("Static harmonic movement (single chord vamp)")
            if rhythmic_energy < 4.5 and bpm > 0:
                criticisms.append("Subdued rhythmic definition")
            if not criticisms:
                criticisms.append("Stylistically cohesive structure")

        # 7. Conversational remark
        if is_ru:
            if drops:
                remark = "Ого, какой мощный дроп! Бас прямо пробивает, шикарный разгон получился."
            elif current_section == MusicSectionKind.BUILDUP or (tracker and tracker.energy_trend() > 0.05):
                remark = "О, вот это разгон! Сейчас точно будет кульминация..."
            elif genre == "EDM / Electronic":
                remark = "Какой бешеный ритм! Прямо заряжает энергией, отлично держит грув."
            elif genre == "Lofi / Downtempo" or (mode == "minor" and arousal < 0.45):
                remark = "Очень тёплый и атмосферный звук, ритм такой мягкий — идеальный вайб."
            elif mode == "minor":
                remark = "Такая глубокая и меланхоличная мелодия... Очень красивый переход в миноре."
            elif genre == "Classical / Orchestral":
                remark = "Потрясающая гармония! Звучит как масштабный саундтрек, очень кинематографично."
            else:
                remark = "Интересный трек, звучание цепляет и держит приятную атмосферу."
        else:
            if drops:
                remark = "Whoa, that drop hit hard! The buildup created so much tension."
            elif current_section == MusicSectionKind.BUILDUP or (tracker and tracker.energy_trend() > 0.05):
                remark = "Here comes the buildup! We're definitely heading for a peak..."
            elif genre == "EDM / Electronic":
                remark = "Incredible rhythmic drive! This tempo keeps the energy super high."
            elif genre == "Lofi / Downtempo" or (mode == "minor" and arousal < 0.45):
                remark = "Super warm and atmospheric sound, the soft groove is such a nice vibe."
            elif mode == "minor":
                remark = "Such a deep and melancholic melody... really touching minor progression."
            elif genre == "Classical / Orchestral":
                remark = "Stunning harmonic depth! Feels like a cinematic orchestral score."
            else:
                remark = "Intriguing track, really liking the atmosphere and textures here."

        return MusicCritique(
            overall_score=overall_score,
            estimated_genre=genre,
            harmonic_depth_score=harmonic_depth,
            rhythmic_energy_score=rhythmic_energy,
            emotional_resonance_score=emotional_resonance,
            highlights=tuple(highlights),
            criticisms=tuple(criticisms),
            conversational_remark=remark,
            language="ru" if is_ru else "en",
        )


__all__ = [
    "DynamicMusicFlowTracker",
    "MusicCritique",
    "MusicCritiqueEngine",
    "MusicDropEvent",
    "MusicPerceptionAnalyzer",
    "MusicPerceptionResult",
    "MusicSectionKind",
    "MusicTrajectoryPoint",
]
