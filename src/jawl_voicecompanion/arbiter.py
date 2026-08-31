"""Priority and cancellation bookkeeping for one active conversational turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from threading import Event, RLock
from typing import Any
from uuid import uuid4


class TurnPriority(IntEnum):
    USER_FINAL = 0
    TOOL_APPROVAL = 1
    PROACTIVE = 2
    SCREEN_DELTA = 3
    BACKGROUND = 4


@dataclass
class TurnToken:
    turn_id: str
    priority: TurnPriority
    generation: int
    active: bool = False
    cancelled: bool = False
    cancel_reason: str | None = None
    cancel_event: Event = field(default_factory=Event, repr=False)

    def cancel(self, reason: str) -> None:
        self.cancelled = True
        self.active = False
        self.cancel_reason = reason
        self.cancel_event.set()


@dataclass
class TurnArbiter:
    """Keep exactly one active turn and bound stale queued work."""

    _generation: int = 0
    _active: TurnToken | None = None
    _queued: list[TurnToken] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def begin(
        self,
        priority: TurnPriority | int,
        turn_id: str | None = None,
    ) -> TurnToken:
        lane = TurnPriority(int(priority))
        with self._lock:
            self._generation += 1
            token = TurnToken(turn_id or str(uuid4()), lane, self._generation)

            # A fresh user turn invalidates all older non-user work, including
            # queued screen/background observations.
            if lane == TurnPriority.USER_FINAL:
                for queued in self._queued:
                    queued.cancel("superseded_by_user_turn")
                self._queued.clear()

            if self._active is None:
                token.active = True
                self._active = token
            elif lane <= self._active.priority:
                self._active.cancel("superseded_by_newer_priority_turn")
                token.active = True
                self._active = token
            else:
                self._queued.append(token)
                self._queued.sort(key=lambda item: (item.priority, item.generation))
            return token

    def complete(self, token: TurnToken) -> TurnToken | None:
        with self._lock:
            if self._active is token:
                token.active = False
                self._active = None
                return self._promote_next()
            if token in self._queued:
                self._queued.remove(token)
            return self._active

    def cancel(self, token: TurnToken, reason: str = "cancelled") -> TurnToken | None:
        with self._lock:
            token.cancel(reason)
            if self._active is token:
                self._active = None
                return self._promote_next()
            if token in self._queued:
                self._queued.remove(token)
            return self._active

    def cancel_all(self, reason: str = "cancelled_all") -> None:
        with self._lock:
            if self._active:
                self._active.cancel(reason)
            for token in self._queued:
                token.cancel(reason)
            self._active = None
            self._queued.clear()

    def is_current(self, token: TurnToken) -> bool:
        with self._lock:
            return self._active is token and token.active and not token.cancelled

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "generation": self._generation,
                "active": self._serialize(self._active),
                "queued": [self._serialize(token) for token in self._queued],
            }

    def _promote_next(self) -> TurnToken | None:
        while self._queued:
            candidate = self._queued.pop(0)
            if candidate.cancelled:
                continue
            candidate.active = True
            self._active = candidate
            return candidate
        return None

    @staticmethod
    def _serialize(token: TurnToken | None) -> dict[str, Any] | None:
        if token is None:
            return None
        return {
            "turn_id": token.turn_id,
            "priority": token.priority.name,
            "generation": token.generation,
            "active": token.active,
            "cancelled": token.cancelled,
            "cancel_reason": token.cancel_reason,
        }
