"""Tests for offline sleep and episodic memory consolidation (CPU/RAM).

Verifies ADR-048 and JAWL_GOAL.md §1 invariants:
1. Hypothesis vs. fact calibration.
2. Invariant: deleted/tombstoned facts are NEVER resurrected.
3. Invariant: expired observations (valid_until < now) are discarded.
4. Immediate purge of staged proposals and buffered observations upon tombstone.
5. Strict CPU/RAM execution with zero GPU calls.
"""

from __future__ import annotations

import time
import pytest

from jawl_voicecompanion.memory_consolidation import (
    EpisodicObservation,
    MemoryProposal,
    OfflineConsolidator,
    PersonaHypothesis,
    SocialEntityRelation,
    SocialGraphConsolidator,
    UserPersonaHypothesisEngine,
)


def test_proposal_contract_fields() -> None:
    prop = MemoryProposal(
        memory_key="user.preference.music_genre",
        revision=1,
        kind="hypothesis",
        subject="user",
        predicate="music_genre",
        value="synthwave",
        confidence=0.75,
        provenance={"episodes": ["ep1", "ep2"], "observation_count": 2},
    )
    d = prop.to_dict()
    assert d["memory_key"] == "user.preference.music_genre"
    assert d["revision"] == 1
    assert d["kind"] == "hypothesis"
    assert d["subject"] == "user"
    assert d["predicate"] == "music_genre"
    assert d["value"] == "synthwave"
    assert d["source"] == "offline_sleep_consolidation"
    assert d["confidence"] == 0.75
    assert d["provenance"]["observation_count"] == 2
    assert d["retention_tier"] == "standard"
    assert "valid_from" in d


def test_episodic_observation_expiration() -> None:
    t0 = 1000.0
    obs = EpisodicObservation(
        observation_id="obs_1",
        episode_id=1,
        category="music",
        key="user.music.genre",
        subject="user",
        predicate="genre",
        value="lofi",
        confidence=0.7,
        timestamp=t0,
        ttl_seconds=60.0,
    )
    assert not obs.is_expired(t0 + 10.0)
    assert not obs.is_expired(t0 + 59.9)
    assert obs.is_expired(t0 + 60.0)
    assert obs.is_expired(t0 + 100.0)


def test_tombstone_rejection_on_ingest() -> None:
    consolidator = OfflineConsolidator()
    consolidator.record_tombstone("user.preference.food")

    # Trying to record an observation with a tombstoned key must return False
    obs = EpisodicObservation(
        observation_id="obs_food",
        episode_id="ep1",
        category="preference",
        key="user.preference.food",
        subject="user",
        predicate="food",
        value="pizza",
    )
    success = consolidator.record_observation(obs)
    assert success is False
    assert consolidator.stats()["suppressed_tombstoned"] == 1
    assert consolidator.stats()["active_observations"] == 0


def test_wildcard_and_prefix_tombstone() -> None:
    consolidator = OfflineConsolidator()
    consolidator.record_tombstone("user.secret.*")
    consolidator.record_tombstone("user.private")

    assert consolidator.is_tombstoned("user.secret.apiKey")
    assert consolidator.is_tombstoned("user.secret.nested.token")
    assert consolidator.is_tombstoned("user.private.notes")
    assert not consolidator.is_tombstoned("user.public.profile")


def test_immediate_purge_on_tombstone() -> None:
    t0 = 1000.0
    consolidator = OfflineConsolidator(clock=lambda: t0)

    # Ingest observations
    obs1 = EpisodicObservation(
        observation_id="obs_1",
        episode_id="ep1",
        category="music",
        key="user.music.artist",
        subject="user",
        predicate="artist",
        value="HOME",
        timestamp=t0,
    )
    obs2 = EpisodicObservation(
        observation_id="obs_2",
        episode_id="ep1",
        category="game",
        key="user.game.favorite",
        subject="user",
        predicate="favorite",
        value="Elden Ring",
        timestamp=t0,
    )
    assert consolidator.record_observation(obs1)
    assert consolidator.record_observation(obs2)
    assert consolidator.stats()["active_observations"] == 2

    # Consolidate so proposals are staged
    props = consolidator.run_consolidation(now=t0)
    assert len(props) == 2
    assert len(consolidator.staged_proposals()) == 2

    # Forget music artist
    consolidator.forget("user.music.artist")

    # Both observations and staged proposals must be purged
    assert consolidator.stats()["active_observations"] == 1
    staged = consolidator.staged_proposals()
    assert len(staged) == 1
    assert staged[0].memory_key == "user.game.favorite"


def test_hypothesis_vs_fact_promotion() -> None:
    # Under-threshold cluster -> hypothesis
    t0 = 1000.0
    consolidator = OfflineConsolidator(clock=lambda: t0)

    for i in range(2):
        consolidator.record_observation(
            EpisodicObservation(
                observation_id=f"obs_h_{i}",
                episode_id=f"ep_{i}",
                category="music",
                key="user.music.genre",
                subject="user",
                predicate="genre",
                value="ambient",
                confidence=0.8,
                timestamp=t0,
            )
        )

    props_hypo = consolidator.run_consolidation(now=t0)
    assert len(props_hypo) == 1
    assert props_hypo[0].kind == "hypothesis"
    assert props_hypo[0].retention_tier == "standard"
    assert props_hypo[0].confidence < 0.85

    # Fact threshold: high confidence (>= 0.85), >= 3 observations, >= 3 distinct episodes
    consolidator_fact = OfflineConsolidator(clock=lambda: t0)
    for i in range(4):
        consolidator_fact.record_observation(
            EpisodicObservation(
                observation_id=f"obs_f_{i}",
                episode_id=f"ep_{i}",
                category="project",
                key="user.project.focus",
                subject="user",
                predicate="focus",
                value="JAWL",
                confidence=0.98,
                timestamp=t0,
            )
        )

    props_fact = consolidator_fact.run_consolidation(now=t0)
    assert len(props_fact) == 1
    assert props_fact[0].kind == "fact"
    assert props_fact[0].retention_tier == "core"
    assert props_fact[0].confidence >= 0.85
    assert len(props_fact[0].provenance["episodes"]) >= 3


def test_logical_forgetting_no_resurrection() -> None:
    """Deleted/tombstoned item MUST NEVER be resurrected by offline consolidation."""
    t0 = 1000.0
    consolidator = OfflineConsolidator(clock=lambda: t0)

    # Simulate observation arriving before tombstone was declared
    obs = EpisodicObservation(
        observation_id="obs_bad",
        episode_id="ep1",
        category="habit",
        key="user.habit.wake_time",
        subject="user",
        predicate="wake_time",
        value="07:00",
        timestamp=t0,
    )
    consolidator.record_observation(obs)

    # User issues memory.forget
    consolidator.forget("user.habit.wake_time")

    # Run consolidation cycle
    props = consolidator.run_consolidation(now=t0 + 10.0)
    assert len(props) == 0
    assert consolidator.stats()["staged_proposals"] == 0

    # Ensure even if another observation tries to sneak in, it's rejected
    obs2 = EpisodicObservation(
        observation_id="obs_bad_2",
        episode_id="ep2",
        category="habit",
        key="user.habit.wake_time",
        subject="user",
        predicate="wake_time",
        value="07:00",
        timestamp=t0 + 20.0,
    )
    assert not consolidator.record_observation(obs2)
    assert consolidator.stats()["suppressed_tombstoned"] >= 1


def test_expired_observations_skipped_in_consolidation() -> None:
    t0 = 1000.0
    consolidator = OfflineConsolidator(clock=lambda: t0)

    obs = EpisodicObservation(
        observation_id="obs_expired",
        episode_id="ep1",
        category="task",
        key="user.task.current",
        subject="user",
        predicate="current",
        value="temporary sprint",
        confidence=0.9,
        timestamp=t0,
        ttl_seconds=30.0,  # expires at t0 + 30
    )
    assert consolidator.record_observation(obs)

    # Consolidate after expiration
    props = consolidator.run_consolidation(now=t0 + 100.0)
    assert len(props) == 0
    assert consolidator.stats()["suppressed_expired"] == 1


def test_tick_and_cooldown_gating() -> None:
    current_time = [1000.0]

    def mock_clock() -> float:
        return current_time[0]

    consolidator = OfflineConsolidator(
        idle_threshold_s=300.0,
        min_cycle_interval_s=600.0,
        clock=mock_clock,
    )

    obs = EpisodicObservation(
        observation_id="obs_tick",
        episode_id="ep1",
        category="music",
        key="user.music.mood",
        subject="user",
        predicate="mood",
        value="energetic",
        timestamp=1000.0,
    )
    consolidator.record_observation(obs)

    # Inactive/active user: idle < 300s -> no consolidation
    res1 = consolidator.tick(timeline_kind="idle", user_idle_seconds=100.0)
    assert len(res1) == 0

    # Sleep timeline kind triggers tick regardless of idle seconds
    res2 = consolidator.tick(timeline_kind="sleep", user_idle_seconds=10.0)
    assert len(res2) == 1
    assert res2[0].predicate == "mood"

    # Cooldown gate: immediately calling tick again produces nothing
    res3 = consolidator.tick(timeline_kind="sleep", user_idle_seconds=500.0)
    assert len(res3) == 0

    # Fast forward past cooldown
    current_time[0] += 650.0
    # Add another observation
    consolidator.record_observation(
        EpisodicObservation(
            observation_id="obs_tick_2",
            episode_id="ep2",
            category="music",
            key="user.music.mood",
            subject="user",
            predicate="mood",
            value="energetic",
            timestamp=current_time[0],
        )
    )
    res4 = consolidator.tick(timeline_kind="idle", user_idle_seconds=400.0)
    assert len(res4) == 1


def test_export_proposals_clears_staging() -> None:
    consolidator = OfflineConsolidator()
    obs = EpisodicObservation(
        observation_id="obs_exp",
        episode_id="ep1",
        category="game",
        key="user.game.role",
        subject="user",
        predicate="role",
        value="support",
    )
    consolidator.record_observation(obs)
    consolidator.run_consolidation()

    assert len(consolidator.staged_proposals()) == 1
    exported = consolidator.export_proposals()
    assert len(exported) == 1
    assert exported[0]["predicate"] == "role"
    # Staging queue must now be cleared
    assert len(consolidator.staged_proposals()) == 0


def test_cancel_check_cooperation() -> None:
    consolidator = OfflineConsolidator()
    for i in range(5):
        consolidator.record_observation(
            EpisodicObservation(
                observation_id=f"obs_cancel_{i}",
                episode_id=f"ep_{i}",
                category="task",
                key=f"user.task.item_{i}",
                subject="user",
                predicate=f"item_{i}",
                value=f"val_{i}",
            )
        )

    # Cancel check returns True immediately
    props = consolidator.run_consolidation(cancel_check=lambda: True)
    assert len(props) == 0


def test_persona_hypothesis_engine_accumulation_and_falsify() -> None:
    clock_val = [1000.0]
    engine = UserPersonaHypothesisEngine(clock=lambda: clock_val[0])

    obs1 = EpisodicObservation(
        observation_id="p1",
        episode_id="ep1",
        category="preference",
        key="user.preference.tea",
        subject="user",
        predicate="tea",
        value="oolong",
        confidence=0.7,
    )
    engine.synthesize_from_observations([obs1], now=1000.0)
    hyp = engine.get_hypothesis("user.preference.tea")
    assert hyp is not None
    assert hyp.value == "oolong"
    assert hyp.confidence == 0.7
    assert not hyp.is_falsified

    # Add second consistent observation
    obs2 = EpisodicObservation(
        observation_id="p2",
        episode_id="ep2",
        category="preference",
        key="user.preference.tea",
        subject="user",
        predicate="tea",
        value="oolong",
        confidence=0.8,
    )
    engine.synthesize_from_observations([obs2], now=1010.0)
    hyp2 = engine.get_hypothesis("user.preference.tea")
    assert hyp2 is not None
    assert hyp2.observation_count == 2
    assert hyp2.confidence > 0.7

    # Falsify hypothesis
    engine.falsify("user.preference.tea", reason="user said they stopped drinking tea")
    hyp_falsified = engine.get_hypothesis("user.preference.tea")
    assert hyp_falsified is not None
    assert hyp_falsified.is_falsified
    assert hyp_falsified.falsified_reason == "user said they stopped drinking tea"


def test_persona_hypothesis_contradiction_resolution() -> None:
    engine = UserPersonaHypothesisEngine()
    # First preference observation
    obs1 = EpisodicObservation(
        observation_id="c1",
        episode_id="ep1",
        category="preference",
        key="user.preference.editor",
        subject="user",
        predicate="editor",
        value="vscode",
        confidence=0.6,
    )
    engine.synthesize_from_observations([obs1], now=1000.0)

    # Contradicting observation with higher confidence replaces/overrules
    obs2 = EpisodicObservation(
        observation_id="c2",
        episode_id="ep2",
        category="preference",
        key="user.preference.editor",
        subject="user",
        predicate="editor",
        value="neovim",
        confidence=0.95,
    )
    engine.synthesize_from_observations([obs2], now=1020.0)
    hyp = engine.get_hypothesis("user.preference.editor")
    assert hyp is not None
    assert hyp.value == "neovim"
    assert hyp.confidence >= 0.8


def test_social_graph_consolidator_relations_and_cascade() -> None:
    sg = SocialGraphConsolidator()
    obs = EpisodicObservation(
        observation_id="s1",
        episode_id="ep1",
        category="social",
        key="social.alice.colleague",
        subject="alice",
        predicate="colleague",
        value={"relation": "colleague", "affinity_delta": 0.2, "trust_delta": 0.1},
    )
    sg.consolidate_observations([obs], current_time=1000.0)
    rel = sg.get_relation("alice", "user")
    assert rel is not None
    assert rel.affinity > 0.0
    assert rel.trust > 0.0

    # Multi-entity relation
    obs_bob = EpisodicObservation(
        observation_id="s2",
        episode_id="ep1",
        category="social",
        key="social.alice.bob",
        subject="alice",
        predicate="knows",
        value={"target": "bob", "relation": "friend", "affinity_delta": 0.3},
    )
    sg.consolidate_observations([obs_bob], current_time=1010.0)
    assert sg.get_relation("alice", "bob") is not None

    # Export graph
    graph_data = sg.export_graph()
    assert "alice" in graph_data["nodes"]
    assert "bob" in graph_data["nodes"]
    assert len(graph_data["edges"]) >= 2

    # Remove entity cascades and drops relations
    sg.remove_entity("alice")
    assert sg.get_relation("alice", "bob") is None
    assert "alice" not in sg.export_graph()["nodes"]


def test_offline_consolidator_persona_social_integration() -> None:
    consolidator = OfflineConsolidator()
    # Add persona observation
    consolidator.record_observation(
        EpisodicObservation(
            observation_id="obs_p",
            episode_id="ep1",
            category="preference",
            key="user.preference.beverage",
            subject="user",
            predicate="beverage",
            value="matcha",
            confidence=0.85,
        )
    )
    # Add social observation
    consolidator.record_observation(
        EpisodicObservation(
            observation_id="obs_s",
            episode_id="ep1",
            category="social",
            key="social.clara.friend",
            subject="clara",
            predicate="friend",
            value={"relation": "friend", "affinity_delta": 0.4},
            confidence=0.9,
        )
    )

    # Run consolidation cycle
    props = consolidator.run_consolidation()
    assert len(props) >= 1

    # Check engines updated
    hyp = consolidator.persona_engine.get_hypothesis("user.preference.beverage")
    assert hyp is not None
    assert hyp.value == "matcha"

    rel = consolidator.social_graph.get_relation("clara", "user")
    assert rel is not None
    assert rel.affinity > 0.0

    stats = consolidator.stats()
    assert stats["active_persona_hypotheses"] >= 1
    assert stats["social_relations_count"] >= 1


def test_offline_consolidator_tombstone_cascades_to_persona_and_social() -> None:
    consolidator = OfflineConsolidator()
    consolidator.record_observation(
        EpisodicObservation(
            observation_id="obs_p",
            episode_id="ep1",
            category="preference",
            key="user.preference.color",
            subject="user",
            predicate="color",
            value="purple",
            confidence=0.8,
        )
    )
    consolidator.record_observation(
        EpisodicObservation(
            observation_id="obs_s",
            episode_id="ep1",
            category="social",
            key="social.dave.user",
            subject="dave",
            predicate="user",
            value={"relation": "acquaintance"},
        )
    )
    consolidator.run_consolidation()

    # Verify hypothesis and social relation exist
    assert consolidator.persona_engine.get_hypothesis("user.preference.color") is not None
    assert not consolidator.persona_engine.get_hypothesis("user.preference.color").is_falsified

    # Record tombstone for persona key
    consolidator.record_tombstone("user.preference.color")
    hyp = consolidator.persona_engine.get_hypothesis("user.preference.color")
    assert hyp is not None
    assert hyp.is_falsified

    # Record tombstone for social entity
    consolidator.record_tombstone("social.dave")
    assert consolidator.social_graph.get_relation("dave", "user") is None
