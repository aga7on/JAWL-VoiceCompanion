"""Bounded, delayed secondary memory for ambient observations.

This module deliberately accepts only normalized text events. Capture, ASR and
VLM providers remain replaceable and must never turn ambient data into a user
conversation or a direct action.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from threading import RLock
import time
from typing import Any
from uuid import uuid4


_AUDIO_EVENT = "AMBIENT_AUDIO_OBSERVATION"
_VISUAL_EVENT = "AMBIENT_VISUAL_OBSERVATION"
_EPISODE_EVENT = "AMBIENT_EPISODE_CANDIDATE"
_PRIVATE = re.compile(
    r"password|passwd|token|secret|api[_ -]?key|парол|токен|секрет|ключ\s+api",
    re.IGNORECASE,
)
_SALIENT = re.compile(
    r"error|exception|warning|failed|failure|deadline|urgent|important|remember|"
    r"ошиб|исключен|предупрежд|сроч|дедлайн|важн|запомн|квест|цель",
    re.IGNORECASE,
)
_TOPICS = (
    ("error", re.compile(r"error|exception|failed|failure|ошиб|исключен", re.IGNORECASE)),
    ("warning", re.compile(r"warning|предупрежд", re.IGNORECASE)),
    ("deadline", re.compile(r"deadline|urgent|сроч|дедлайн", re.IGNORECASE)),
    ("important", re.compile(r"important|remember|важн|запомн", re.IGNORECASE)),
    ("goal", re.compile(r"goal|квест|цель", re.IGNORECASE)),
)


def _iso(timestamp: float | None = None) -> str:
    value = time.time() if timestamp is None else float(timestamp)
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.5
    return round(max(0.0, min(1.0, float(value))), 3)


@dataclass
class _StoredObservation:
    event: dict[str, Any]
    received_at: float
    expires_at: float
    size: int
    triaged: bool = False


class AmbientMemoryBuffer:
    """Keep bounded ambient observations and form delayed episode candidates."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        observation_ttl_seconds: float = 1800.0,
        episode_ttl_seconds: float = 7 * 24 * 3600.0,
        episode_window_seconds: float = 300.0,
        max_observations: int = 256,
        max_episodes: int = 64,
        max_bytes: int = 256 * 1024,
        max_episode_bytes: int = 256 * 1024,
    ) -> None:
        self.enabled = bool(enabled)
        self.observation_ttl_seconds = max(1.0, min(float(observation_ttl_seconds), 7 * 24 * 3600.0))
        self.episode_ttl_seconds = max(60.0, min(float(episode_ttl_seconds), 30 * 24 * 3600.0))
        self.episode_window_seconds = max(1.0, min(float(episode_window_seconds), 3600.0))
        self.max_observations = max(1, min(int(max_observations), 4096))
        self.max_episodes = max(1, min(int(max_episodes), 512))
        self.max_bytes = max(4096, min(int(max_bytes), 4 * 1024 * 1024))
        self.max_episode_bytes = max(4096, min(int(max_episode_bytes), 4 * 1024 * 1024))
        self._observations: deque[_StoredObservation] = deque()
        self._episodes: deque[dict[str, Any]] = deque(maxlen=self.max_episodes)
        self._bytes = 0
        self._episode_bytes = 0
        self._lock = RLock()

    def ingest(self, event: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        """Normalize one ambient event without retaining raw media or unknown fields."""
        if not self.enabled:
            return {"status": "disabled", "reason": "ambient_capture_disabled"}
        if not isinstance(event, dict):
            raise TypeError("ambient event must be an object")
        event_type = event.get("type")
        if event_type not in {_AUDIO_EVENT, _VISUAL_EVENT}:
            return {"status": "ignored", "reason": "unsupported_ambient_event"}
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return {"status": "ignored", "reason": "ambient_payload_missing"}

        stream = "system_audio" if event_type == _AUDIO_EVENT else "screen"
        text_key = "text" if stream == "system_audio" else "summary"
        text = _bounded_text(payload.get(text_key), 1200)
        if not text:
            return {"status": "ignored", "reason": "ambient_text_missing"}
        if _PRIVATE.search(text):
            return {"status": "suppressed", "reason": "ambient_text_private"}

        received_at = time.time() if now is None else float(now)
        event_id = _bounded_text(event.get("event_id"), 120) or str(uuid4())
        session_id = _bounded_text(event.get("session_id"), 120) or "ambient"
        source_app = _bounded_text(payload.get("source_app"), 80)
        if _PRIVATE.search(source_app):
            source_app = ""
        observed_at = _bounded_text(
            payload.get("observed_at") or payload.get("captured_at") or event.get("created_at"),
            80,
        ) or _iso(received_at)
        retention_until = _iso(received_at + self.observation_ttl_seconds)
        normalized_payload: dict[str, Any] = {
            "stream": stream,
            text_key: text,
            "confidence": _confidence(payload.get("confidence")),
            "observed_at": observed_at,
            "raw_audio_persisted": False,
            "raw_frame_persisted": False,
            "retention_until": retention_until,
        }
        if source_app:
            normalized_payload["source_app"] = source_app
        normalized = {
            "schema_version": 1,
            "event_id": event_id,
            "session_id": session_id,
            "created_at": _bounded_text(event.get("created_at"), 80) or _iso(received_at),
            "source": "ambient_memory",
            "type": event_type,
            "priority": 4,
            "payload": normalized_payload,
        }
        size = len(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > self.max_bytes:
            return {"status": "ignored", "reason": "ambient_event_too_large"}

        with self._lock:
            self._prune(received_at)
            if any(item.event["event_id"] == event_id for item in self._observations):
                return {"status": "duplicate", "reason": "ambient_event_seen", "event_id": event_id}
            while self._observations and (
                len(self._observations) >= self.max_observations
                or self._bytes + size > self.max_bytes
            ):
                removed = self._observations.popleft()
                self._bytes -= removed.size
            if len(self._observations) >= self.max_observations or self._bytes + size > self.max_bytes:
                return {"status": "ignored", "reason": "ambient_buffer_full"}
            stored = _StoredObservation(normalized, received_at, received_at + self.observation_ttl_seconds, size)
            self._observations.append(stored)
            self._bytes += size
        return {"status": "retained", "observation": normalized}

    def ingest_system_audio(
        self,
        text: str,
        *,
        confidence: float = 0.5,
        source_app: str | None = None,
        event_id: str | None = None,
        session_id: str = "ambient-audio",
        now: float | None = None,
    ) -> dict[str, Any]:
        return self.ingest(
            {
                "schema_version": 1,
                "event_id": event_id or str(uuid4()),
                "session_id": session_id,
                "type": _AUDIO_EVENT,
                "payload": {"text": text, "confidence": confidence, "source_app": source_app},
            },
            now=now,
        )

    def ingest_visual(
        self,
        summary: str,
        *,
        confidence: float = 0.5,
        source_app: str | None = None,
        event_id: str | None = None,
        session_id: str = "ambient-screen",
        now: float | None = None,
    ) -> dict[str, Any]:
        return self.ingest(
            {
                "schema_version": 1,
                "event_id": event_id or str(uuid4()),
                "session_id": session_id,
                "type": _VISUAL_EVENT,
                "payload": {"summary": summary, "confidence": confidence, "source_app": source_app},
            },
            now=now,
        )

    def triage(self, *, now: float | None = None, max_items: int = 64) -> dict[str, Any]:
        """Coalesce unprocessed observations using deterministic local rules."""
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune(timestamp)
            pending = [item for item in self._observations if not item.triaged][: max(1, min(int(max_items), 256))]
            for item in pending:
                item.triaged = True
            groups: list[list[_StoredObservation]] = []
            for item in pending:
                if not groups or item.received_at - groups[-1][-1].received_at > self.episode_window_seconds:
                    groups.append([])
                groups[-1].append(item)

            episodes: list[dict[str, Any]] = []
            ignored = 0
            for group in groups:
                episode = self._episode(group, timestamp)
                if episode is None:
                    ignored += 1
                    continue
                if self._append_episode(episode):
                    episodes.append(episode)
        return {"status": "processed", "episodes": episodes, "ignored": ignored}

    def observations(self, *, now: float | None = None) -> list[dict[str, Any]]:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune(timestamp)
            return [dict(item.event) for item in self._observations]

    def episodes(self, *, now: float | None = None) -> list[dict[str, Any]]:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune(timestamp)
            return [dict(item) for item in self._episodes]

    def state(self, *, now: float | None = None) -> dict[str, Any]:
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune(timestamp)
            return {
                "enabled": self.enabled,
                "observation_count": len(self._observations),
                "episode_count": len(self._episodes),
                "buffer_bytes": self._bytes,
                "max_observations": self.max_observations,
                "max_bytes": self.max_bytes,
                "max_episode_bytes": self.max_episode_bytes,
                "observation_ttl_seconds": self.observation_ttl_seconds,
                "episode_ttl_seconds": self.episode_ttl_seconds,
            }

    def clear(self) -> dict[str, Any]:
        with self._lock:
            observations = len(self._observations)
            episodes = len(self._episodes)
            self._observations.clear()
            self._episodes.clear()
            self._bytes = 0
            self._episode_bytes = 0
        return {"status": "cleared", "observations": observations, "episodes": episodes}

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self.enabled = bool(enabled)
        return self.state()

    def _prune(self, now: float) -> None:
        while self._observations and self._observations[0].expires_at <= now:
            removed = self._observations.popleft()
            self._bytes -= removed.size
        while self._episodes:
            retention = self._episodes[0].get("payload", {}).get("retention_until")
            try:
                expires = datetime.fromisoformat(str(retention)).timestamp()
            except (TypeError, ValueError, OverflowError):
                expires = now
            if expires > now:
                break
            removed = self._episodes.popleft()
            self._episode_bytes -= self._serialized_size(removed)

    def _append_episode(self, episode: dict[str, Any]) -> bool:
        size = self._serialized_size(episode)
        if size > self.max_episode_bytes:
            return False
        while self._episodes and (
            len(self._episodes) >= self.max_episodes
            or self._episode_bytes + size > self.max_episode_bytes
        ):
            removed = self._episodes.popleft()
            self._episode_bytes -= self._serialized_size(removed)
        self._episodes.append(episode)
        self._episode_bytes += size
        return True

    @staticmethod
    def _serialized_size(value: dict[str, Any]) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _episode(self, group: list[_StoredObservation], now: float) -> dict[str, Any] | None:
        payloads = [item.event["payload"] for item in group]
        confidence = round(sum(float(item.get("confidence", 0.5)) for item in payloads) / len(payloads), 3)
        texts = [str(item.get("text") or item.get("summary") or "").strip() for item in payloads]
        combined = " ".join(text for text in texts if text)[:600]
        if confidence < 0.35 or len(combined) < 8:
            return None
        salient = bool(_SALIENT.search(combined))
        importance = "promote_candidate" if salient and confidence >= 0.7 else "retain"
        topics = [name for name, pattern in _TOPICS if pattern.search(combined)][:5]
        streams = {str(item.get("stream")) for item in payloads}
        source = next(iter(streams)) if len(streams) == 1 else "mixed"
        observed = [str(item.get("observed_at")) for item in payloads if item.get("observed_at")]
        retention_until = _iso(now + self.episode_ttl_seconds)
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "session_id": "ambient-memory",
            "created_at": _iso(now),
            "source": "ambient_memory",
            "type": _EPISODE_EVENT,
            "priority": 4,
            "payload": {
                "importance": importance,
                "summary": combined,
                "topics": topics,
                "confidence": confidence,
                "source": source,
                "source_event_ids": [item.event["event_id"] for item in group[:32]],
                "observed_from": min(observed) if observed else _iso(group[0].received_at),
                "observed_until": max(observed) if observed else _iso(group[-1].received_at),
                "retention_until": retention_until,
                "raw_audio_persisted": False,
                "raw_frame_persisted": False,
            },
        }


__all__ = ["AmbientMemoryBuffer"]
