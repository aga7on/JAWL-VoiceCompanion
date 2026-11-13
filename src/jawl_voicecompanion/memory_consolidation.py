"""Offline sleep and episodic memory consolidation for the companion (CPU/RAM).

ADR-048 / JAWL_GOAL.md §1:
- Consolidates episodic observations into structured hypotheses during quiet hours,
  sleep, or sustained user inactivity.
- Strictly CPU/RAM only: no GPU/VRAM allocations.
- Logical forgetting invariant: NEVER resurrects deleted (tombstoned / memory.forget)
  or expired (valid_until < now) facts.
- Proposes candidate memories to JAWL in canonical structured format (kind="hypothesis"
  or kind="fact" with provenance); companion never writes directly to durable JAWL state.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Bounded buffer sizes to prevent unbounded memory growth
_MAX_OBSERVATIONS = 2048
_MAX_PROPOSALS = 256
_MAX_TOMBSTONES = 1024
_DEFAULT_IDLE_CONSOLIDATION_S = 1800.0  # 30 minutes of inactivity
_MIN_CYCLE_INTERVAL_S = 3600.0          # At most once per hour automatically
_HIGH_CONFIDENCE_FACT_THRESHOLD = 0.85
_MIN_EPISODES_FOR_FACT = 3


def _utc_iso(ts: float | None = None) -> str:
    """Format timestamp as ISO-8601 UTC string."""
    t = time.time() if ts is None else float(ts)
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class MemoryProposal:
    """Canonical memory proposal adhering to docs/contracts/jawl.md."""

    memory_key: str
    revision: int = 1
    kind: str = "hypothesis"  # "hypothesis" | "fact"
    subject: str = "user"
    predicate: str = ""
    value: Any = None
    source: str = "offline_sleep_consolidation"
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)
    supersedes_id: str | None = None
    valid_from: str = field(default_factory=_utc_iso)
    valid_until: str | None = None
    retention_tier: str = "standard"  # "standard" | "core" | "short"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EpisodicObservation:
    """Single sensory or episodic observation recorded during interaction."""

    observation_id: str
    episode_id: int | str
    category: str  # "music", "game", "habit", "social", "task", "preference"
    key: str
    subject: str
    predicate: str
    value: Any
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: float = 86400.0  # default 24h transient TTL
    valid_until: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.valid_until is None and self.ttl_seconds > 0:
            self.valid_until = self.timestamp + self.ttl_seconds

    def is_expired(self, current_time: float) -> bool:
        """True if observation has passed its validity window."""
        if self.valid_until is not None and current_time >= self.valid_until:
            return True
        return False


@dataclass
class PersonaHypothesis:
    """Hypothesis about user personality, preferences, communication style, or traits."""

    trait_key: str
    inferred_value: Any
    confidence: float = 0.5
    evidence_count: int = 1
    supporting_episodes: list[str] = field(default_factory=list)
    falsified: bool = False
    rationale: str = ""
    updated_at: str = field(default_factory=_utc_iso)

    @property
    def value(self) -> Any:
        return self.inferred_value

    @property
    def is_falsified(self) -> bool:
        return self.falsified

    @property
    def observation_count(self) -> int:
        return self.evidence_count

    @property
    def falsified_reason(self) -> str:
        return self.rationale.removeprefix("Falsified: ")

    def to_memory_proposal(self) -> MemoryProposal:
        """Convert hypothesis into canonical MemoryProposal."""
        is_fact = (
            (not self.falsified)
            and self.confidence >= _HIGH_CONFIDENCE_FACT_THRESHOLD
            and self.evidence_count >= _MIN_EPISODES_FOR_FACT
        )
        kind = "fact" if is_fact else "hypothesis"

        parts = self.trait_key.split(".", 2)
        subject = parts[0] if len(parts) > 0 else "user"
        category = parts[1] if len(parts) > 1 else "persona"
        predicate = parts[2] if len(parts) > 2 else self.trait_key

        return MemoryProposal(
            memory_key=self.trait_key,
            revision=1,
            kind=kind,
            subject=subject,
            predicate=predicate,
            value=self.inferred_value,
            source="offline_persona_consolidation",
            confidence=0.0 if self.falsified else self.confidence,
            provenance={
                "episodes": self.supporting_episodes,
                "evidence_count": self.evidence_count,
                "falsified": self.falsified,
                "rationale": self.rationale,
                "updated_at": self.updated_at,
            },
            valid_from=self.updated_at,
            valid_until=None,
            retention_tier="core" if kind == "fact" else "standard",
        )


class UserPersonaHypothesisEngine:
    """Pure CPU/RAM engine for synthesizing, updating, and falsifying user persona hypotheses."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._hypotheses: dict[str, PersonaHypothesis] = {}
        self._falsified_keys: set[str] = set()

    def record_hypothesis(self, hypothesis: PersonaHypothesis) -> PersonaHypothesis:
        """Ingest or merge a persona hypothesis."""
        with self._lock:
            key = hypothesis.trait_key.strip().lower()
            if key in self._falsified_keys or hypothesis.falsified:
                hypothesis.falsified = True
                hypothesis.confidence = 0.0
                self._falsified_keys.add(key)
                self._hypotheses[key] = hypothesis
                return hypothesis

            existing = self._hypotheses.get(key)
            if existing is None or existing.falsified:
                self._hypotheses[key] = hypothesis
                return hypothesis

            # Merge evidence
            merged_episodes = sorted(list(set(existing.supporting_episodes + hypothesis.supporting_episodes)))
            total_evidence = existing.evidence_count + hypothesis.evidence_count

            # Compare inferred values
            if existing.inferred_value == hypothesis.inferred_value:
                # Value matches: boost confidence asymptotically toward 0.95
                boosted_conf = min(0.95, round(existing.confidence + (1.0 - existing.confidence) * 0.25, 3))
                merged = PersonaHypothesis(
                    trait_key=key,
                    inferred_value=existing.inferred_value,
                    confidence=boosted_conf,
                    evidence_count=total_evidence,
                    supporting_episodes=merged_episodes,
                    falsified=False,
                    rationale=hypothesis.rationale or existing.rationale,
                    updated_at=_utc_iso(self._clock()),
                )
            else:
                # Contradiction: higher confidence evidence dominates or confidence degrades
                if hypothesis.confidence > existing.confidence + 0.15:
                    new_val = hypothesis.inferred_value
                    new_conf = round(max(0.2, hypothesis.confidence * 0.9), 3)
                    rationale = f"Updated preference: contradicted previous '{existing.inferred_value}'"
                else:
                    new_val = existing.inferred_value
                    new_conf = max(0.2, round(existing.confidence * 0.75, 3))
                    rationale = f"Retained dominant value '{existing.inferred_value}' against '{hypothesis.inferred_value}'"

                merged = PersonaHypothesis(
                    trait_key=key,
                    inferred_value=new_val,
                    confidence=new_conf,
                    evidence_count=total_evidence,
                    supporting_episodes=merged_episodes,
                    falsified=False,
                    rationale=rationale,
                    updated_at=_utc_iso(self._clock()),
                )

            self._hypotheses[key] = merged
            return merged

    def falsify(self, trait_key: str, reason: str = "") -> bool:
        """Mark hypotheses matching trait_key (supports exact, wildcard, or prefix) as falsified."""
        pattern = trait_key.strip().lower()
        if not pattern:
            return False

        with self._lock:
            matched = False
            for k, hyp in list(self._hypotheses.items()):
                is_match = False
                if k == pattern:
                    is_match = True
                elif pattern.endswith("*") and k.startswith(pattern[:-1]):
                    is_match = True
                elif k.startswith(pattern + "."):
                    is_match = True

                if is_match:
                    hyp.falsified = True
                    hyp.confidence = 0.0
                    hyp.rationale = reason if reason else "Falsified by user instruction or tombstone"
                    hyp.updated_at = _utc_iso(self._clock())
                    self._falsified_keys.add(k)
                    matched = True

            if pattern.endswith("*") or not matched:
                self._falsified_keys.add(pattern)
            return matched

    def get_hypothesis(self, trait_key: str) -> PersonaHypothesis | None:
        """Look up hypothesis by key."""
        with self._lock:
            return self._hypotheses.get(trait_key.strip().lower())

    def get_hypotheses(self, *, include_falsified: bool = False) -> list[PersonaHypothesis]:
        """Return list of hypotheses."""
        with self._lock:
            if include_falsified:
                return list(self._hypotheses.values())
            return [h for h in self._hypotheses.values() if not h.falsified]

    def synthesize_from_observations(
        self,
        observations: Sequence[EpisodicObservation],
        now: float | None = None,
    ) -> list[PersonaHypothesis]:
        """Synthesize persona hypotheses from raw episodic observations."""
        current_time = self._clock() if now is None else float(now)
        relevant_obs = [
            obs for obs in observations
            if (
                obs.category in ("preference", "habit", "persona", "style", "trait", "routine")
                or obs.subject.lower() in ("user", "player", "companion")
            ) and not obs.is_expired(current_time)
        ]

        clusters: dict[str, list[EpisodicObservation]] = defaultdict(list)
        for obs in relevant_obs:
            clusters[obs.key.lower()].append(obs)

        synthesized: list[PersonaHypothesis] = []
        for key, group in clusters.items():
            if not group:
                continue
            val_counts: dict[Any, int] = defaultdict(int)
            val_confs: dict[Any, float] = defaultdict(float)
            episodes: set[str] = set()

            for o in group:
                vk = str(o.value) if isinstance(o.value, (dict, list)) else o.value
                val_counts[vk] += 1
                val_confs[vk] += max(0.01, min(1.0, o.confidence))
                episodes.add(str(o.episode_id))

            dom_vk = max(val_counts.keys(), key=lambda v: (val_counts[v], val_confs[v]))
            dom_val = next(
                o.value for o in group
                if (str(o.value) if isinstance(o.value, (dict, list)) else o.value) == dom_vk
            )
            count = val_counts[dom_vk]
            avg_conf = val_confs[dom_vk] / count
            consistency = count / len(group)
            if len(group) == 1:
                calibrated_conf = round(avg_conf, 3)
            else:
                sample_boost = min(1.0, 0.8 + 0.1 * min(count, 2))
                calibrated_conf = min(0.95, round(avg_conf * consistency * sample_boost, 3))

            hyp = PersonaHypothesis(
                trait_key=key,
                inferred_value=dom_val,
                confidence=calibrated_conf,
                evidence_count=count,
                supporting_episodes=sorted(list(episodes)),
                falsified=False,
                rationale=f"Synthesized from {count} observation(s) across {len(episodes)} episode(s)",
                updated_at=_utc_iso(current_time),
            )
            recorded = self.record_hypothesis(hyp)
            synthesized.append(recorded)

        return synthesized

    def synthesize_proposals(self) -> list[MemoryProposal]:
        """Convert all active non-falsified hypotheses into canonical MemoryProposals."""
        with self._lock:
            return [h.to_memory_proposal() for h in self._hypotheses.values() if not h.falsified]


@dataclass
class SocialEntityRelation:
    """Interpersonal relation between user, companion, or named third-party entity."""

    source_entity: str
    target_entity: str
    relation_type: str = "peer"
    affinity: float = 0.0          # -1.0 (hostile) to +1.0 (beloved)
    trust_score: float = 0.5       # 0.0 to 1.0
    last_observed_episode: str = ""
    interaction_count: int = 1
    context_notes: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_utc_iso)

    @property
    def edge_key(self) -> str:
        return f"{self.source_entity.lower()}::{self.target_entity.lower()}"

    @property
    def trust(self) -> float:
        return self.trust_score

    @property
    def relation(self) -> str:
        return self.relation_type

    def to_memory_proposal(self) -> MemoryProposal:
        """Convert social relationship to canonical MemoryProposal."""
        is_fact = self.interaction_count >= 3 and self.trust_score >= 0.7
        kind = "fact" if is_fact else "hypothesis"
        mem_key = f"social.{self.source_entity.lower()}.{self.target_entity.lower()}"
        return MemoryProposal(
            memory_key=mem_key,
            revision=1,
            kind=kind,
            subject=self.source_entity,
            predicate=f"relation_to_{self.target_entity.lower()}",
            value={
                "relation_type": self.relation_type,
                "affinity": round(self.affinity, 2),
                "trust_score": round(self.trust_score, 2),
            },
            source="offline_social_consolidation",
            confidence=round(min(0.95, 0.4 + 0.1 * min(self.interaction_count, 5)), 2),
            provenance={
                "source": self.source_entity,
                "target": self.target_entity,
                "interaction_count": self.interaction_count,
                "last_episode": self.last_observed_episode,
                "context_notes": self.context_notes[-5:],
                "updated_at": self.updated_at,
            },
            valid_from=self.updated_at,
            valid_until=None,
            retention_tier="core" if kind == "fact" else "standard",
        )


class SocialGraphConsolidator:
    """Pure CPU/RAM social network & relationship consolidation engine."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._relations: dict[tuple[str, str], SocialEntityRelation] = {}
        self._entities: set[str] = set()

    def record_interaction(
        self,
        source: str,
        target: str,
        *,
        relation_type: str = "peer",
        affinity_delta: float = 0.0,
        trust_delta: float = 0.0,
        episode_id: str | int = "",
        note: str = "",
        now: float | None = None,
    ) -> SocialEntityRelation:
        """Record or update interpersonal social dynamic between two entities."""
        current_time = self._clock() if now is None else float(now)
        src = str(source).strip()
        tgt = str(target).strip()
        pair = (src.lower(), tgt.lower())

        with self._lock:
            self._entities.add(src.lower())
            self._entities.add(tgt.lower())
            existing = self._relations.get(pair)

            if existing is None:
                new_affinity = max(-1.0, min(1.0, affinity_delta))
                new_trust = max(0.0, min(1.0, 0.5 + trust_delta))
                rel = SocialEntityRelation(
                    source_entity=src,
                    target_entity=tgt,
                    relation_type=relation_type,
                    affinity=new_affinity,
                    trust_score=new_trust,
                    last_observed_episode=str(episode_id) if episode_id else "",
                    interaction_count=1,
                    context_notes=[note] if note else [],
                    updated_at=_utc_iso(current_time),
                )
            else:
                new_affinity = max(-1.0, min(1.0, existing.affinity + affinity_delta))
                new_trust = max(0.0, min(1.0, existing.trust_score + trust_delta))
                notes = list(existing.context_notes)
                if note:
                    notes.append(note)
                rel = SocialEntityRelation(
                    source_entity=src,
                    target_entity=tgt,
                    relation_type=relation_type or existing.relation_type,
                    affinity=new_affinity,
                    trust_score=new_trust,
                    last_observed_episode=str(episode_id) if episode_id else existing.last_observed_episode,
                    interaction_count=existing.interaction_count + 1,
                    context_notes=notes[-20:],
                    updated_at=_utc_iso(current_time),
                )

            self._relations[pair] = rel
            return rel

    def consolidate_observations(
        self,
        observations: Sequence[EpisodicObservation],
        current_time: float | None = None,
    ) -> list[SocialEntityRelation]:
        """Extract and consolidate social interactions from episodic observations."""
        now = self._clock() if current_time is None else float(current_time)
        updated: list[SocialEntityRelation] = []

        for obs in observations:
            is_social = (
                obs.category == "social"
                or obs.key.startswith("social.")
                or "target_entity" in obs.metadata
            )
            if not is_social or obs.is_expired(now):
                continue

            source = obs.subject
            target = ""
            rel_type = "peer"
            affinity_delta = 0.0
            trust_delta = 0.0
            note = str(obs.metadata.get("note", ""))

            # 1. Target from metadata
            if "target_entity" in obs.metadata:
                target = str(obs.metadata["target_entity"])
            elif "target" in obs.metadata:
                target = str(obs.metadata["target"])

            # 2. Extract from obs.value dict
            if isinstance(obs.value, dict):
                if not target:
                    target = str(obs.value.get("target", obs.value.get("target_entity", "")))
                rel_type = str(
                    obs.value.get("relation_type", obs.value.get("relation", rel_type))
                )
                affinity_delta = float(
                    obs.value.get("affinity_delta", obs.value.get("affinity", 0.0))
                )
                trust_delta = float(
                    obs.value.get("trust_delta", obs.value.get("trust", 0.0))
                )
            elif isinstance(obs.value, (int, float)):
                affinity_delta = float(obs.value)
            elif isinstance(obs.value, str):
                rel_type = obs.value

            # 3. Target from key if not yet set
            if not target and obs.key.startswith("social."):
                parts = obs.key.split(".")
                if len(parts) >= 3:
                    source = parts[1]
                    candidate = parts[2].lower()
                    if candidate in ("user", "companion"):
                        target = parts[2]
                    elif candidate not in (
                        "peer",
                        "friend",
                        "colleague",
                        "acquaintance",
                        "mentor",
                        "family",
                        "rival",
                        "stranger",
                        "partner",
                        "knows",
                    ):
                        target = parts[2]
                elif len(parts) == 2:
                    source = parts[1]

            # 4. Target from predicate if predicate is user/companion
            if not target:
                if obs.predicate.lower() in ("user", "companion"):
                    target = obs.predicate
                elif obs.predicate.lower() in (
                    "peer",
                    "friend",
                    "colleague",
                    "acquaintance",
                    "mentor",
                    "family",
                    "rival",
                    "stranger",
                    "partner",
                    "knows",
                ):
                    rel_type = obs.predicate
                    target = "user" if source.lower() != "user" else "companion"
                else:
                    target = "user" if source.lower() != "user" else "companion"

            # 5. Fallback source
            if not source:
                source = "user"
            rel = self.record_interaction(
                source=source,
                target=target,
                relation_type=rel_type,
                affinity_delta=affinity_delta,
                trust_delta=trust_delta,
                episode_id=obs.episode_id,
                note=note,
                now=now,
            )
            updated.append(rel)

        return updated

    def get_relation(self, source: str, target: str) -> SocialEntityRelation | None:
        """Lookup relation between two entities."""
        with self._lock:
            return self._relations.get((source.strip().lower(), target.strip().lower()))

    def get_social_network(self, entity: str) -> list[SocialEntityRelation]:
        """Get all relations involving the given entity as source or target."""
        ent = entity.strip().lower()
        with self._lock:
            return [
                rel for (src, tgt), rel in self._relations.items()
                if src == ent or tgt == ent
            ]

    def remove_relation(self, source: str, target: str) -> bool:
        """Remove a relation between two entities."""
        with self._lock:
            pair = (source.strip().lower(), target.strip().lower())
            return self._relations.pop(pair, None) is not None

    def remove_entity(self, entity: str) -> int:
        """Remove an entity and all associated relations (for tombstone/forgetting)."""
        ent = entity.strip().lower()
        removed_count = 0
        with self._lock:
            pairs_to_remove = [pair for pair in self._relations if pair[0] == ent or pair[1] == ent]
            for pair in pairs_to_remove:
                del self._relations[pair]
                removed_count += 1
            self._entities.discard(ent)
        return removed_count

    def export_graph(self) -> dict[str, Any]:
        """Export serialized social graph structure."""
        with self._lock:
            nodes = sorted(list(self._entities))
            return {
                "nodes": nodes,
                "entities": nodes,
                "edges": [asdict(r) for r in self._relations.values()],
            }

    def synthesize_proposals(self) -> list[MemoryProposal]:
        """Convert all active social relations into canonical MemoryProposals."""
        with self._lock:
            return [r.to_memory_proposal() for r in self._relations.values()]

class OfflineConsolidator:
    """CPU/RAM-only consolidation engine for sleep and offline processing."""

    def __init__(
        self,
        *,
        idle_threshold_s: float = _DEFAULT_IDLE_CONSOLIDATION_S,
        min_cycle_interval_s: float = _MIN_CYCLE_INTERVAL_S,
        clock: Callable[[], float] = time.time,
        on_proposal_ready: Callable[[MemoryProposal], None] | None = None,
    ) -> None:
        self._clock = clock
        self._idle_threshold_s = max(60.0, float(idle_threshold_s))
        self._min_cycle_interval_s = max(60.0, float(min_cycle_interval_s))
        self._on_proposal_ready = on_proposal_ready

        self._lock = threading.RLock()
        self._observations: deque[EpisodicObservation] = deque(maxlen=_MAX_OBSERVATIONS)
        self._tombstones: set[str] = set()
        self._staged_proposals: deque[MemoryProposal] = deque(maxlen=_MAX_PROPOSALS)
        self._persona_engine = UserPersonaHypothesisEngine(clock=self._clock)
        self._social_consolidator = SocialGraphConsolidator(clock=self._clock)

        # Telemetry and state
        self._last_run_at: float = 0.0
        self._cycles_count: int = 0
        self._hypotheses_synthesized: int = 0
        self._facts_synthesized: int = 0
        self._suppressed_expired: int = 0
        self._suppressed_tombstoned: int = 0
        self._last_error: str = ""

        # Background worker state
        self._running: bool = False
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def persona_engine(self) -> UserPersonaHypothesisEngine:
        """Access the user persona hypothesis engine."""
        return self._persona_engine

    @property
    def social_graph(self) -> SocialGraphConsolidator:
        """Access the social graph consolidator."""
        return self._social_consolidator

    # ------------------------------------------------------------- Ingestion & Tombstones

    def record_observation(self, obs: EpisodicObservation, now: float | None = None) -> bool:
        """Ingest one observation if not expired and not tombstoned."""
        current_time = self._clock() if now is None else float(now)
        with self._lock:
            if self.is_tombstoned(obs.key):
                self._suppressed_tombstoned += 1
                return False
            if obs.is_expired(current_time):
                self._suppressed_expired += 1
                return False
            self._observations.append(obs)
            return True

    def record_tombstone(self, memory_key: str) -> None:
        """Register a forgotten key. Purges matching observations immediately."""
        key = str(memory_key or "").strip()
        if not key:
            return
        with self._lock:
            if len(self._tombstones) >= _MAX_TOMBSTONES:
                # Discard oldest arbitrary item to keep bounded
                try:
                    self._tombstones.pop()
                except KeyError:
                    pass
            self._tombstones.add(key)

            # Purge existing observations touching this key
            filtered_obs = deque(
                (obs for obs in self._observations if not self._matches_tombstone(obs.key, key)),
                maxlen=_MAX_OBSERVATIONS,
            )
            self._observations = filtered_obs

            # Purge staged proposals touching this key
            filtered_props = deque(
                (prop for prop in self._staged_proposals if not self._matches_tombstone(prop.memory_key, key)),
                maxlen=_MAX_PROPOSALS,
            )
            self._staged_proposals = filtered_props

            # Falsify persona hypothesis matching key
            self._persona_engine.falsify(key, reason="tombstoned")

            # Purge social relation if key touches social namespace
            if key.startswith("social."):
                parts = key.split(".")
                if len(parts) >= 3:
                    self._social_consolidator.remove_relation(parts[1], parts[2])
                elif len(parts) == 2:
                    self._social_consolidator.remove_entity(parts[1])

    def forget(self, memory_key: str) -> None:
        """Alias for record_tombstone adhering to memory.forget."""
        self.record_tombstone(memory_key)

    def is_tombstoned(self, memory_key: str) -> bool:
        """Check if key or its parent namespace is tombstoned."""
        with self._lock:
            return any(self._matches_tombstone(memory_key, t) for t in self._tombstones)

    @staticmethod
    def _matches_tombstone(key: str, tombstone: str) -> bool:
        """Check exact match or namespace prefix match (e.g. user.preference.*)."""
        if key == tombstone:
            return True
        if tombstone.endswith("*") and key.startswith(tombstone[:-1]):
            return True
        if key.startswith(tombstone + "."):
            return True
        return False

    # ------------------------------------------------------------- Consolidation Logic

    def run_consolidation(
        self,
        now: float | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[MemoryProposal]:
        """Perform one offline sleep/idle consolidation cycle strictly on CPU/RAM."""
        current_time = self._clock() if now is None else float(now)
        proposals: list[MemoryProposal] = []

        with self._lock:
            # 1. Filter active observations: drop expired and tombstoned
            valid_obs: list[EpisodicObservation] = []
            for obs in self._observations:
                if cancel_check and cancel_check():
                    logger.debug("Consolidation cancelled by caller.")
                    return []
                if self.is_tombstoned(obs.key):
                    self._suppressed_tombstoned += 1
                    continue
                if obs.is_expired(current_time):
                    self._suppressed_expired += 1
                    continue
                valid_obs.append(obs)

            if not valid_obs:
                self._last_run_at = current_time
                self._cycles_count += 1
                return []

            # 2. Cluster observations by (category, subject, predicate)
            clusters: dict[tuple[str, str, str], list[EpisodicObservation]] = defaultdict(list)
            for obs in valid_obs:
                clusters[(obs.category, obs.subject, obs.predicate)].append(obs)

            # 3. Synthesize hypotheses for each cluster
            for (category, subject, predicate), group in clusters.items():
                if cancel_check and cancel_check():
                    logger.debug("Consolidation cancelled during cluster processing.")
                    return proposals

                candidate = self._synthesize_cluster(category, subject, predicate, group, current_time)
                if candidate is not None:
                    # Invariant check: ensure candidate key is never tombstoned
                    if not self.is_tombstoned(candidate.memory_key):
                        proposals.append(candidate)
                        self._staged_proposals.append(candidate)
                        if candidate.kind == "fact":
                            self._facts_synthesized += 1
                        else:
                            self._hypotheses_synthesized += 1
                        if self._on_proposal_ready:
                            try:
                                self._on_proposal_ready(candidate)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("Error in on_proposal_ready callback: %s", exc)
                    else:
                        self._suppressed_tombstoned += 1

            # In addition to cluster proposals, consolidate into persona engine and social graph
            self._persona_engine.synthesize_from_observations(valid_obs, now=current_time)
            self._social_consolidator.consolidate_observations(valid_obs, current_time=current_time)

            self._last_run_at = current_time
            self._cycles_count += 1

        return proposals

    def _synthesize_cluster(
        self,
        category: str,
        subject: str,
        predicate: str,
        observations: list[EpisodicObservation],
        current_time: float,
    ) -> MemoryProposal | None:
        """Synthesize a structured proposal from a group of observations."""
        if not observations:
            return None

        # Value frequency and confidence aggregation
        value_counts: dict[Any, int] = defaultdict(int)
        value_conf_sum: dict[Any, float] = defaultdict(float)
        episodes_by_value: dict[Any, set[int | str]] = defaultdict(set)

        for obs in observations:
            # Handle unhashable types by converting to string representation if needed
            val_key = obs.value
            if isinstance(val_key, (dict, list)):
                val_key = str(val_key)
            value_counts[val_key] += 1
            value_conf_sum[val_key] += max(0.01, min(1.0, obs.confidence))
            episodes_by_value[val_key].add(obs.episode_id)

        # Select dominant value
        dominant_val_key = max(value_counts.keys(), key=lambda v: (value_counts[v], value_conf_sum[v]))
        count = value_counts[dominant_val_key]
        total_in_cluster = len(observations)
        distinct_episodes = len(episodes_by_value[dominant_val_key])

        # Retrieve original value object from first matching observation
        dominant_value = next(obs.value for obs in observations if (str(obs.value) if isinstance(obs.value, (dict, list)) else obs.value) == dominant_val_key)

        # Calibrated confidence formula:
        # Base confidence from observations scaled by consistency and sample sufficiency.
        # Single observations have sample penalty; 3+ consistent observations retain high base confidence.
        avg_base_conf = value_conf_sum[dominant_val_key] / count
        consistency = count / max(1, total_in_cluster)
        sample_factor = min(1.0, 0.7 + 0.1 * min(count, 3))
        calibrated_conf = min(0.95, round(avg_base_conf * consistency * sample_factor, 3))
        # Kind determination: "fact" requires high confidence, multiple observations, and distinct episodes
        is_fact = (
            calibrated_conf >= _HIGH_CONFIDENCE_FACT_THRESHOLD
            and count >= 3
            and distinct_episodes >= _MIN_EPISODES_FOR_FACT
        )
        kind = "fact" if is_fact else "hypothesis"

        # Construct structured memory key
        mem_key = f"{subject}.{category}.{predicate}".lower().replace(" ", "_")

        provenance = {
            "episodes": sorted(list(str(e) for e in episodes_by_value[dominant_val_key])),
            "observation_count": count,
            "consistency_ratio": round(consistency, 2),
            "synthesized_at": _utc_iso(current_time),
            "reasoning": f"Synthesized from {count} observations across {distinct_episodes} episode(s) (consistency: {consistency:.0%})",
        }

        return MemoryProposal(
            memory_key=mem_key,
            revision=1,
            kind=kind,
            subject=subject,
            predicate=predicate,
            value=dominant_value,
            source="offline_sleep_consolidation",
            confidence=calibrated_conf,
            provenance=provenance,
            valid_from=_utc_iso(current_time),
            valid_until=None,
            retention_tier="core" if kind == "fact" else "standard",
        )

    # ------------------------------------------------------------- Dispatch & Staging

    def staged_proposals(self) -> list[MemoryProposal]:
        """Return shallow copy of currently staged proposals."""
        with self._lock:
            return list(self._staged_proposals)

    def export_proposals(self) -> list[dict[str, Any]]:
        """Export staged proposals as dictionaries and clear staging queue."""
        with self._lock:
            exported = [prop.to_dict() for prop in self._staged_proposals]
            self._staged_proposals.clear()
            return exported

    # ------------------------------------------------------------- Background Loop

    def tick(
        self,
        current_time: float | None = None,
        *,
        user_idle_seconds: float = 0.0,
        timeline_kind: str = "idle",
    ) -> list[MemoryProposal]:
        """Poll-driven tick called from companion scheduler."""
        now = self._clock() if current_time is None else float(current_time)
        with self._lock:
            time_since_last = now - self._last_run_at
            if time_since_last < self._min_cycle_interval_s:
                return []

            # Condition to consolidate: user in sleep mode or idle long enough
            is_sleep = timeline_kind == "sleep"
            is_deep_idle = timeline_kind == "idle" and user_idle_seconds >= self._idle_threshold_s

            if not (is_sleep or is_deep_idle):
                return []

        # Run consolidation if conditions met
        return self.run_consolidation(now)

    def start(self) -> None:
        """Start optional background consolidation daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="jawl-memory-consolidation-cpu",
                daemon=True,
            )
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop background worker thread."""
        with self._lock:
            self._running = False
            self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

    def _worker_loop(self) -> None:
        """Periodic background poll."""
        while not self._stop_event.wait(30.0):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in memory consolidation worker: %s", exc)
                with self._lock:
                    self._last_error = str(exc)[:200]

    # ------------------------------------------------------------- Telemetry & Stats

    def stats(self, now: float | None = None) -> dict[str, Any]:
        """Telemetry snapshot."""
        current_time = self._clock() if now is None else float(now)
        with self._lock:
            return {
                "active_observations": len(self._observations),
                "staged_proposals": len(self._staged_proposals),
                "tombstones_count": len(self._tombstones),
                "cycles_count": self._cycles_count,
                "hypotheses_synthesized": self._hypotheses_synthesized,
                "facts_synthesized": self._facts_synthesized,
                "suppressed_expired": self._suppressed_expired,
                "suppressed_tombstoned": self._suppressed_tombstoned,
                "last_run_at": self._last_run_at or None,
                "last_run_age_s": round(current_time - self._last_run_at, 1) if self._last_run_at else None,
                "last_error": self._last_error,
                "running": self._running,
                "active_persona_hypotheses": len(self._persona_engine.get_hypotheses()),
                "social_relations_count": len(self._social_consolidator.export_graph()["edges"]),
            }


__all__ = [
    "EpisodicObservation",
    "MemoryProposal",
    "OfflineConsolidator",
    "PersonaHypothesis",
    "SocialEntityRelation",
    "SocialGraphConsolidator",
    "UserPersonaHypothesisEngine",
]
