"""Bounded, transient identities for speech-only cancellation and replay drop."""

from __future__ import annotations

import re
import threading
import time
from typing import Callable


def validate_speech_request_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("request_id must be 1-128 ASCII letters, digits, underscores or hyphens")
    return value


class SpeechRequests:
    """Keep cancel-before-start tombstones without retaining text or raw audio.

    Completed IDs cannot be reused during the TTL. Active entries never expire
    under a running caller; saturation fails closed instead of evicting a token.
    """

    def __init__(self, *, limit: int = 128, ttl_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 event_factory: Callable[[], threading.Event] = threading.Event):
        self._limit = limit
        self._ttl = ttl_seconds
        self._clock = clock
        self._event_factory = event_factory
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[threading.Event, float | None]] = {}

    def _prune(self) -> None:
        now = self._clock()
        for key, (_, expiry) in list(self._entries.items()):
            if expiry is not None and expiry <= now:
                del self._entries[key]

    def _insert(self, key: str, *, cancelled: bool) -> threading.Event:
        if len(self._entries) >= self._limit:
            raise RuntimeError("speech request registry is full; retry with a new ID after its TTL")
        token = self._event_factory()
        if cancelled:
            token.set()
        self._entries[key] = (token, self._clock() + self._ttl if cancelled else None)
        return token

    def begin(self, request_id: str | None) -> threading.Event:
        if request_id is None:
            return self._event_factory()
        key = validate_speech_request_id(request_id)
        with self._lock:
            self._prune()
            entry = self._entries.get(key)
            if entry is not None:
                token, expiry = entry
                if expiry is None:
                    raise ValueError("request_id is already active")
                # A cancelled or completed request must never become new work.
                return token
            return self._insert(key, cancelled=False)

    def cancel(self, request_id: str) -> threading.Event:
        key = validate_speech_request_id(request_id)
        with self._lock:
            self._prune()
            entry = self._entries.get(key)
            token = entry[0] if entry is not None else self._insert(key, cancelled=True)
            token.set()
            return token

    def finish(self, token: threading.Event) -> None:
        token.set()
        with self._lock:
            for key, (owned, expiry) in self._entries.items():
                if owned is token and expiry is None:
                    self._entries[key] = (owned, self._clock() + self._ttl)
                    break
