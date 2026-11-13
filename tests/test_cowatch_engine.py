"""Unit and behavioral tests for CoWatchEngine.

Tests verify:
1. Scene cut boundary purging: transient bounding boxes & frame facts are cleared
   so no stale claims survive across cuts. Chronological cut history preserved.
2. Decoupled 3 identities: spatial_track_id, visual_identity_id, audio_speaker_id.
   Offscreen voiceover dialogue does not falsely bind to on-screen characters.
3. Attention gating & anti-spam: DND, quiet hours, user speaking, and cooldowns
   strictly suppress spoken commentary bids. Routine static scenes output silence.
4. Barge-in stop latency: interruption halts in-flight speech within <= 300 ms invariant.
5. Gameplay co-op integration: GameObservation ingestion, tactical alert detection,
   and epistemic state preservation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from jawl_voicecompanion.cowatch_engine import (
    CharacterBinding,
    CoWatchCommentaryBid,
    CoWatchEngine,
    CoWatchObservation,
    SceneCutEvent,
)
from jawl_voicecompanion.game_embodied import GameEmbodiedLayer, GameObservation
from jawl_voicecompanion.scene_state import EpistemicObservationState


def test_scene_transition_purges_transient_tracks_and_records_cut() -> None:
    engine = CoWatchEngine(scene_id="shot_01", scene_type="anime")
    assert engine.scene_id == "shot_01"
    assert engine.scene_version == 1

    # Ingest a visual track in shot_01
    engine.ingest_visual_entity(
        track_id="trk_person_1",
        visual_identity_id="character_asuka",
        bbox=[0.1, 0.2, 0.3, 0.4],
        label="character",
        confidence=0.95,
        timestamp=100.0,
    )
    assert len(engine.active_tracks) == 1
    assert "trk_person_1" in engine.active_tracks
    assert len(engine.frame_observations) == 1

    # Cut to shot_02
    cut = engine.transition_scene(
        new_scene_id="shot_02",
        scene_type="anime",
        summary="Camera angle switches to wide stadium shot",
        timestamp=105.0,
    )

    assert isinstance(cut, SceneCutEvent)
    assert cut.from_scene_id == "shot_01"
    assert cut.to_scene_id == "shot_02"
    assert engine.scene_id == "shot_02"
    assert engine.scene_version == 2

    # Zero stale claims: transient tracks and frame inspections must be purged!
    assert len(engine.active_tracks) == 0
    assert len(engine.frame_observations) == 0

    # Chronological history must retain the cut
    assert len(engine.scene_history) == 1
    assert engine.scene_history[0].to_scene_id == "shot_02"

    # Character binding spatial track detached after cut
    asuka_binding = engine.character_bindings["character_asuka"]
    assert asuka_binding.spatial_track_id is None
    assert asuka_binding.binding_status == "hypothesis"


def test_decoupled_identities_and_offscreen_speech() -> None:
    engine = CoWatchEngine(scene_id="scene_classroom")

    # Ingest visual character in active track
    engine.ingest_visual_entity(
        track_id="trk_front_desk",
        visual_identity_id="student_shinji",
        confidence=0.92,
        timestamp=10.0,
    )

    # 1. On-screen speech with matching track & visual ID -> confirmed
    sp_event_1 = engine.ingest_speech_event(
        audio_speaker_id="spk_shinji",
        text="Я не хочу пилотировать робота.",
        spatial_track_id="trk_front_desk",
        visual_identity_id="student_shinji",
        confidence=0.95,
        timestamp=11.0,
    )
    assert sp_event_1.binding_status == "confirmed"
    assert not sp_event_1.is_offscreen
    assert sp_event_1.spatial_track_id == "trk_front_desk"

    # 2. Off-screen voiceover (no spatial track) -> hypothesis & offscreen
    sp_event_2 = engine.ingest_speech_event(
        audio_speaker_id="spk_narrator",
        text="В этот момент за окном раздался гул сирен.",
        spatial_track_id=None,
        is_offscreen=True,
        confidence=0.88,
        timestamp=13.0,
    )
    assert sp_event_2.binding_status == "hypothesis"
    assert sp_event_2.is_offscreen
    assert sp_event_2.spatial_track_id is None

    # Verify binding record in engine
    narrator_binding = engine.character_bindings["spk_narrator"]
    assert narrator_binding.is_offscreen
    assert narrator_binding.binding_status == "hypothesis"


def test_attention_gating_dnd_suppression() -> None:
    engine = CoWatchEngine(scene_id="sc_1", dnd=True)

    bid = engine.evaluate_commentary_bid("Неожиданный поворот сюжета", now=10.0)
    assert bid.action == "suppress"
    assert bid.reason == "dnd_active"


def test_attention_gating_quiet_hours_suppression() -> None:
    # Quiet hours set to 23:00 - 07:00
    clock = lambda: datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc)
    engine = CoWatchEngine(scene_id="sc_1", quiet_hours="23:00-07:00", clock=clock)

    assert engine.is_quiet()
    bid = engine.evaluate_commentary_bid("Важный диалог персонажей", now=10.0)
    assert bid.action == "suppress"
    assert bid.reason == "quiet_hours_active"


def test_attention_gating_user_speaking_suppression() -> None:
    engine = CoWatchEngine(scene_id="sc_1")

    # User is currently talking
    bid = engine.evaluate_commentary_bid("Взрыв здания", now=10.0, user_speaking=True)
    assert bid.action == "suppress"
    assert bid.reason == "user_speaking_active"


def test_attention_gating_cooldown() -> None:
    engine = CoWatchEngine(scene_id="sc_1", cooldown_s=45.0)

    # First salient event passes
    bid1 = engine.evaluate_commentary_bid("Герой находит артефакт", now=10.0)
    assert bid1.action == "propose"
    assert bid1.reason == "salient_event"

    # Second salient event 20 seconds later must be suppressed by cooldown
    bid2 = engine.evaluate_commentary_bid("Враг появляется из тени", now=30.0)
    assert bid2.action == "suppress"
    assert bid2.reason == "cooldown_active"

    # After cooldown expires (50s > 45s), next event is allowed
    bid3 = engine.evaluate_commentary_bid("Началась битва", now=60.0)
    assert bid3.action == "propose"
    assert bid3.reason == "salient_event"


def test_anti_spam_routine_silence() -> None:
    engine = CoWatchEngine(scene_id="sc_1")

    # Static / routine frames must return action="silence" and text="тишина"
    for routine_desc in ["статичный кадр коридора", "фоновый шум улицы", "пауза в диалоге", "routine idle"]:
        bid = engine.evaluate_commentary_bid(routine_desc, now=100.0)
        assert bid.action == "silence"
        assert bid.suggested_text == "тишина"
        assert bid.reason == "routine_scene_silence"


def test_barge_in_stop_latency_invariant() -> None:
    engine = CoWatchEngine(scene_id="sc_movie")

    # Trigger proposal (sets in_flight_speech=True)
    bid = engine.evaluate_commentary_bid("Босс вошел в комнату", now=10.0)
    assert bid.action == "propose"
    assert engine.get_scene_context()["in_flight_speech"] is True

    # User barges in 150 ms later
    interruption_ts = 10.500
    stop_result = engine.handle_barge_in(interruption_ts=interruption_ts, now=10.620)

    assert stop_result["status"] == "stopped"
    assert stop_result["reason"] == "user_barge_in"
    assert stop_result["barge_in_stop_latency_ms"] == pytest.approx(120.0, abs=1.0)
    assert stop_result["compliant_under_300ms"] is True
    assert engine.get_scene_context()["in_flight_speech"] is False


def test_gameplay_observation_ingestion_and_tactical_alert() -> None:
    game_layer = GameEmbodiedLayer()
    engine = CoWatchEngine(scene_id="boss_arena", scene_type="gameplay", game_layer=game_layer)

    # Ingest critical low health observation
    obs = GameObservation(
        game="Elden Ring",
        scene="boss_arena",
        health=0.15,
        enemies=6,
        objective="Survive Malenia Phase 2",
    )
    result = engine.ingest_gameplay_observation(obs, now=50.0)

    assert result["tactical_alert"] == "critical_low_health"
    assert result["observation"]["modality"] == "gameplay"
    assert "critical_low_health" in result["observation"]["metadata"]["tactical_alert"]

    # Scene context includes the gameplay event
    ctx = engine.get_scene_context()
    assert ctx["scene_type"] == "gameplay"
    assert len(ctx["recent_events"]) >= 1


def test_observation_ttl_expiration() -> None:
    obs = CoWatchObservation(
        modality="visual",
        event_type="visual_detection",
        description="Временный объект",
        timestamp=100.0,
        ttl_s=5.0,
    )
    assert not obs.is_expired(102.0)
    assert obs.is_expired(106.0)
