"""Tests for CPU/RAM music and audio perception analyzer.

Verifies JAWL_GOAL.md §2 and ADR-048 invariants:
1. Negative audio control 1: Silence (< -55 dBFS) -> kind="unknown", is_music=False, confidence=0.0.
2. Negative audio control 2: Pure Gaussian noise (flatness > 0.55) -> kind="sound", is_music=False.
3. Negative audio control 3: Speech-only -> kind="speech", is_music=False, tags includes "speech".
4. Positive control 1: C major chord -> kind="music", is_music=True, key="C major", mode="major", valence > 0.
5. Positive control 2: A minor chord -> kind="music", is_music=True, mode="minor", minor-keyed mood.
6. Positive control 3: Simultaneous speech + music -> is_music=True, speech_overlap=True.
7. Contract compliance: Integration with AudioDescriptionService satisfies validate_audio_description.
8. Low-VRAM budget: Strict CPU/RAM execution with pure NumPy DSP and zero GPU allocations.
"""

from __future__ import annotations

import numpy as np
import pytest

from jawl_voicecompanion.audio_understanding import (
    AudioDescriptionService,
    validate_audio_description,
)
from jawl_voicecompanion.music_perception import (
    MusicPerceptionAnalyzer,
    MusicPerceptionResult,
)


def _generate_sine_wave(freq_hz: float, duration_s: float, sample_rate: int = 16000) -> np.ndarray:
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    return np.sin(2.0 * np.pi * freq_hz * t)


def _generate_speech_signal(duration_s: float = 2.0, sample_rate: int = 16000) -> np.ndarray:
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    pitch_contour = 140.0 + 35.0 * np.sin(2.0 * np.pi * 1.5 * t)
    phase = 2.0 * np.pi * np.cumsum(pitch_contour) / sample_rate
    glottal = np.sin(phase) + 0.6 * np.sin(2.0 * phase) + 0.4 * np.sin(3.0 * phase)
    syllables = np.maximum(0.0, np.sin(2.0 * np.pi * 3.5 * t)) ** 3
    speech_wave = glottal * syllables
    max_val = np.max(np.abs(speech_wave))
    if max_val > 0:
        speech_wave = speech_wave / max_val
    return speech_wave


def _to_pcm16_bytes(audio_float: np.ndarray, peak_amp: float = 16000.0) -> bytes:
    max_amp = np.max(np.abs(audio_float))
    if max_amp > 1e-6:
        normalized = audio_float / max_amp
    else:
        normalized = audio_float
    pcm16 = (normalized * peak_amp).astype(np.int16)
    return pcm16.tobytes()


def test_negative_control_silence() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 2.0
    silence_pcm = bytes(int(sr * duration * 2))  # all zero int16

    result = analyzer.analyze_pcm16(silence_pcm, sample_rate=sr)

    assert isinstance(result, MusicPerceptionResult)
    assert result.kind == "unknown"
    assert result.is_music is False
    assert result.confidence == 0.0
    assert result.mood == ""
    assert result.key is None
    assert result.mode is None
    assert result.speech_overlap is False


def test_negative_control_white_noise() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 2.0
    rng = np.random.default_rng(42)
    noise = rng.normal(0.0, 5000.0, int(sr * duration)).astype(np.int16)
    noise_pcm = noise.tobytes()

    result = analyzer.analyze_pcm16(noise_pcm, sample_rate=sr)

    assert result.kind == "sound"
    assert result.is_music is False
    assert result.confidence == 0.0
    assert result.mood == ""
    assert result.speech_overlap is False


def test_negative_control_speech_only() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    speech_wave = _generate_speech_signal(duration_s=2.0, sample_rate=sr)
    speech_pcm = _to_pcm16_bytes(speech_wave)

    result = analyzer.analyze_pcm16(speech_pcm, sample_rate=sr)

    assert result.kind == "speech"
    assert result.is_music is False
    assert result.confidence > 0.40
    assert "speech" in result.tags
    assert result.speech_overlap is False
    assert result.mood == ""


def test_positive_control_c_major_chord() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # C3 (130.81), C4 (261.63), E4 (329.63), G4 (392.00)
    c_chord = (
        1.0 * np.sin(2.0 * np.pi * 130.81 * t)
        + 0.8 * np.sin(2.0 * np.pi * 261.63 * t)
        + 0.6 * np.sin(2.0 * np.pi * 329.63 * t)
        + 0.7 * np.sin(2.0 * np.pi * 392.00 * t)
    )
    c_pcm = _to_pcm16_bytes(c_chord)

    result = analyzer.analyze_pcm16(c_pcm, sample_rate=sr)

    assert result.kind == "music"
    assert result.is_music is True
    assert result.key == "C major"
    assert result.mode == "major"
    assert result.confidence >= 0.50
    assert result.valence > 0.0
    assert result.speech_overlap is False
    assert result.mood in {"energetic", "cheerful", "calm", "triumphant"}


def test_positive_control_a_minor_chord() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # A2 (110.00), A3 (220.00), C4 (261.63), E4 (329.63)
    a_chord = (
        1.0 * np.sin(2.0 * np.pi * 110.00 * t)
        + 0.8 * np.sin(2.0 * np.pi * 220.00 * t)
        + 0.6 * np.sin(2.0 * np.pi * 261.63 * t)
        + 0.7 * np.sin(2.0 * np.pi * 329.63 * t)
    )
    a_pcm = _to_pcm16_bytes(a_chord)

    result = analyzer.analyze_pcm16(a_pcm, sample_rate=sr)

    assert result.kind == "music"
    assert result.is_music is True
    assert result.mode == "minor"
    assert result.confidence >= 0.50
    assert result.valence < 0.20
    assert result.mood in {"dramatic", "melancholic", "tense", "dark", "sad"}
    assert result.speech_overlap is False


def test_mixed_speech_and_music_overlap() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    c_chord = (
        1.0 * np.sin(2.0 * np.pi * 130.81 * t)
        + 0.8 * np.sin(2.0 * np.pi * 261.63 * t)
        + 0.6 * np.sin(2.0 * np.pi * 329.63 * t)
        + 0.7 * np.sin(2.0 * np.pi * 392.00 * t)
    )
    c_chord_norm = c_chord / np.max(np.abs(c_chord))
    speech_wave = _generate_speech_signal(duration_s=duration, sample_rate=sr)

    mixed = c_chord_norm * 0.60 + speech_wave * 0.50
    mix_pcm = _to_pcm16_bytes(mixed)

    result = analyzer.analyze_pcm16(mix_pcm, sample_rate=sr)

    assert result.is_music is True
    assert result.speech_overlap is True
    assert result.kind == "music"
    assert result.confidence >= 0.40


def test_audio_description_service_schema_contract() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    c_chord = (
        1.0 * np.sin(2.0 * np.pi * 130.81 * t)
        + 0.8 * np.sin(2.0 * np.pi * 261.63 * t)
        + 0.6 * np.sin(2.0 * np.pi * 329.63 * t)
        + 0.7 * np.sin(2.0 * np.pi * 392.00 * t)
    )
    pcm = _to_pcm16_bytes(c_chord)

    service = AudioDescriptionService(analyzer)
    payload = service.describe(pcm, sample_rate=sr, channels=1, clip_id="clip_music_001")

    assert isinstance(payload, dict)
    assert payload["clip_id"] == "clip_music_001"
    assert payload["kind"] == "music"
    assert "C major" in payload["description"]
    assert "energetic" in payload["tags"] or "c major" in payload["tags"]
    assert payload["confidence"] > 0.50

    # Verify against official schema validator
    validated = validate_audio_description(payload, clip_id="clip_music_001", duration_seconds=2.0)
    assert validated["clip_id"] == "clip_music_001"
    assert validated["kind"] == "music"
    assert validated["confidence"] > 0.50


def test_stereo_channel_and_short_buffer_edge_cases() -> None:
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000

    # Sub-chunk or empty bytes: fail closed to unknown without throwing exceptions
    empty_res = analyzer.analyze_pcm16(b"", sample_rate=sr)
    assert empty_res.kind == "unknown"
    assert empty_res.is_music is False
    assert empty_res.confidence == 0.0

    tiny_res = analyzer.analyze_pcm16(bytes(100), sample_rate=sr)
    assert tiny_res.kind == "unknown"
    assert tiny_res.is_music is False
    assert tiny_res.confidence == 0.0

    # Stereo input (2 channels interleaved)
    duration = 1.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    sine = (np.sin(2.0 * np.pi * 440.0 * t) * 16000.0).astype(np.int16)
    stereo_interleaved = np.empty((len(sine) * 2,), dtype=np.int16)
    stereo_interleaved[0::2] = sine
    stereo_interleaved[1::2] = sine
    stereo_bytes = stereo_interleaved.tobytes()

    stereo_res = analyzer.analyze_pcm16(stereo_bytes, sample_rate=sr, channels=2)
    assert stereo_res.kind in {"music", "sound"}
    assert stereo_res.duration_seconds == pytest.approx(1.0, abs=0.05)


def test_zero_gpu_allocation_invariant() -> None:
    import sys

    # Check that MusicPerceptionAnalyzer does not initialize or depend on CUDA / GPU device
    analyzer = MusicPerceptionAnalyzer()
    sr = 16000
    duration = 0.5
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    sine = (np.sin(2.0 * np.pi * 440.0 * t) * 16000.0).astype(np.int16).tobytes()

    # Pre-check GPU allocation if torch is already imported
    torch_mod = sys.modules.get("torch")
    gpu0_before = 0
    gpu1_before = 0
    if torch_mod is not None and hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
        gpu0_before = torch_mod.cuda.memory_allocated(0) if torch_mod.cuda.device_count() > 0 else 0
        gpu1_before = torch_mod.cuda.memory_allocated(1) if torch_mod.cuda.device_count() > 1 else 0

    analyzer.analyze_pcm16(sine, sample_rate=sr)

    if torch_mod is not None and hasattr(torch_mod, "cuda") and torch_mod.cuda.is_available():
        gpu0_after = torch_mod.cuda.memory_allocated(0) if torch_mod.cuda.device_count() > 0 else 0
        gpu1_after = torch_mod.cuda.memory_allocated(1) if torch_mod.cuda.device_count() > 1 else 0
        assert gpu0_after == gpu0_before, f"GPU 0 memory changed: {gpu0_before} -> {gpu0_after}"
        assert gpu1_after == gpu1_before, f"GPU 1 memory changed: {gpu1_before} -> {gpu1_after}"
