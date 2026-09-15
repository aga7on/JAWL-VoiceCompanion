"""Bounded JAWL initiative feed with an idle gate and a silence switch.

JAWL heartbeats may speak on their own; those messages land in the shared
chat history without a Companion turn. This feed surfaces them deliberately:
new initiative is delivered only while the conversation is idle, inside the
learned active hours, rate limited, and never while the silence switch or a
feedback cooldown is on. Everything else waits in a bounded queue and is
delivered later, oldest first.

The EOPA-lite layer adds two deterministic gates on top of the idle check:
activity windows learned from the conversation history (an hour counts as
active when turns happened there on at least two distinct days) and user
feedback ("useful" / "noise") that opens an exponential quiet window.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

_POLL_INTERVAL_S = 12.0
_IDLE_AFTER_TURN_S = 45.0
_ECHO_HISTORY_TURNS = 8
_ACTIVITY_TURNS = 400
_ACTIVITY_DAYS = 14
_ACTIVITY_CACHE_S = 600.0
_DUPLICATE_WINDOW_S = 24 * 3600.0
_DELIVERED_TEXT_LIMIT = 60


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())[:1200]


def _timestamp(value: str) -> float:
    import datetime

    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.datetime.fromisoformat(raw).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(raw[:19], fmt).replace(
                tzinfo=datetime.timezone.utc
            ).timestamp()
        except ValueError:
            continue
    return 0.0


class ProactiveFeed:
    """Surface JAWL messages that are not replies to a Companion turn."""

    def __init__(
        self,
        client: Any,
        *,
        history: Any | None = None,
        poll_interval_s: float = _POLL_INTERVAL_S,
        idle_after_turn_s: float = _IDLE_AFTER_TURN_S,
        min_gap_s: float = 300.0,
        max_per_hour: int = 6,
        queue_limit: int = 20,
        delivered_limit: int = 50,
        state_path: str | Path | None = None,
        quiet_base_s: float = 1800.0,
        quiet_max_s: float = 4 * 3600.0,
    ) -> None:
        self.client = client
        self.history = history
        self.poll_interval_s = max(1.0, float(poll_interval_s))
        self.idle_after_turn_s = max(0.0, float(idle_after_turn_s))
        self.min_gap_s = max(0.0, float(min_gap_s))
        self.max_per_hour = max(1, int(max_per_hour))
        self.queue_limit = max(1, int(queue_limit))
        self.delivered_limit = max(1, int(delivered_limit))
        self.state_path = Path(state_path) if state_path else None
        self.quiet_base_s = max(0.0, float(quiet_base_s))
        self.quiet_max_s = max(self.quiet_base_s, float(quiet_max_s))
        self.muted = False
        self.speak = True
        self.last_error = ""
        self._seen: deque[str] = deque(maxlen=400)
        self._seen_set: set[str] = set()
        self._seeded = False
        self._last_poll = 0.0
        self._last_delivery = 0.0
        self._delivery_times: deque[float] = deque(maxlen=64)
        self._queue: list[dict[str, Any]] = []
        self._delivered: list[dict[str, Any]] = []
        self._delivered_texts: deque[tuple[str, float]] = deque(maxlen=_DELIVERED_TEXT_LIMIT)
        self._quiet_until = 0.0
        self._noise_streak = 0
        self._suppressed_duplicates = 0
        self._activity_cache: tuple[float, set[int]] | None = None
        self._load_state()

    def update_settings(self, *, muted: bool | None = None, speak: bool | None = None) -> None:
        if muted is not None:
            if not isinstance(muted, bool):
                raise ValueError("muted must be boolean")
            self.muted = muted
        if speak is not None:
            if not isinstance(speak, bool):
                raise ValueError("speak must be boolean")

    def state(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        return {
            "configured": True,
            "muted": self.muted,
            "speak": self.speak,
            "queued": list(self._queue),
            "delivered": list(self._delivered[-self.delivered_limit:])[-20:],
            "delivered_last_hour": sum(1 for ts in self._delivery_times if now - ts < 3600.0),
            "last_error": self.last_error[:240],
            "poll_age_s": max(0.0, round(now - self._last_poll, 1)) if self._last_poll else None,
            "quiet_until": self._quiet_until,
            "quiet_for_s": max(0.0, round(self._quiet_until - now, 1)) if self._quiet_until > now else 0.0,
            "noise_streak": self._noise_streak,
            "suppressed_duplicates": self._suppressed_duplicates,
            "active_hours": sorted(self._active_hours(now)) if self._activity_cache else [],
        }

    def poll_state(self) -> dict[str, Any]:
        self.poll()
        return self.state()

    def note_feedback(self, item_id: str, verdict: str) -> dict[str, Any]:
        """Apply explicit user feedback to the delivery gate."""
        clean_id = str(item_id or "").strip()[:64]
        if not clean_id:
            raise ValueError("item_id is required")
        if verdict not in {"useful", "noise"}:
            raise ValueError("verdict must be useful or noise")
        item = next((entry for entry in self._delivered if entry.get("id") == clean_id), None)
        if item is None:
            raise ValueError("delivered item was not found")
        item["feedback"] = verdict
        now = time.time()
        if verdict == "noise":
            self._noise_streak += 1
            window = min(self.quiet_base_s * (2 ** (self._noise_streak - 1)), self.quiet_max_s)
            self._quiet_until = max(self._quiet_until, now + window)
        else:
            self._noise_streak = 0
            self._quiet_until = 0.0
        self._save_state()
        return {"ok": True, "feedback": verdict, **self.state(now)}

    def poll(self, now: float | None = None) -> list[dict[str, Any]]:
        """Fetch new JAWL history rows, queue or deliver them, drain the queue."""
        now = time.time() if now is None else float(now)
        if now - self._last_poll < self.poll_interval_s:
            return []
        self._last_poll = now
        try:
            rows = self.client.chat_history(limit=50)
        except Exception as exc:  # noqa: BLE001 - the feed must never break the plane
            self.last_error = f"{type(exc).__name__}: {exc}"[:240]
            return []
        self.last_error = ""
        echoes = self._echo_texts()
        for row in rows:
            sender = str(row.get("sender", ""))
            text = str(row.get("text", "")).strip()
            if not text or sender.strip().lower() == "user":
                continue
            key = hashlib.sha1(
                f"{row.get('time', '')}|{text[:400]}".encode("utf-8", "replace")
            ).hexdigest()[:16]
            if key in self._seen_set:
                continue
            self._remember(key)
            if not self._seeded:
                continue
            if self._is_echo(text, echoes):
                continue
            if self._is_duplicate(text, now):
                self._suppressed_duplicates += 1
                continue
            self._enqueue({"id": key, "time": str(row.get("time", ""))[:40], "text": text[:2000], "queued_at": now})
        self._seeded = True
        return self._drain(now)

    def _remember(self, key: str) -> None:
        if len(self._seen) == self._seen.maxlen:
            oldest = self._seen[0]
            self._seen_set.discard(oldest)
        self._seen.append(key)
        self._seen_set.add(key)

    def _echo_texts(self) -> set[str]:
        echoes: set[str] = set()
        if self.history is None:
            return echoes
        try:
            turns = self.history.turns(limit=_ECHO_HISTORY_TURNS)
        except Exception:  # noqa: BLE001
            return echoes
        for turn in turns:
            response = turn.get("response")
            if isinstance(response, dict):
                echoes.add(_normalize(str(response.get("text", ""))))
        return echoes

    def _is_echo(self, text: str, echoes: set[str]) -> bool:
        normalized = _normalize(text)
        if not normalized:
            return True
        for echo in echoes:
            if echo and (echo.startswith(normalized[:400]) or normalized.startswith(echo[:400])):
                return True
        return False

    def _is_duplicate(self, text: str, now: float) -> bool:
        normalized = _normalize(text)[:200]
        if not normalized:
            return True
        for previous, ts in self._delivered_texts:
            if previous == normalized and now - ts < _DUPLICATE_WINDOW_S:
                return True
        return False

    def _enqueue(self, item: dict[str, Any]) -> None:
        self._queue.append(item)
        if len(self._queue) > self.queue_limit:
            del self._queue[: len(self._queue) - self.queue_limit]
        self._save_state()

    def _idle(self, now: float) -> bool:
        if self.history is None:
            return True
        try:
            turns = self.history.turns(limit=1)
        except Exception:  # noqa: BLE001
            return True
        if not turns:
            return True
        age = now - _timestamp(str(turns[-1].get("created_at", "")))
        return age >= self.idle_after_turn_s

    def _active_hours(self, now: float) -> set[int]:
        """Hours of day with conversation on >= 2 distinct days in the window."""
        cached = self._activity_cache
        if cached is not None and now - cached[0] < _ACTIVITY_CACHE_S:
            return cached[1]
        hours: set[int] = set()
        days: dict[int, set[str]] = {}
        if self.history is not None:
            try:
                turns = self.history.turns(limit=_ACTIVITY_TURNS)
            except Exception:  # noqa: BLE001
                turns = []
            for turn in turns:
                stamp = _timestamp(str(turn.get("created_at", "")))
                if not stamp or now - stamp > _ACTIVITY_DAYS * 86400.0:
                    continue
                import datetime

                moment = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc)
                days.setdefault(moment.hour, set()).add(moment.strftime("%Y-%m-%d"))
        hours = {hour for hour, seen in days.items() if len(seen) >= 2}
        self._activity_cache = (now, hours)
        return hours

    def _in_active_hour(self, now: float) -> bool:
        hours = self._active_hours(now)
        if not hours:
            return True  # no learned rhythm yet: do not block
        import datetime

        return datetime.datetime.fromtimestamp(now, datetime.timezone.utc).hour in hours

    def _drain(self, now: float) -> list[dict[str, Any]]:
        delivered: list[dict[str, Any]] = []
        if self.muted or now < self._quiet_until:
            return delivered
        while self._queue:
            if not self._idle(now) or not self._in_active_hour(now):
                break
            if now - self._last_delivery < self.min_gap_s and self._delivery_times:
                break
            recent = sum(1 for ts in self._delivery_times if now - ts < 3600.0)
            if recent >= self.max_per_hour:
                break
            item = self._queue.pop(0)
            item = {**item, "speak": self.speak, "feedback": None}
            self._delivered.append(item)
            self._delivered_texts.append((_normalize(item.get("text", ""))[:200], now))
            self._delivery_times.append(now)
            self._last_delivery = now
            delivered.append(item)
        if delivered:
            self._save_state()
        return delivered

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        try:
            self._quiet_until = float(payload.get("quiet_until") or 0.0)
            self._noise_streak = int(payload.get("noise_streak") or 0)
        except (TypeError, ValueError):
            self._quiet_until = 0.0
            self._noise_streak = 0
        for entry in payload.get("delivered_texts") or []:
            if not isinstance(entry, list) or len(entry) != 2:
                continue
            text, ts = entry
            try:
                self._delivered_texts.append((str(text)[:200], float(ts)))
            except (TypeError, ValueError):
                continue
        for item in payload.get("queue") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()[:2000]
            if not text:
                continue
            self._queue.append({
                "id": str(item.get("id") or "")[:64] or hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16],
                "time": str(item.get("time") or "")[:40],
                "text": text,
                "queued_at": float(item.get("queued_at") or 0.0),
            })

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        payload = {
            "quiet_until": self._quiet_until,
            "noise_streak": self._noise_streak,
            "delivered_texts": [[text, ts] for text, ts in self._delivered_texts],
            "queue": [dict(item) for item in self._queue],
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8",
            )
        except OSError:
            pass
