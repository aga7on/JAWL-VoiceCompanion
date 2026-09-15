"""Bounded passive screen-delta producer.

This is a sensor/event layer, not a second personality. It never speaks or
calls JAWL directly; it emits inspectable ``SCREEN_DELTA`` events for a later
Attention/Presence consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque
from threading import Event, RLock, Thread, current_thread
from typing import Any, Callable
from uuid import uuid4

from .arbiter import TurnArbiter, TurnPriority


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScreenDeltaWatcher:
    """Poll explicit vision at a bounded interval and publish new deltas."""

    vision: Any
    arbiter: TurnArbiter
    interval_seconds: float = 10.0
    prompt: str = "Кратко опиши заметное изменение в сфокусированном окне."
    session_id: str = "local"
    event_sink: Callable[[dict[str, Any]], None] | None = None
    _stop: Event = field(default_factory=Event, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _thread: Thread | None = field(default=None, init=False, repr=False)
    _events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=100), init=False, repr=False
    )
    _last_error: str | None = field(default=None, init=False, repr=False)
    _idle_polls: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.interval_seconds = max(2.0, min(float(self.interval_seconds), 3600.0))
        self.prompt = str(self.prompt or "").strip()[:1200] or "Опиши заметное изменение в окне."
        self.session_id = str(self.session_id or "local")[:200]

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="screen-delta-watcher", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(0.0, min(float(timeout), 10.0)))
        with self._lock:
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None

    def poll_once(self) -> dict[str, Any]:
        """Run one arbiter-aware poll; useful for tests and controlled hosts."""
        token = self.arbiter.begin(TurnPriority.SCREEN_DELTA)
        if not self.arbiter.is_current(token):
            self.arbiter.cancel(token, "screen_poll_deferred_for_higher_priority_work")
            # A fresh user turn must not leave the watcher parked in back-off.
            self._idle_polls = 0
            return {"status": "deferred", "reason": "higher_priority_work_active", "event": None}
        result: dict[str, Any] | None = None
        try:
            result = self.vision.look(self.prompt, session_id=self.session_id)
            if token.cancelled:
                return {"status": "cancelled", "reason": "screen_poll_superseded", "event": None}
            if result.get("status") != "ok":
                with self._lock:
                    self._last_error = str(result.get("reason") or result.get("status") or "vision_unavailable")[:200]
                return result
            event = self._make_event(result)
            sink_failed = False
            # Publish before exposing the event through events().  Consumers use
            # that deque as the readiness signal; recording first made them race
            # the synchronous file sink and observe a missing IPC artifact.
            if self.event_sink is not None:
                try:
                    self.event_sink(event)
                except Exception:
                    sink_failed = True
            with self._lock:
                self._events.append(event)
                self._last_error = "screen_event_sink_failed" if sink_failed else None
            return {**result, "event": event}
        except Exception:
            with self._lock:
                self._last_error = "screen_watcher_poll_failed"
            return {"status": "degraded", "reason": "screen_watcher_poll_failed", "event": None}
        finally:
            status = result.get("status") if isinstance(result, dict) else None
            if status == "unchanged":
                self._idle_polls += 1
            elif status == "ok":
                self._idle_polls = 0
            self.arbiter.complete(token)

    def state(self) -> dict[str, Any]:
        with self._lock:
            last_event = self._events[-1] if self._events else None
            return {
                "running": self._thread is not None and self._thread.is_alive(),
                "interval_seconds": self.interval_seconds,
                "idle_polls": self._idle_polls,
                "next_wait_seconds": round(self._next_wait(), 1),
                "event_count": len(self._events),
                "last_event": last_event,
                "last_error": self._last_error,
            }

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._next_wait())

    def _next_wait(self) -> float:
        """Back vision polling off while the screen stays unchanged.

        One unchanged poll keeps the base cadence; consecutive unchanged
        polls slow the watcher down to 4x, and any published change (or a
        fresh user turn being deferred) returns it to the base interval.
        """
        idle = self._idle_polls
        if idle < 2:
            return self.interval_seconds
        factor = min(4.0, float(idle))
        return min(3600.0, self.interval_seconds * factor)

    def _make_event(self, result: dict[str, Any]) -> dict[str, Any]:
        description = str(result.get("description") or "").strip()[:4000]
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "session_id": self.session_id,
            "created_at": _now(),
            "source": "screen_sensor",
            "type": "SCREEN_DELTA",
            "priority": int(TurnPriority.SCREEN_DELTA),
            "payload": {
                "summary": description,
                # A changed focused window is the event itself: baseline 2 so
                # it clears the attention threshold; salient wording (errors,
                # dialogs, "важно") is bumped to 3 by the attention scorer.
                "significance": 2,
                "captured_at": str(result.get("captured_at") or _now()),
                "changed": True,
                "raw_frame_persisted": False,
            },
        }
