"""Unit and behavioral tests for SceneState and HypothesisDrivenEntityTracker."""

from __future__ import annotations

import numpy as np
import pytest
from jawl_voicecompanion.scene_state import (
    HypothesisDrivenEntityTracker,
    NarrativeSpeechEvent,
    SceneState,
)


def test_character_tracking_lifecycle():
    tracker = HypothesisDrivenEntityTracker(
        iou_match_threshold=0.3,
        reid_hypothesis_threshold=0.70,
        reid_confirm_threshold=0.85,
    )

    # Base frame
    rng = np.random.RandomState(42)
    frame = rng.randint(50, 100, size=(720, 1280, 3), dtype=np.uint8)

    # Distinct person appearance (e.g. blue jacket, dark hair)
    person_patch = rng.randint(10, 40, size=(200, 100, 3), dtype=np.uint8)
    person_patch[:, :, 2] = 220  # Strong blue tint

    # -------------------------------------------------------------
    # Step 1: Initial detection at t = 1000 ms (person_1 on left)
    # -------------------------------------------------------------
    f1 = frame.copy()
    f1[200:400, 100:200] = person_patch
    det1 = [{"bbox": [0.278, 0.078, 0.556, 0.156], "label": "девушка", "conf": 0.95}]
    state1 = tracker.update_frame(f1, timestamp_ms=1000.0, detected_boxes=det1)

    assert "person_1" in state1.entities
    assert state1.entities["person_1"].state == "idle"

    # -------------------------------------------------------------
    # Step 2: Smooth movement at t = 1050 ms (person_1 moves right)
    # -------------------------------------------------------------
    f2 = frame.copy()
    f2[200:400, 160:260] = person_patch
    det2 = [{"bbox": [0.278, 0.125, 0.556, 0.203], "label": "девушка", "conf": 0.94}]
    state2 = tracker.update_frame(f2, timestamp_ms=1050.0, detected_boxes=det2)

    assert "person_1" in state2.entities
    assert len(state2.entities) == 1
    assert state2.entities["person_1"].bbox[1] > 0.078  # Moved right

    # -------------------------------------------------------------
    # Step 3: Temporary disappearance / occlusion at t = 1150 ms
    # -------------------------------------------------------------
    f3 = frame.copy()  # No person in frame
    state3 = tracker.update_frame(f3, timestamp_ms=1150.0, detected_boxes=[])

    assert "person_1" in state3.entities
    assert state3.entities["person_1"].state == "occluded"

    # -------------------------------------------------------------
    # Step 4: Re-appearance across camera cut at t = 1650 ms (right screen)
    # -------------------------------------------------------------
    f4 = frame.copy()
    f4[250:450, 900:1000] = person_patch
    det4 = [{"bbox": [0.347, 0.703, 0.625, 0.781], "label": "девушка", "conf": 0.92}]
    state4 = tracker.update_frame(f4, timestamp_ms=1650.0, detected_boxes=det4)

    # IoU with old position is 0.0, but appearance similarity is ~1.0 -> Re-ID confirmed!
    assert "person_1" in state4.entities
    p1 = state4.entities["person_1"]
    assert len(p1.aliases) >= 1
    assert p1.bbox[1] > 0.6
    assert any(h.status == "confirmed" for h in state4.hypotheses)

    # -------------------------------------------------------------
    # Step 5: Active Speaker Binding
    # -------------------------------------------------------------
    f5 = frame.copy()
    f5[250:450, 900:1000] = person_patch
    speech = NarrativeSpeechEvent(
        text="Танцуешь с этой кучерявой девчонкой?",
        start_ms=1700.0,
        end_ms=2100.0,
    )
    state5 = tracker.update_frame(f5, timestamp_ms=1800.0, detected_boxes=det4, active_speech=speech)
    assert state5.active_dialogue is not None
    assert state5.active_dialogue.speaker_track_id == "person_1"
    assert state5.entities["person_1"].state == "speaking"

    # -------------------------------------------------------------
    # Step 6: Semantic Delta Diff for LLM
    # -------------------------------------------------------------
    diff = state5.compute_semantic_diff(state4)
    assert diff["has_change"] is True
    assert diff["speech_event"] is not None
    assert diff["speech_event"]["speaker_track_id"] == "person_1"
    assert "Танцуешь" in diff["speech_event"]["text"]
    assert any(m["track_id"] == "person_1" for m in diff["entities_modified"])


def test_offscreen_speech_no_false_binding():
    """Verifies that offscreen speech does not falsely bind to visible listener entities."""
    tracker = HypothesisDrivenEntityTracker()
    rng = np.random.RandomState(42)
    frame = rng.randint(50, 100, size=(720, 1280, 3), dtype=np.uint8)

    # Character A (listener) is visible on screen
    det = [{"bbox": [0.2, 0.2, 0.6, 0.5], "label": "слушатель", "conf": 0.95}]
    state1 = tracker.update_frame(frame, timestamp_ms=1000.0, detected_boxes=det)
    assert "person_1" in state1.entities
    assert state1.entities["person_1"].state == "idle"

    # Character B speaks offscreen (e.g. Turn 15 telephone/intercom)
    speech = NarrativeSpeechEvent(
        text="Здравствуйте, Нина? Я из службы доставки...",
        is_offscreen=True,
        audio_speaker_id="speaker_audio_03",
        visual_identity_id="p_friend_m",
        start_ms=1050.0,
        end_ms=1500.0,
    )
    state2 = tracker.update_frame(frame, timestamp_ms=1100.0, detected_boxes=det, active_speech=speech)

    assert state2.active_dialogue is not None
    assert state2.active_dialogue.is_offscreen is True
    assert state2.active_dialogue.spatial_track_id is None
    assert state2.active_dialogue.speaker_track_id is None
    assert state2.active_dialogue.visual_identity_id == "p_friend_m"
    assert state2.active_dialogue.audio_speaker_id == "speaker_audio_03"
    assert state2.active_dialogue.binding_status == "unbound_offscreen"

    # Visible listener entity MUST remain idle, NOT falsely marked speaking
    assert state2.entities["person_1"].state == "idle"


def test_decoupled_three_identities_and_serialization():
    """Verifies spatial_track_id, visual_identity_id, and audio_speaker_id serialization."""
    speech = NarrativeSpeechEvent(
        spatial_track_id="track_04",
        visual_identity_id="p_curly",
        audio_speaker_id="speaker_audio_02",
        is_offscreen=False,
        binding_status="active_speaker_present",
        text="Привет!",
        start_ms=500.0,
        end_ms=900.0,
    )
    d = speech.to_dict()
    assert d["spatial_track_id"] == "track_04"
    assert d["visual_identity_id"] == "p_curly"
    assert d["audio_speaker_id"] == "speaker_audio_02"
    assert d["is_offscreen"] is False
    assert d["binding_status"] == "active_speaker_present"
    # Backwards compatibility check
    assert d["speaker_track_id"] == "track_04"


def test_multispeaker_ambiguity_abstention():
    """Verifies that multiple simultaneously speaking entities trigger safe abstention."""
    tracker = HypothesisDrivenEntityTracker()
    rng = np.random.RandomState(42)
    frame = rng.randint(50, 100, size=(720, 1280, 3), dtype=np.uint8)

    det1 = [{"bbox": [0.1, 0.1, 0.5, 0.4], "label": "девушка", "conf": 0.95}]
    det2 = [{"bbox": [0.1, 0.6, 0.5, 0.9], "label": "парень", "conf": 0.95}]
    tracker.update_frame(frame, timestamp_ms=1000.0, detected_boxes=det1 + det2)

    det1_speak = [{"bbox": [0.1, 0.1, 0.5, 0.4], "label": "девушка", "conf": 0.95, "state": "speaking"}]
    det2_speak = [{"bbox": [0.1, 0.6, 0.5, 0.9], "label": "парень", "conf": 0.95, "state": "speaking"}]

    speech = NarrativeSpeechEvent(text="Одновременная реплика", start_ms=1100.0, end_ms=1400.0)
    state = tracker.update_frame(frame, timestamp_ms=1150.0, detected_boxes=det1_speak + det2_speak, active_speech=speech)

    assert state.active_dialogue is not None
    assert state.active_dialogue.spatial_track_id is None
    assert state.active_dialogue.binding_status == "ambiguous_multiple_speakers"


def test_unlocalized_presence_recording():
    """Verifies that VLM person detection without accurate BBox enters unlocalized_presences."""
    tracker = HypothesisDrivenEntityTracker()
    rec = tracker.record_unlocalized_presence(
        traits={"appearance": "парень в очках", "action": "читает"},
        confidence=0.88,
        evidence_id="ev_frame_042",
        timestamp_ms=2500.0,
    )
    assert rec["tag"] == "person_present_unlocalized"
    assert rec["evidence_id"] == "ev_frame_042"
    # Does NOT corrupt spatial entities dict
    assert len(tracker.current_state.entities) == 0
    assert len(tracker.current_state.unlocalized_presences) == 1

    # Verify semantic diff catches unlocalized presence
    prev = SceneState(timestamp_ms=2000.0)
    diff = tracker.current_state.compute_semantic_diff(prev)
    assert diff["has_change"] is True
    assert len(diff["unlocalized_presences"]) == 1
    assert diff["unlocalized_presences"][0]["evidence_id"] == "ev_frame_042"


def test_temporal_causality_late_vlm_no_overwrite():
    """Verifies that late VLM results do NOT overwrite real-time coordinates or jump clock."""
    tracker = HypothesisDrivenEntityTracker()
    rng = np.random.RandomState(42)
    frame = rng.randint(50, 100, size=(720, 1280, 3), dtype=np.uint8)

    # At t = 2000ms: character at [0.5, 0.5, 0.9, 0.9]
    tracker.update_frame(
        frame,
        timestamp_ms=2000.0,
        detected_boxes=[{"bbox": [0.5, 0.5, 0.9, 0.9], "label": "персонаж", "conf": 0.95}],
    )
    assert "person_1" in tracker.current_state.entities
    assert tracker.current_state.entities["person_1"].bbox == [0.5, 0.5, 0.9, 0.9]

    # At t = 2500ms, late VLM result arrives for frame t = 1800ms with coarse bbox [0.0, 0.0, 1.0, 1.0]
    res = tracker.apply_async_vlm_evidence(
        vlm_characters=[{
            "appearance": "девушка с кудрявыми волосами",
            "action": "говорит",
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "confidence": 0.9,
        }],
        frame_timestamp_ms=1800.0,
        current_timestamp_ms=2500.0,
        evidence_id="ev_late_1800",
    )
    assert res["is_stale"] is True
    # Real-time entity bbox at t = 2000ms must NOT be replaced with stale [0,0,1,1]
    assert tracker.current_state.entities["person_1"].bbox == [0.5, 0.5, 0.9, 0.9]
    # Stale VLM without overlap records safely as unlocalized presence
    assert len(res["unlocalized_added"]) == 1
    assert res["unlocalized_added"][0]["evidence_id"] == "ev_late_1800"


def test_semantic_veto_hard_vs_incomplete():
    """Verifies distinction between hard contradiction and incomplete observation."""
    # 1. Hard contradiction: gender mismatch
    is_veto, reason = HypothesisDrivenEntityTracker.check_semantic_contradiction(
        {"appearance": "парень в школьной форме", "gender": "male"},
        {"appearance": "девушка в школьной форме", "gender": "female"},
    )
    assert is_veto is True
    assert "gender mismatch" in reason

    # 2. Hard contradiction: courier uniform vs student
    is_veto, reason = HypothesisDrivenEntityTracker.check_semantic_contradiction(
        {"appearance": "парень, курьер в кепке и куртке"},
        {"appearance": "парень, школьная форма"},
    )
    assert is_veto is True
    assert "distinct attire/role" in reason

    # 3. Incomplete observation: glasses on person A, but glasses not mentioned on person B
    is_veto, reason = HypothesisDrivenEntityTracker.check_semantic_contradiction(
        {"appearance": "парень в очках, темные волосы"},
        {"appearance": "парень, темные волосы"},
    )
    assert is_veto is False
    assert "Compatible or incomplete" in reason


def test_epistemic_observation_three_states():
    from jawl_voicecompanion.scene_state import EpistemicObservationState, EntityObservation

    st = SceneState(timestamp_ms=5000.0)

    # 1. Target present in active entity
    st.entities["track_1"] = EntityObservation(
        track_id="track_1",
        label="персонаж",
        aliases=["девушка с блондинкой", "студентка"],
        last_seen_ms=4800.0,
    )
    res_pres = st.evaluate_observation_status("девушка")
    assert res_pres["status"] == EpistemicObservationState.OBSERVED_PRESENT
    assert "track_1" in res_pres["reason"]

    # 2. Target NOT observed: absence of evidence is NOT evidence of absence!
    # Even if entities is not empty, a cup or sofa was never checked
    res_not_obs = st.evaluate_observation_status("чашка на столе")
    assert res_not_obs["status"] == EpistemicObservationState.NOT_OBSERVED
    assert res_not_obs["needs_visual_refresh"] is True

    # 3. Target observed_absent: an active inspection explicitly looked for it with sufficient quality (>=0.70)
    # and reported not detecting it. Absence is bounded to that inspection, not absolute truth.
    active_inspections = [
        {
            "inspected_scope": "курьер у двери",
            "verified_absent": True,
            "inspection_quality": 0.85,
            "captured_at_ms": 4900.0,
        }
    ]
    res_abs = st.evaluate_observation_status("курьер у двери", active_inspections=active_inspections)
    assert res_abs["status"] == EpistemicObservationState.OBSERVED_ABSENT
    assert "not detected" in res_abs["reason"]
    assert res_abs["inspection_quality"] == 0.85

    # 4. Low-quality inspection (<0.70) MUST NOT trigger observed_absent!
    # It must safely degrade to NOT_OBSERVED (absence of evidence != evidence of absence)
    low_qual_inspections = [
        {
            "inspected_scope": "курьер у двери",
            "verified_absent": True,
            "inspection_quality": 0.50,  # Below 0.70 threshold
            "captured_at_ms": 4900.0,
        }
    ]
    res_low = st.evaluate_observation_status("курьер у двери", active_inspections=low_qual_inspections)
    assert res_low["status"] == EpistemicObservationState.NOT_OBSERVED
    assert res_low["needs_visual_refresh"] is True


def test_epistemic_observation_staleness():
    from jawl_voicecompanion.scene_state import EpistemicObservationState, EntityObservation

    st = SceneState(timestamp_ms=10000.0)

    # Observation from 8000ms ago (staleness = 8000ms, max allowed = 4000ms)
    st.entities["track_old"] = EntityObservation(
        track_id="track_old",
        label="собака",
        last_seen_ms=2000.0,
    )

    res = st.evaluate_observation_status("собака", max_staleness_ms=4000.0)
    # Because observation is stale, it safely degrades to NOT_OBSERVED instead of claiming present or absent
    assert res["status"] == EpistemicObservationState.NOT_OBSERVED
    assert res["needs_visual_refresh"] is True


def test_runtime_observations_age_on_monotonic_clock(monkeypatch):
    from jawl_voicecompanion import scene_state as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    state = SceneState()
    state.record_unlocalized_presence(traits={"target": "cat"}, timestamp_ms=70_000)
    assert state.evaluate_observation_status("cat")["status"] == "not_observed"

    state.record_unlocalized_presence(traits={"target": "cat"}, timestamp_ms=99_500)
    assert state.evaluate_observation_status("cat")["freshness_ms"] == 500
    now[0] = 104.0
    assert state.evaluate_observation_status("cat")["status"] == "not_observed"

    state.record_unlocalized_presence(traits={"target": "cat"}, timestamp_ms=104_000)
    assert state.evaluate_observation_status("cat")["status"] == "observed_present"


def test_inspection_expiry_is_relative_to_capture_and_uses_matching_clock(monkeypatch):
    from jawl_voicecompanion import scene_state as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    state = SceneState()
    inspection = state.record_inspection(target="cup", captured_at_ms=99_000)
    assert inspection["expires_at_ms"] == 103_000
    assert state.evaluate_observation_status("cup")["status"] == "observed_absent"
    now[0] = 104.0
    assert state.evaluate_observation_status("cup")["status"] == "not_observed"

    # An epoch timestamp must never be mistaken for a fresh monotonic one.
    state.record_unlocalized_presence(traits={"target": "clock"}, timestamp_ms=1_700_000_000_000)
    assert state.evaluate_observation_status("clock")["status"] == "not_observed"


def test_explicit_zero_timestamp_preserves_synthetic_timeline(monkeypatch):
    from jawl_voicecompanion import scene_state as module

    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    state = SceneState(timestamp_ms=0.0)
    state.record_unlocalized_presence(traits={"target": "cat"}, timestamp_ms=0.0)
    assert state.evaluate_observation_status("cat")["status"] == "observed_present"
    state.timestamp_ms = 4_001
    assert state.evaluate_observation_status("cat")["status"] == "not_observed"


def test_frame_version_vs_scene_version_separation():
    """Frame updates (motion) advance frame_version without discarding active scene inspections."""
    state = SceneState(scene_id="scene-0")
    assert state.scene_version == 0
    assert state.frame_version == 0

    state.record_inspection(target="terminal_window", captured_at_ms=1000.0)
    assert len(state.active_inspections) == 1

    # Local frame update (minor motion / video playback)
    state.advance_frame()
    assert state.frame_version == 1
    assert state.scene_version == 0
    assert len(state.active_inspections) == 1  # Not wiped!

    # True scene transition (window switch / major cut)
    state.transition_scene("scene-1")
    assert state.scene_version == 1
    assert state.frame_version == 2
    assert len(state.active_inspections) == 0  # Safely wiped on scene transition!




