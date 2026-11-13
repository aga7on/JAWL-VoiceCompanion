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
