"""Unit tests for EventPolicy (conversational initiative & grounded commentary)."""

from __future__ import annotations

import pytest
from jawl_voicecompanion.event_policy import EventPolicy, PolicyDecision
from jawl_voicecompanion.scene_state import NarrativeSpeechEvent, SceneState


def test_user_query_bypasses_cooldown_and_salience():
    """Direct user query must immediately trigger response regardless of cooldown."""
    policy = EventPolicy(commentary_cooldown_sec=10.0)
    # Simulate recent speech
    policy.record_spoken("some_topic", timestamp_sec=100.0)

    state = SceneState(timestamp_ms=101000.0)
    diff = {"has_change": False}

    dec = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=101.0,  # 1s after last spoken
        user_query="Кто сейчас в кадре?",
        evidence_id="query_ev_01",
    )
    assert dec.should_speak is True
    assert dec.decision_type == "interactive_answer"
    assert dec.salience_score == 1.0
    assert "Кто сейчас в кадре?" in dec.prompt_context["user_query"]


def test_user_speaking_suppresses_commentary():
    """Companion must never speak while user is speaking."""
    policy = EventPolicy()
    state = SceneState(timestamp_ms=5000.0)
    diff = {"has_change": True}
    speech = NarrativeSpeechEvent(text="Я не пойду на танцы!", start_ms=4500.0, end_ms=5000.0)

    dec = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=5.0,
        is_user_speaking=True,  # User is talking
        speech_event=speech,
        evidence_id="ev_01",
    )
    assert dec.should_speak is False
    assert dec.decision_type == "suppressed_user_active"


def test_low_salience_movement_suppressed():
    """Spatial movement alone (15% coordinate shift) should not trigger speech."""
    policy = EventPolicy(min_salience_threshold=0.60)
    state = SceneState(timestamp_ms=10000.0)
    diff = {
        "has_change": True,
        "entities_modified": [{"track_id": "person_1", "change": "movement: delta=0.18"}],
    }

    dec = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=10.0,
        evidence_id="ev_move_01",
    )
    assert dec.should_speak is False
    assert dec.decision_type == "suppressed_low_salience"
    assert dec.salience_score <= 0.25


def test_high_salience_dialogue_triggers_commentary():
    """High narrative salience dialogue triggers grounded commentary."""
    policy = EventPolicy(min_salience_threshold=0.60)
    state = SceneState(timestamp_ms=15000.0)
    speech = NarrativeSpeechEvent(
        text="Своё лучшее платье... А поищешь?",
        visual_identity_id="p_friend_m",
        start_ms=14500.0,
        end_ms=15000.0,
    )
    diff = {"has_change": True, "speech_event": speech.to_dict()}

    dec = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=15.0,
        speech_event=speech,
        evidence_id="ev_speech_15",
    )
    assert dec.should_speak is True
    assert dec.decision_type == "commentary"
    assert dec.salience_score >= 0.80
    assert dec.evidence_id == "ev_speech_15"
    assert dec.character_id == "p_friend_m"


def test_cooldown_and_anti_repetition():
    """Verifies that cooldown prevents chatter and anti-repetition prevents topic looping."""
    policy = EventPolicy(commentary_cooldown_sec=5.0, anti_repetition_window_sec=20.0)
    state = SceneState(timestamp_ms=20000.0)
    speech = NarrativeSpeechEvent(text="Мой отец узнает об этом!", visual_identity_id="p_curly")
    diff = {"has_change": True}

    # First turn: should speak
    dec1 = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=20.0,
        speech_event=speech,
        evidence_id="ev_1",
    )
    assert dec1.should_speak is True
    policy.record_spoken("dialogue_p_curly", timestamp_sec=20.0)

    # Immediate second turn: suppressed by cooldown
    dec2 = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=22.0,  # 2s < 5s cooldown
        speech_event=speech,
        evidence_id="ev_2",
    )
    assert dec2.should_speak is False
    assert dec2.decision_type == "suppressed_cooldown"

    # Turn after cooldown (6s later), but same topic: suppressed by anti-repetition
    dec3 = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=26.0,  # 6s > 5s cooldown, but 6s < 20s anti-repetition
        speech_event=speech,
        evidence_id="ev_3",
    )
    assert dec3.should_speak is False
    assert dec3.decision_type == "suppressed_repetition"


def test_grounded_evidence_requirement():
    """Suppresses speech if no grounded evidence_id is provided."""
    policy = EventPolicy(require_grounded_evidence=True)
    state = SceneState(timestamp_ms=30000.0)
    diff = {"has_change": True}

    dec = policy.arbitrate(
        scene_state=state,
        semantic_diff=diff,
        timestamp_sec=30.0,
        evidence_id="",  # No evidence
    )
    assert dec.should_speak is False
    assert dec.decision_type == "suppressed_ungrounded"
