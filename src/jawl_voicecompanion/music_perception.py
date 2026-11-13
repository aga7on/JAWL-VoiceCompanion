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

from dataclasses import dataclass, field
import math
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
