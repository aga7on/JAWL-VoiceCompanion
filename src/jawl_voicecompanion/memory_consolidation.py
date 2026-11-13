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
            }


__all__ = [
    "EpisodicObservation",
    "MemoryProposal",
    "OfflineConsolidator",
]
