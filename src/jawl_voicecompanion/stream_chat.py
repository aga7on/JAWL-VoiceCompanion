"""Bounded, transport-agnostic ingestion for already-delivered stream chat events.

This module deliberately does not know how a chat provider is polled.  A caller
hands it one provider event at a time, and the module emits a small, safe
``CHAT_MESSAGE`` envelope to a downstream Attention/JAWL callback.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import uuid4


_STOP = object()
_WS = re.compile(r"\s+")
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return _WS.sub(" ", str(value).replace("\x00", "")).strip()[:limit]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else MappingProxyType({})


@dataclass(frozen=True)
class StreamChatLimits:
    """Hard limits applied before an event can enter the queue."""

    max_text: int = 500
    max_author: int = 120
    max_platform: int = 40
    max_channel: int = 160
    max_message_id: int = 160
    max_session_id: int = 160
    max_url: int = 2048
    max_title: int = 240
    max_queue_items: int = 128
    max_queue_bytes: int = 256 * 1024
    dedup_capacity: int = 2048
    dedup_ttl_seconds: float = 3600.0
    rate_per_second: float = 4.0
    rate_burst: int = 8

    def __post_init__(self) -> None:
        for name in (
            "max_text",
            "max_author",
            "max_platform",
            "max_channel",
            "max_message_id",
            "max_session_id",
            "max_url",
            "max_title",
            "max_queue_items",
            "max_queue_bytes",
            "dedup_capacity",
            "rate_burst",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.dedup_ttl_seconds <= 0 or self.rate_per_second <= 0:
            raise ValueError("dedup_ttl_seconds and rate_per_second must be positive")


ModerationHook = Callable[[Mapping[str, Any]], bool]
Downstream = Callable[[dict[str, Any]], Any]


@dataclass
class StreamChatIngestor:
    """Accept bounded chat events and deliver them without blocking producers.

    ``moderation_hook`` receives the already-normalized envelope and must
    return ``True`` to allow delivery.  Exceptions from the hook suppress the
    event.  The class never performs network I/O; URL metadata is metadata only.
    """

    downstream: Downstream | None = None
    moderation_hook: ModerationHook | None = None
    limits: StreamChatLimits = field(default_factory=StreamChatLimits)
    session_id: str = "local"
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], str] = _utc_now
    auto_start: bool = True

    def __post_init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self.limits.max_queue_items)
        self._lock = threading.RLock()
        self._state = "new"
        self._worker: threading.Thread | None = None
        self._stop_requested = False
        self._drain_on_stop = True
        self._queued_bytes = 0
        self._seen: dict[str, float] = {}
        self._seen_order: deque[tuple[str, float]] = deque()
        self._delivered: deque[dict[str, Any]] = deque(maxlen=min(self.limits.max_queue_items, 256))
        self._stats = {
            "accepted": 0,
            "delivered": 0,
            "duplicates": 0,
            "moderated": 0,
            "rate_limited": 0,
            "backpressure": 0,
            "invalid": 0,
            "sink_errors": 0,
            "dropped_on_stop": 0,
        }
        self._tokens = float(self.limits.rate_burst)
        self._last_refill = self.clock()
        if self.auto_start:
            self.start()

    def start(self) -> dict[str, Any]:
        """Start the delivery worker; repeated calls are harmless."""
        with self._lock:
            if self._state == "closed":
                return self.state()
            if self._state == "running":
                return self.state()
            self._stop_requested = False
            self._drain_on_stop = True
            self._state = "running"
            self._worker = threading.Thread(
                target=self._run,
                name="stream-chat-ingestor",
                daemon=True,
            )
            self._worker.start()
            return self.state()

    def accept(
        self,
        event: Mapping[str, Any],
        url_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Try to enqueue one already-delivered provider event.

        This method is non-blocking under load.  The returned status is one of
        ``accepted``, ``duplicate``, ``moderated``, ``rate_limited``,
        ``backpressure``, ``stopped``, or ``invalid``.
        """
        try:
            envelope = self._normalize(event, url_metadata)
        except (TypeError, ValueError):
            with self._lock:
                self._stats["invalid"] += 1
            return {"status": "invalid", "reason": "invalid_chat_event"}

        payload_size = len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        key = self._dedup_key(envelope)
        with self._lock:
            if self._state != "running":
                return {"status": "stopped", "reason": "ingestor_not_running"}
            self._expire_seen(self.clock())
            if key in self._seen:
                self._stats["duplicates"] += 1
                return {"status": "duplicate", "reason": "chat_event_seen"}
            if not self._allowed_by_moderation(envelope):
                self._remember(key)
                self._stats["moderated"] += 1
                return {"status": "moderated", "reason": "chat_event_denied"}
            if not self._take_token():
                self._stats["rate_limited"] += 1
                return {"status": "rate_limited", "reason": "chat_rate_limit"}
            if self._queued_bytes + payload_size > self.limits.max_queue_bytes:
                self._stats["backpressure"] += 1
                return {"status": "backpressure", "reason": "chat_queue_bytes"}
            try:
                self._queue.put_nowait((envelope, payload_size))
            except queue.Full:
                self._stats["backpressure"] += 1
                return {"status": "backpressure", "reason": "chat_queue_items"}
            self._queued_bytes += payload_size
            self._remember(key)
            self._stats["accepted"] += 1
            return {"status": "accepted", "event_id": envelope["event_id"]}

    def stop(self, *, drain: bool = True, timeout: float | None = 5.0) -> dict[str, Any]:
        """Stop intake and optionally deliver queued events before returning."""
        with self._lock:
            if self._state in {"new", "stopped", "closed"}:
                if self._state == "new":
                    self._state = "stopped"
                return self.state()
            self._state = "stopping"
            self._stop_requested = True
            self._drain_on_stop = bool(drain)
            if not drain:
                self._drop_queued()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=None if timeout is None else max(0.0, float(timeout)))
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._state = "stopped"
                self._worker = None
            return self.state()

    def close(self, *, timeout: float | None = 5.0) -> dict[str, Any]:
        """Permanently close the ingestor after dropping pending work."""
        self.stop(drain=False, timeout=timeout)
        with self._lock:
            self._state = "closed"
            return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "queued_items": self._queue.qsize(),
                "queued_bytes": self._queued_bytes,
                "worker_alive": bool(self._worker and self._worker.is_alive()),
                "stats": dict(self._stats),
            }

    def delivered(self) -> list[dict[str, Any]]:
        """Return a bounded diagnostic copy of envelopes delivered downstream."""
        with self._lock:
            return [dict(item) for item in self._delivered]

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._stop_requested and (not self._drain_on_stop or self._queue.empty()):
                    return
            try:
                item = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is _STOP:
                return
            envelope, payload_size = item
            with self._lock:
                self._queued_bytes = max(0, self._queued_bytes - payload_size)
            try:
                if self.downstream is not None:
                    self.downstream(envelope)
                with self._lock:
                    self._delivered.append(envelope)
                    self._stats["delivered"] += 1
            except Exception:  # noqa: BLE001 - downstream is an isolation boundary
                with self._lock:
                    self._stats["sink_errors"] += 1
            finally:
                self._queue.task_done()

    def _normalize(self, event: Mapping[str, Any], url_metadata: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise TypeError("event must be a mapping")
        payload = _mapping(event.get("payload"))
        text = _text(event.get("text", payload.get("text")), self.limits.max_text)
        if not text:
            raise ValueError("chat text is required")
        platform = _text(event.get("platform", event.get("source", payload.get("platform"))), self.limits.max_platform)
        author = _text(event.get("author", event.get("user", payload.get("author"))), self.limits.max_author)
        channel = _text(event.get("channel_id", event.get("channel", payload.get("channel_id"))), self.limits.max_channel)
        message_id = _text(event.get("message_id", event.get("id", payload.get("message_id"))), self.limits.max_message_id)
        session_id = _text(event.get("session_id", self.session_id), self.limits.max_session_id) or "local"
        metadata = url_metadata if url_metadata is not None else event.get("url_metadata")
        safe_metadata = self._normalize_url_metadata(metadata)
        safe_payload: dict[str, Any] = {"text": text}
        for key, value in (("platform", platform), ("author", author), ("channel_id", channel), ("message_id", message_id)):
            if value:
                safe_payload[key] = value
        if safe_metadata:
            safe_payload["url_metadata"] = safe_metadata
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "session_id": session_id,
            "created_at": self.now(),
            "source": "stream_chat",
            "type": "CHAT_MESSAGE",
            "payload": safe_payload,
        }

    def _normalize_url_metadata(self, value: Any) -> dict[str, str]:
        metadata = _mapping(value)
        if not metadata:
            return {}
        result: dict[str, str] = {}
        raw_url = _text(metadata.get("url"), self.limits.max_url)
        if raw_url:
            parsed: SplitResult = urlsplit(raw_url)
            if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES or not parsed.hostname:
                raise ValueError("url metadata must be an http(s) URL")
            host = parsed.hostname.lower()
            netloc = host
            if parsed.port:
                netloc = f"{host}:{parsed.port}"
            result["url"] = urlunsplit((parsed.scheme.lower(), netloc, parsed.path[:512], "", ""))[: self.limits.max_url]
            result["host"] = host[:253]
        title = _text(metadata.get("title"), self.limits.max_title)
        if title:
            result["title"] = title
        return result

    def _dedup_key(self, envelope: Mapping[str, Any]) -> str:
        payload = _mapping(envelope.get("payload"))
        message_id = _text(payload.get("message_id"), self.limits.max_message_id)
        if message_id:
            identity = "id:" + "|".join(
                (_text(payload.get("platform"), 40), _text(payload.get("channel_id"), 160), message_id)
            )
        else:
            identity = "text:" + "|".join(
                (_text(payload.get("platform"), 40), _text(payload.get("author"), 120), _text(payload.get("text"), 500))
            )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _remember(self, key: str) -> None:
        expires = self.clock() + self.limits.dedup_ttl_seconds
        self._seen[key] = expires
        self._seen_order.append((key, expires))
        while len(self._seen) > self.limits.dedup_capacity and self._seen_order:
            old_key, old_expiry = self._seen_order.popleft()
            if self._seen.get(old_key) == old_expiry:
                self._seen.pop(old_key, None)

    def _expire_seen(self, now: float) -> None:
        while self._seen_order and self._seen_order[0][1] <= now:
            key, expiry = self._seen_order.popleft()
            if self._seen.get(key) == expiry:
                self._seen.pop(key, None)

    def _take_token(self) -> bool:
        now = self.clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(float(self.limits.rate_burst), self._tokens + elapsed * self.limits.rate_per_second)
        self._last_refill = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def _allowed_by_moderation(self, envelope: Mapping[str, Any]) -> bool:
        if self.moderation_hook is None:
            return True
        try:
            return bool(self.moderation_hook(envelope))
        except Exception:  # noqa: BLE001 - failed moderation is fail-closed
            return False

    def _drop_queued(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                self._queued_bytes = 0
                return
            if item is not _STOP:
                self._stats["dropped_on_stop"] += 1
            self._queue.task_done()


__all__ = ["Downstream", "ModerationHook", "StreamChatIngestor", "StreamChatLimits"]
