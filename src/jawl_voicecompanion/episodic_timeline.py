"""Episodic timeline: the single shared TimeService for the companion.

ADR-038: machine process-time (timestamps, event log) is projected into one
bounded episodic timeline. Activity boundaries (conversation start/end, focus
change, sustained silence, owner sleep/wake) cut episodes. This module is the
single source of "now / recently / long ago" for Heartbeat, memory, attention
and the avatar — replacing the per-module ad-hoc clocks, TTLs and cooldowns.

Design rules (PRODUCT.md / AGENTS.md): one owner, bounded state, no second
brain. The timeline records episodes; it does not reason about them. Background
consumers (consolidation, triage) read it best-effort and yield to user turns.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

# Hard bounds so the timeline can never grow without limit (bounded state).
_MAX_EPISODES = 2048
_MAX_EVENTS_PER_EPISODE = 256


def _utc_now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@dataclass
class TimelineEvent:
    """One typed observation inside an episode."""

    ts: float
    kind: str  # conversation | focus | sensory | screen | task | presence | system
    source: str
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ts": _iso(self.ts), "kind": self.kind, "source": self.source, "summary": self.summary[:200]}


@dataclass
class Episode:
    """A bounded span of activity between two boundary cuts."""

    episode_id: int
    kind: str  # conversation | ambient | idle | sleep
    started_ts: float
    ended_ts: float | None = None
    events: deque[TimelineEvent] = field(default_factory=lambda: deque(maxlen=_MAX_EVENTS_PER_EPISODE))
    summary: str = ""

    @property
    def open(self) -> bool:
        return self.ended_ts is None

    def close(self, ts: float, summary: str = "") -> None:
        if self.open:
            self.ended_ts = ts
            if summary:
                self.summary = summary[:300]

    def duration_s(self) -> float:
        end = self.ended_ts if self.ended_ts is not None else _utc_now()
        return max(0.0, end - self.started_ts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "kind": self.kind,
            "started": _iso(self.started_ts),
            "ended": _iso(self.ended_ts) if self.ended_ts is not None else None,
            "open": self.open,
            "duration_s": round(self.duration_s(), 1),
            "events": len(self.events),
            "summary": self.summary,
        }


class EpisodicTimeline:
    """Bounded, thread-safe episodic timeline.

    Episodes are cut by explicit boundary signals (record()) and by the
    silence/sleep detector (poll()). Exactly one episode is open at a time;
    closing one opens the next. Reads never mutate; poll() is the only place
    that may cut on elapsed time, and callers invoke it from a background tick
    so the interactive path never blocks on it.
    """

    def __init__(
        self,
        *,
        silence_cut_s: float = 300.0,
        max_episodes: int = _MAX_EPISODES,
        clock: Callable[[], float] = _utc_now,
    ) -> None:
        self._silence_cut_s = max(30.0, float(silence_cut_s))
        self._max_episodes = max(64, int(max_episodes))
        self._clock = clock
        self._lock = threading.RLock()
        self._episodes: deque[Episode] = deque(maxlen=self._max_episodes)
        self._next_id = 1
        self._last_activity_ts = self._clock()
        # Start in an idle episode so there is always exactly one open episode.
        self._open_locked("idle", "system", "timeline start")

    # ------------------------------------------------------------- recording

    def record(self, kind: str, source: str, summary: str = "", *, activity: bool = True) -> int:
        """Record a typed event. Boundary kinds cut a new episode.

        Returns the id of the episode that now holds the event.
        """
        now = self._clock()
        with self._lock:
            if activity:
                self._last_activity_ts = now
            boundary = kind in ("conversation", "focus", "sleep", "wake")
            if boundary:
                target = "conversation" if kind in ("conversation",) else (
                    "ambient" if kind == "focus" else ("sleep" if kind == "sleep" else "idle")
                )
                self._cut_locked(now, target, source, summary)
            episode = self._current_locked()
            episode.events.append(TimelineEvent(now, kind, str(source)[:60], str(summary)[:200]))
            return episode.episode_id

    def poll(self) -> bool:
        """Cut to an idle episode after sustained silence. Returns True if a cut happened.

        Called from a background tick, never from the interactive path.
        """
        now = self._clock()
        with self._lock:
            current = self._current_locked()
            if current.kind == "sleep":
                return False
            if current.kind == "idle":
                # Keep the idle episode fresh but do not churn ids.
                self._last_activity_ts = now
                return False
            if now - self._last_activity_ts >= self._silence_cut_s:
                self._cut_locked(now, "idle", "silence", f"silence>{int(self._silence_cut_s)}s")
                return True
            return False

    def sleep(self) -> None:
        self.record("sleep", "presence", "owner sleep / DND", activity=False)

    def wake(self) -> None:
        self.record("wake", "presence", "owner active", activity=True)

    # ------------------------------------------------------------------ read

    def current(self) -> dict[str, Any]:
        with self._lock:
            return self._current_locked().to_dict()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            eps = list(self._episodes)[-max(1, min(int(limit), 200)):]
            return [e.to_dict() for e in reversed(eps)]

    def window(self, seconds: float) -> list[dict[str, Any]]:
        """Episodes that overlap the last `seconds` of wall time."""
        cutoff = self._clock() - max(0.0, float(seconds))
        with self._lock:
            out = []
            for e in reversed(self._episodes):
                end = e.ended_ts if e.ended_ts is not None else self._clock()
                if end < cutoff:
                    break
                out.append(e.to_dict())
            return out

    def state(self) -> dict[str, Any]:
        with self._lock:
            current = self._current_locked()
            return {
                "ok": True,
                "now": _iso(self._clock()),
                "episode_count": len(self._episodes),
                "current": current.to_dict(),
                "last_activity_age_s": round(self._clock() - self._last_activity_ts, 1),
                "silence_cut_s": self._silence_cut_s,
            }

    # -------------------------------------------------------------- internals

    def _current_locked(self) -> Episode:
        return self._episodes[-1]

    def _cut_locked(self, ts: float, new_kind: str, source: str, summary: str) -> Episode:
        current = self._current_locked()
        if current.kind == new_kind and current.open:
            return current
        current.close(ts, summary=self._summarize_locked(current))
        return self._open_locked(new_kind, source, summary, ts)

    def _open_locked(self, kind: str, source: str, summary: str, ts: float | None = None) -> Episode:
        start = self._clock() if ts is None else ts
        episode = Episode(self._next_id, kind, start)
        self._next_id += 1
        episode.events.append(TimelineEvent(start, "episode_open", str(source)[:60], str(summary)[:200]))
        self._episodes.append(episode)
        return episode

    @staticmethod
    def _summarize_locked(episode: Episode) -> str:
        """Deterministic, cheap episode summary from event kinds (no LLM here)."""
        if episode.summary:
            return episode.summary
        kinds = [e.kind for e in episode.events if e.kind != "episode_open"]
        if not kinds:
            return f"{episode.kind} (no events)"
        from collections import Counter

        top = ", ".join(f"{k}x{n}" for k, n in Counter(kinds).most_common(3))
        return f"{episode.kind}: {len(kinds)} events ({top})"


__all__ = ["EpisodicTimeline", "Episode", "TimelineEvent"]
