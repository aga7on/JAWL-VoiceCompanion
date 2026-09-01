"""Bounded, delayed secondary memory for ambient observations.

This module deliberately accepts only normalized text events. Capture, ASR and
VLM providers remain replaceable and must never turn ambient data into a user
conversation or a direct action.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any
from uuid import uuid4

from .ambient_triage import AmbientTriageProvider, validate_triage_result


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
        triage_provider: AmbientTriageProvider | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.observation_ttl_seconds = max(1.0, min(float(observation_ttl_seconds), 7 * 24 * 3600.0))
        self.episode_ttl_seconds = max(60.0, min(float(episode_ttl_seconds), 30 * 24 * 3600.0))
        self.episode_window_seconds = max(1.0, min(float(episode_window_seconds), 3600.0))
        self.max_observations = max(1, min(int(max_observations), 4096))
        self.max_episodes = max(1, min(int(max_episodes), 512))
        self.max_bytes = max(4096, min(int(max_bytes), 4 * 1024 * 1024))
        self.max_episode_bytes = max(4096, min(int(max_episode_bytes), 4 * 1024 * 1024))
        self.triage_provider = triage_provider
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

    def triage(
        self,
        *,
        now: float | None = None,
        max_items: int = 64,
        provider: AmbientTriageProvider | None = None,
    ) -> dict[str, Any]:
        """Coalesce observations locally or through an explicitly configured provider."""
        timestamp = time.time() if now is None else float(now)
        provider = provider or self.triage_provider
        with self._lock:
            self._prune(timestamp)
            pending = [item for item in self._observations if not item.triaged][: max(1, min(int(max_items), 256))]
            groups: list[list[_StoredObservation]] = []
            for item in pending:
                if not groups or item.received_at - groups[-1][-1].received_at > self.episode_window_seconds:
                    groups.append([])
                groups[-1].append(item)

            episodes: list[dict[str, Any]] = []
            ignored = 0
            if provider is not None:
                prepared: list[tuple[list[_StoredObservation], dict[str, Any]]] = []
                try:
                    for group in groups:
                        result = provider.triage([item.event for item in group])
                        event_ids = {item.event["event_id"] for item in group}
                        prepared.append((group, validate_triage_result(result, event_ids)))
                except Exception as exc:
                    return {
                        "status": "provider_error",
                        "provider": self._provider_name(provider),
                        "episodes": [],
                        "ignored": 0,
                        "error": str(exc)[:200] or type(exc).__name__,
                    }
                for group, payload in prepared:
                    for item in group:
                        item.triaged = True
                    if payload["importance"] == "ignore":
                        ignored += 1
                        continue
                    episode = self._episode_from_payload(group, payload, timestamp, self._provider_name(provider))
                    if self._append_episode(episode):
                        episodes.append(episode)
                return {
                    "status": "processed",
                    "provider": self._provider_name(provider),
                    "episodes": episodes,
                    "ignored": ignored,
                }

            for item in pending:
                item.triaged = True
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
                "triage_provider": self._provider_name(self.triage_provider) if self.triage_provider else None,
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

    @staticmethod
    def _provider_name(provider: Any) -> str:
        return _bounded_text(getattr(provider, "name", "") or type(provider).__name__, 80)

    def _episode_from_payload(
        self,
        group: list[_StoredObservation],
        payload: dict[str, Any],
        now: float,
        provider_name: str,
    ) -> dict[str, Any]:
        observed = [str(item.event["payload"].get("observed_at")) for item in group]
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "session_id": "ambient-memory",
            "created_at": _iso(now),
            "source": "ambient_memory",
            "type": _EPISODE_EVENT,
            "priority": 4,
            "payload": {
                **payload,
                "triage_provider": provider_name,
                "observed_from": min(observed) if observed else _iso(group[0].received_at),
                "observed_until": max(observed) if observed else _iso(group[-1].received_at),
                "retention_until": _iso(now + self.episode_ttl_seconds),
                "raw_audio_persisted": False,
                "raw_frame_persisted": False,
            },
        }

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


class AmbientTriageScheduler:
    """Opt-in bounded background triage; never creates turns or invokes tools."""

    def __init__(self, memory: AmbientMemoryBuffer, interval_seconds: float = 300.0) -> None:
        self.memory = memory
        self.interval_seconds = max(1.0, min(float(interval_seconds), 24 * 3600.0))
        self._stop = Event()
        self._lock = RLock()
        self._thread: Thread | None = None
        self._last: dict[str, Any] = {"status": "never", "episodes": 0, "error": None}

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = Thread(target=self._run, name="ambient-triage", daemon=True)
                self._thread.start()
        return self.state()

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(0.0, min(float(timeout), 10.0)))
        with self._lock:
            if thread is None or not thread.is_alive():
                self._thread = None
        return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "enabled": True,
                "running": running,
                "interval_seconds": self.interval_seconds,
                **self._last,
            }

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                result = self.memory.triage()
                update = {
                    "status": str(result.get("status") or "unknown")[:40],
                    "episodes": len(result.get("episodes") or []),
                    "error": str(result.get("error") or "")[:200] or None,
                }
            except Exception as exc:  # keep an autonomous worker from taking down the server
                update = {"status": "error", "episodes": 0, "error": type(exc).__name__}
            with self._lock:
                self._last = update


__all__ = ["AmbientMemoryBuffer", "AmbientTriageScheduler"]
