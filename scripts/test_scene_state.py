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
    print("Step 1 PASS: person_1 created at left screen")

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
    print("Step 2 PASS: person_1 tracked smoothly during movement")

    # -------------------------------------------------------------
    # Step 3: Temporary disappearance / occlusion at t = 1150 ms
    # -------------------------------------------------------------
    f3 = frame.copy()  # No person in frame
    state3 = tracker.update_frame(f3, timestamp_ms=1150.0, detected_boxes=[])

    assert "person_1" in state3.entities
    assert state3.entities["person_1"].state == "occluded"
    print("Step 3 PASS: person_1 marked as occluded, entity not destroyed")

    # -------------------------------------------------------------
    # Step 4: Re-appearance across camera cut at t = 1650 ms (right screen)
    # -------------------------------------------------------------
    f4 = frame.copy()
    # Same person appears on right half of screen
    f4[250:450, 900:1000] = person_patch
    det4 = [{"bbox": [0.347, 0.703, 0.625, 0.781], "label": "девушка", "conf": 0.92}]
    state4 = tracker.update_frame(f4, timestamp_ms=1650.0, detected_boxes=det4)

    # Because IoU with old position is 0.0, but appearance similarity is near 1.0 -> Re-ID confirm!
    assert "person_1" in state4.entities
    p1 = state4.entities["person_1"]
    assert len(p1.aliases) >= 1
    assert p1.bbox[1] > 0.6  # New position retained
    assert any(h.status == "confirmed" for h in state4.hypotheses)
    print("Step 4 PASS: Re-ID hypothesis confirmed across cut; identity person_1 preserved!")

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
    print("Step 5 PASS: Speech event bound to person_1, state = speaking")

    # -------------------------------------------------------------
    # Step 6: Semantic Delta Diff for LLM
    # -------------------------------------------------------------
    diff = state5.compute_semantic_diff(state4)
    assert diff["has_change"] is True
    assert diff["speech_event"] is not None
    assert diff["speech_event"]["speaker_track_id"] == "person_1"
    print("Step 6 PASS: Semantic delta successfully formatted for Language-Out-of-the-Loop")

    # -------------------------------------------------------------
    # Step 7: Targeted Dual-Attention on Static Region
    # -------------------------------------------------------------
    target = tracker.query_attention(
        f5,
        target_bbox=[0.8, 0.8, 0.95, 0.95],
        label="надпись_субтитров",
        timestamp_ms=1850.0,
    )
    assert target.source == "visual_targeted"
    assert "targeted_надпись_субтитров" in target.track_id
    print("Step 7 PASS: Targeted Top-Down Attention executed on static region")

    print("\n>>> ALL SCENESTATE AND TRACKER LIFECYCLE TESTS PASSED! <<<")


if __name__ == "__main__":
    test_character_tracking_lifecycle()
