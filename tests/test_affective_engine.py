"""Tests for AffectiveEngine, VRM BlendShape mapping, turn-taking, and WindowsSMTCAdapter."""

from __future__ import annotations

import io
import time
from typing import Any
import numpy as np
import pytest

from jawl_voicecompanion.affective_engine import AffectiveEngine, BACKCHANNEL_CUES
from jawl_voicecompanion.windows_smtc import WindowsSMTCAdapter
from jawl_voicecompanion.process_loopback import ProcessLoopbackBridge


def test_affective_engine_init_and_state() -> None:
    engine = AffectiveEngine(silence_threshold_db=-40.0, min_gap_seconds=1.0)
    st = engine.get_state()
    assert st["valence"] == 0.0
    assert st["arousal"] == -0.2
    assert st["silence_duration_sec"] == 0.0
    assert st["is_dialogue_gap"] is False
    assert st["dominant_expression"] == "neutral"
    assert "blend_weights" in st


def test_affective_engine_silence_and_dialogue_gap() -> None:
    engine = AffectiveEngine(silence_threshold_db=-45.0, min_gap_seconds=0.2)
    silence_bytes = np.zeros(1024, dtype=np.int16).tobytes()

    # Step 1: feed first silence chunk
    st1 = engine.process_pcm_chunk(silence_bytes)
    assert st1["dbfs"] <= -90.0

    # Wait 0.25s and feed next silence chunk
    time.sleep(0.25)
    st2 = engine.process_pcm_chunk(silence_bytes)
    assert st2["silence_duration_sec"] >= 0.2
    assert st2["is_dialogue_gap"] is True

    # Step 2: feed loud audio to break the gap
    loud_samples = (np.sin(np.linspace(0, 100, 1024)) * 20000).astype(np.int16)
    st3 = engine.process_pcm_chunk(loud_samples.tobytes())
    assert st3["silence_duration_sec"] == 0.0
    assert st3["is_dialogue_gap"] is False


def test_affective_engine_expression_quadrants() -> None:
    # 1. Happy: +V, +A
    expr_happy, w_happy = AffectiveEngine._compute_expressions(v=0.8, a=0.8)
    assert expr_happy == "happy"
    assert w_happy["happy"] > 0.5

    # 2. Relaxed: +V, -A
    expr_relaxed, w_relaxed = AffectiveEngine._compute_expressions(v=0.7, a=-0.6)
    assert expr_relaxed == "relaxed"
    assert w_relaxed["relaxed"] > 0.4

    # 3. Angry: -V, +A
    expr_angry, w_angry = AffectiveEngine._compute_expressions(v=-0.8, a=0.7)
    assert expr_angry == "angry"
    assert w_angry["angry"] > 0.5

    # 4. Sad: -V, -A
    expr_sad, w_sad = AffectiveEngine._compute_expressions(v=-0.7, a=-0.7)
    assert expr_sad == "sad"
    assert w_sad["sad"] > 0.4

    # 5. Surprised: neutral V, high positive A
    expr_surp, w_surp = AffectiveEngine._compute_expressions(v=0.0, a=0.9)
    assert expr_surp == "surprised"
    assert w_surp["surprised"] > 0.6

    # 6. Neutral: center
    expr_neutral, w_neutral = AffectiveEngine._compute_expressions(v=0.05, a=0.05)
    assert expr_neutral == "neutral"


def test_affective_engine_backchanneling_spike() -> None:
    engine = AffectiveEngine(silence_threshold_db=-50.0, min_gap_seconds=2.0)
    engine.set_valence(-0.5)

    # Establish low-level audio baseline
    baseline_pcm = (np.ones(1024, dtype=np.int16) * 500).tobytes()
    for _ in range(5):
        engine.process_pcm_chunk(baseline_pcm)

    # Trigger sudden explosive spike (Arousal spike while not in gap)
    spike_pcm = (np.sin(np.linspace(0, 100, 1024)) * 30000).astype(np.int16).tobytes()
    st = engine.process_pcm_chunk(spike_pcm)

    assert st["backchannel_ready"] is True
    assert st["backchannel_cue"] in BACKCHANNEL_CUES["angry"] or st["backchannel_cue"] in BACKCHANNEL_CUES["surprised"]

    # Cooldown verification: immediate second chunk should NOT trigger backchannel
    st_next = engine.process_pcm_chunk(spike_pcm)
    assert st_next["backchannel_ready"] is False


def test_windows_smtc_adapter() -> None:
    adapter = WindowsSMTCAdapter(cache_ttl_sec=0.5)
    assert isinstance(adapter.is_available, bool)

    state = adapter.poll(force=True)
    assert isinstance(state, dict)
    assert "available" in state
    assert "has_active_playback" in state
    assert "playback_status" in state
    assert "title" in state
    assert "artist" in state
    assert "album" in state
    assert "app_id" in state
    assert "last_updated" in state

    # Caching check
    state2 = adapter.poll(force=False)
    assert state2["last_updated"] == state["last_updated"]


def test_process_loopback_with_affective_engine(tmp_path: Any) -> None:
    fake_exe = tmp_path / "process-loopback.exe"
    fake_exe.write_bytes(b"dummy")

    engine = AffectiveEngine()

    class FakeProc:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            # Handshake + one frame of loud audio + EOF
            loud = (np.sin(np.linspace(0, 100, 1024)) * 25000).astype(np.int16).tobytes()
            self.stdout = io.BytesIO(ProcessLoopbackBridge.HANDSHAKE + loud)
            self.stderr = io.BytesIO()

        def poll(self) -> Any:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def terminate(self) -> None:
            pass

    bridge = ProcessLoopbackBridge(
        fake_exe,
        spawn=lambda *args, **kwargs: FakeProc(),
        affective_engine=engine,
    )

    assert bridge.affective_engine is engine
    st_init = bridge.state()
    assert "affective" in st_init
    assert st_init["affective"]["dominant_expression"] == "neutral"

    # Start loopback and let reader thread process the chunk
    bridge.start(pid=1234)
    time.sleep(0.15)

    st_after = bridge.state()
    assert st_after["chunks_captured"] >= 1
    assert st_after["affective"] is not None
    assert st_after["affective"]["last_rms"] > 0.1

    bridge.stop()


def test_affective_engine_dsp_spectral_features() -> None:
    # 1. Harmonic 440 Hz sine vs Harsh Noise
    t = np.linspace(0, 2048 / 44100, 2048)
    harmonic_pcm = (np.sin(2 * np.pi * 440 * t) * 20000).astype(np.int16).tobytes()
    noise_pcm = (np.random.uniform(-1, 1, 2048) * 20000).astype(np.int16).tobytes()

    engine_harm = AffectiveEngine()
    engine_harm.set_valence(0.0)
    st_h = engine_harm.process_pcm_chunk(harmonic_pcm)
    assert st_h["centroid_hz"] < 3500.0
    assert st_h["hnr"] > 0.4
    assert st_h["dsp_valence"] > 0.0

    engine_noise = AffectiveEngine()
    engine_noise.set_valence(0.0)
    st_n = engine_noise.process_pcm_chunk(noise_pcm)
    assert st_n["centroid_hz"] > 5000.0
    assert st_n["hnr"] < 0.3
    assert st_n["dsp_valence"] < 0.0


def test_affective_engine_semantic_valence_and_music_taste() -> None:
    engine = AffectiveEngine()
    engine.set_valence(0.0)

    # Positive semantic update
    v_pos = engine.update_semantic_valence("Это просто отлично, мы победили, круто!", weight=0.5)
    assert v_pos > 0.3

    # Negative semantic update
    v_neg = engine.update_semantic_valence("Какой ужас, кошмар и провал...", weight=0.5)
    assert v_neg < v_pos

    # Music taste sampling with mock episodic memory and SMTC adapter
    records_saved = []

    class MockMemory:
        def save_taste_record(self, **kwargs: Any) -> dict[str, Any]:
            records_saved.append(kwargs)
            return {"status": "saved"}

    class MockSMTC:
        def poll(self, force: bool = False) -> dict[str, Any]:
            return {
                "has_active_playback": True,
                "title": "Midnight City",
                "artist": "M83",
                "album": "Hurry Up, We're Dreaming",
            }

    engine.episodic_memory = MockMemory()
    engine.smtc_adapter = MockSMTC()

    # Trigger taste sampling
    sample_res = engine.sample_music_taste(force=True)
    assert sample_res is not None
    assert len(records_saved) == 1
    assert records_saved[0]["track_info"]["title"] == "Midnight City"
    assert len(records_saved[0]["audio_vector"]) == 16
