"""Small Attention/Presence gate for passive screen observations."""

from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from .arbiter import TurnPriority


_SALIENT = re.compile(
    r"(?:error|exception|warning|failed|failure|critical|alert|dialog|confirm|"
    r"ошиб|исключен|предупрежд|сбой|критичес|уведомлен|подтвержден|внимани)",
    re.IGNORECASE,
)
_PRIVATE = re.compile(
    r"(?:password|passcode|api[ _-]?key|secret|token|парол|токен|секрет|ключ)",
    re.IGNORECASE,
)
_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AttentionPresence:
    """Turn screen deltas into bounded, optional proactive intents."""

    min_significance: int = 2
    cooldown_seconds: float = 30.0
    budget_per_hour: int = 6
    dnd: bool = False
    quiet_hours: str | None = None
    clock: Callable[[], datetime] | None = None
    intent_sink: Callable[[dict[str, Any]], Any] | None = None
    activity_provider: Callable[[], dict[str, Any]] | None = None
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _seen: deque[str] = field(default_factory=lambda: deque(maxlen=200), init=False, repr=False)
    _intents: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=50), init=False, repr=False)
    _intent_times: deque[float] = field(default_factory=deque, init=False, repr=False)
    _last_intent_at: float = field(default=0.0, init=False, repr=False)
    _last_decision: str = field(default="not_checked", init=False, repr=False)
    _last_error: str | None = field(default=None, init=False, repr=False)
    _last_activity: dict[str, Any] = field(default_factory=lambda: {"status": "disabled"}, init=False, repr=False)
    _quiet_window: tuple[int, int] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.min_significance = max(1, min(int(self.min_significance), 3))
        self.cooldown_seconds = max(0.0, min(float(self.cooldown_seconds), 3600.0))
        self.budget_per_hour = max(1, min(int(self.budget_per_hour), 100))
        self.quiet_hours = self._normalize_quiet_hours(self.quiet_hours)
        self._quiet_window = self._window(self.quiet_hours)

    def consume(self, event: dict[str, Any]) -> dict[str, Any]:
        """Evaluate one untrusted SCREEN_DELTA and never raise to the sensor."""
        try:
            result = self._consume(event)
        except Exception:  # noqa: BLE001 - sensor consumers are isolation boundaries
            with self._lock:
                self._last_decision = "invalid"
                self._last_error = "attention_event_invalid"
            return {"status": "ignored", "reason": "attention_event_invalid"}
        with self._lock:
            self._last_decision = result["status"]
            if result.get("delivered", True):
                self._last_error = None
        return result

    def configure(
        self,
        *,
        dnd: bool | None = None,
        min_significance: int | None = None,
        cooldown_seconds: float | None = None,
        budget_per_hour: int | None = None,
        quiet_hours: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        with self._lock:
            if dnd is not None:
                self.dnd = bool(dnd)
            if min_significance is not None:
                if isinstance(min_significance, bool):
                    raise ValueError("min_significance must be an integer")
                self.min_significance = max(1, min(3, int(min_significance)))
            if cooldown_seconds is not None:
                self.cooldown_seconds = max(0.0, min(3600.0, float(cooldown_seconds)))
            if budget_per_hour is not None:
                if isinstance(budget_per_hour, bool):
                    raise ValueError("budget_per_hour must be an integer")
                self.budget_per_hour = max(1, min(100, int(budget_per_hour)))
            if quiet_hours is not _UNSET:
                self.quiet_hours = self._normalize_quiet_hours(quiet_hours)  # type: ignore[arg-type]
                self._quiet_window = self._window(self.quiet_hours)
            return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            self._trim_budget(time.monotonic())
            return {
                "dnd": self.dnd,
                "min_significance": self.min_significance,
                "cooldown_seconds": self.cooldown_seconds,
                "budget_per_hour": self.budget_per_hour,
                "quiet_hours": self.quiet_hours,
                "quiet_hours_active": self._is_quiet(self._local_now()),
                "intents_last_hour": len(self._intent_times),
                "intent_count": len(self._intents),
                "last_decision": self._last_decision,
                "last_error": self._last_error,
                "last_intent": self._intents[-1] if self._intents else None,
                "activity": dict(self._last_activity),
            }

    def intents(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._intents)

    def _consume(self, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict) or event.get("type") != "SCREEN_DELTA":
            return {"status": "ignored", "reason": "not_screen_delta"}
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("changed") is False:
            return {"status": "ignored", "reason": "screen_delta_not_changed"}
        summary = self._summary(payload.get("summary"))
        if not summary:
            return {"status": "ignored", "reason": "screen_summary_missing"}
        if _PRIVATE.search(summary):
            return {"status": "suppressed", "reason": "screen_summary_private"}
        key = str(event.get("event_id") or hashlib.sha256(summary.encode()).hexdigest())[:200]
        with self._lock:
            if key in self._seen:
                return {"status": "duplicate", "reason": "screen_event_seen"}
            self._seen.append(key)
            score = self._score(payload.get("significance"), summary)
            activity = self._sample_activity()
            self._last_activity = activity
            if activity.get("status") == "verified" and activity.get("user_active"):
                return {"status": "suppressed", "reason": "user_active", "significance": score}
            if self.dnd:
                return {"status": "suppressed", "reason": "dnd_active", "significance": score}
            if self._is_quiet(self._local_now()):
                return {"status": "suppressed", "reason": "quiet_hours_active", "significance": score}
            now = time.monotonic()
            self._trim_budget(now)
            if score < self.min_significance:
                return {"status": "ignored", "reason": "below_salience_threshold", "significance": score}
            if now - self._last_intent_at < self.cooldown_seconds:
                return {"status": "coalesced", "reason": "attention_cooldown_active", "significance": score}
            if len(self._intent_times) >= self.budget_per_hour:
                return {"status": "suppressed", "reason": "proactive_budget_exhausted", "significance": score}
            intent = self._make_intent(event, summary, score)
            self._intents.append(intent)
            self._intent_times.append(now)
            self._last_intent_at = now
        if self.intent_sink is not None:
            try:
                self.intent_sink(intent)
            except Exception:  # noqa: BLE001 - an optional sink must not kill sensing
                with self._lock:
                    self._last_error = "attention_sink_failed"
                return {"status": "proposed", "intent": intent, "delivered": False}
        return {"status": "proposed", "intent": intent, "delivered": True}

    def _sample_activity(self) -> dict[str, Any]:
        if self.activity_provider is None:
            return {"status": "disabled"}
        try:
            result = self.activity_provider()
        except Exception:  # noqa: BLE001 - optional sensor must not break attention
            return {"status": "degraded", "reason": "activity_provider_failed"}
        if not isinstance(result, dict):
            return {"status": "degraded", "reason": "activity_provider_invalid"}
        status = str(result.get("status") or "degraded")[:40]
        bounded: dict[str, Any] = {"status": status}
        if isinstance(result.get("user_active"), bool):
            bounded["user_active"] = result["user_active"]
        for key in ("idle_seconds", "threshold_seconds"):
            value = result.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                bounded[key] = round(max(0.0, min(float(value), 30 * 24 * 3600.0)), 1)
        if isinstance(result.get("foreground_class"), str):
            bounded["foreground_class"] = result["foreground_class"][:120]
        return bounded

    @staticmethod
    def _summary(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").replace("\x00", "")).strip()[:600]

    @staticmethod
    def _score(value: Any, summary: str) -> int:
        base = 0 if isinstance(value, bool) else int(value or 0)
        base = max(0, min(3, base))
        return max(base, 3 if _SALIENT.search(summary) else 0)

    @staticmethod
    def _make_intent(event: dict[str, Any], summary: str, score: int) -> dict[str, Any]:
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "session_id": str(event.get("session_id") or "local")[:200],
            "created_at": _now(),
            "source": "attention_presence",
            "type": "SPEAK_INTENT",
            "priority": int(TurnPriority.PROACTIVE),
            "payload": {
                "topic": "screen_change",
                "reason": "salient_screen_change",
                "summary": summary,
                "significance": score,
                "observed_event_id": str(event.get("event_id") or "")[:200],
                "expires_at": expires.isoformat(),
                "raw_frame_persisted": False,
            },
        }

    def _trim_budget(self, now: float) -> None:
        while self._intent_times and now - self._intent_times[0] >= 3600.0:
            self._intent_times.popleft()

    def _local_now(self) -> datetime:
        value = self.clock() if self.clock is not None else datetime.now().astimezone()
        return value.astimezone() if value.tzinfo is not None else value.replace(tzinfo=datetime.now().astimezone().tzinfo)

    def _is_quiet(self, value: datetime) -> bool:
        if self._quiet_window is None:
            return False
        minute = value.hour * 60 + value.minute
        start, end = self._quiet_window
        return start <= minute < end if start < end else minute >= start or minute < end

    @staticmethod
    def _normalize_quiet_hours(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", value):
            raise ValueError("quiet_hours must use HH:MM-HH:MM")
        start = AttentionPresence._parse_hhmm(value[:5])
        end = AttentionPresence._parse_hhmm(value[6:])
        if start == end:
            raise ValueError("quiet_hours start and end must differ")
        return value

    @staticmethod
    def _window(value: str | None) -> tuple[int, int] | None:
        if value is None:
            return None
        return AttentionPresence._parse_hhmm(value[:5]), AttentionPresence._parse_hhmm(value[6:])

    @staticmethod
    def _parse_hhmm(value: str) -> int:
        hour, minute = (int(part) for part in value.split(":", 1))
        if hour > 23 or minute > 59:
            raise ValueError("quiet_hours must use valid local time")
        return hour * 60 + minute
