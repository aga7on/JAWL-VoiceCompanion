"""Voice commentary on salient screen events (D4 initiative lane).

Owner requirement (2026-11-10): the brain never speaks about what happens on
the screen although perception already watches it. Screen events do not wake
the brain by themselves and user turns only carry the ready perception draft,
so the commentary lane below closes the gap architecturally, not by prompt:

* ``ScreenDeltaWatcher`` already publishes bounded screen events carrying a
  text ``description`` (no new capture is paid by the scheduler);
* on a fresh event the scheduler submits one bounded observation turn to the
  gateway — JAWL itself decides whether the event deserves a spoken comment
  and may answer exactly ``тишина`` to decline;
* accepted comments are delivered through :class:`ProactiveFeed`
  (``deliver_direct``), which reuses the existing rate limits, idle gates,
  learned feedback (useful/noise) and the desktop's polite playback rules.

Anti-spam is a hard requirement: the fillers the owner rejected («Работаю»,
«Проверка») showed that an ungated initiative lane is worse than silence.
Every tick therefore checks enabled, mute/quiet, idle, min gap, hourly cap,
and one in-flight brain query at a time.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque
from typing import Any, Callable

from .proactive import _sanitize_delivery, _timestamp

__all__ = ["ScreenCommentaryScheduler"]

_GREATEST_EVENT_LIMIT = 3
_PROMPT_TEMPLATE = (
    "[НАБЛЮДЕНИЕ ЭКРАНА]\n{observation}\n\n"
    "Это свежее изменение на экране пользователя. Реши по нему, стоит ли "
    "КОРОТКО прокомментировать вслух. Комментарий уместен только тогда, когда "
    "он полезен или срочен: продолжение недавней темы, готовый результат, "
    "важное сообщение на экране, прямое следствие последнего поручения. "
    "Не комментируй рутину, смену окон, собственную работу пользователя без "
    "запроса и всё, что не изменилось.\n"
    "Если комментировать не стоит — ответь ровно одним словом: тишина\n"
    "Если стоит — ответь одной-двумя короткими простыми фразами по-русски, "
    "без разметки, без приветствий, без напоминаний о своих возможностях."
)
_SILENCE_RE = re.compile(r"^[\W«»]*(?:тиш[іi]на)[\W«»]*$", re.IGNORECASE)
_MAX_TEXT = 2000


class ScreenCommentaryScheduler:
    """Poll-driven trigger that lets JAWL vote on speaking one screen event."""

    def __init__(
        self,
        watcher_getter: Callable[[], Any],
        gateway: Any,
        feed: Any | None = None,
        *,
        enabled: bool = True,
        idle_after_turn_s: float = 90.0,
        min_gap_s: float = 600.0,
        max_per_hour: int = 2,
        max_description_chars: int = 1600,
        sensory_motivation: Any | None = None,
    ) -> None:
        self._watcher_getter = watcher_getter
        self.gateway = gateway
        self.feed = feed
        self._enabled = bool(enabled)
        self.min_gap_s = max(0.0, float(min_gap_s))
        self.max_per_hour = max(1, int(max_per_hour))
        self.idle_after_turn_s = max(0.0, float(idle_after_turn_s))
        self._max_description_chars = max(1, int(max_description_chars))
        self.enabled = self._enabled
        self.last_error = ""
        self._inflight: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_commentary_at = 0.0
        self._delivery_times: deque[float] = deque(maxlen=32)
        self._last_event_id = ""
        self._last_event_taken = 0.0
        self._delivered_count = 0
        self._suppressed_silence = 0
        self._suppressed_rate = 0
        self._suppressed_motivation = 0
        self._sensory_motivation = sensory_motivation
        self._muted_source = False

    # ------------------------------------------------------------- settings

    def update_settings(self, *, enabled: bool | None = None) -> None:
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be boolean")
            self._enabled = enabled
            self.enabled = enabled

    def state(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        with self._lock:
            inflight = bool(self._inflight and self._inflight.is_alive())
            last = self._last_commentary_at
        payload = {
            "enabled": self._enabled,
            "in_flight": inflight,
            "last_commentary_at": last or None,
            "last_age_s": round(now - last, 1) if last else None,
            "deliveries": self._delivered_count,
            "suppressed_silence": self._suppressed_silence,
            "suppressed_rate": self._suppressed_rate,
            "suppressed_motivation": self._suppressed_motivation,
            "last_error": self.last_error[:200],
        }
        sm = self._sensory_motivation
        if sm is not None and hasattr(sm, "state"):
            try:
                payload["sensory_motivation"] = sm.state(now)
            except Exception:  # noqa: BLE001
                payload["sensory_motivation"] = {"status": "error"}
        return payload

    def join_inflight(self, timeout: float = 5.0) -> bool:
        """Await the in-flight commentary turn (tests and graceful stop)."""
        with self._lock:
            thread = self._inflight
        if thread is None:
            return True
        thread.join(max(0.0, float(timeout)))
        return not thread.is_alive()

    # ---------------------------------------------------------------- tick

    def tick(self, now: float | None = None) -> dict[str, Any]:
        """Check gates; at most start one brain query and return the state."""
        if not self._enabled:
            return self.state(now)
        watcher = self._watcher_getter()
        if watcher is None:
            return self.state(now)
        event = self._fresh_event(watcher)
        if event is None:
            return self.state(now)
        with self._lock:
            if self._inflight is not None and self._inflight.is_alive():
                self._suppressed_rate += 1
                return self.state(now)
        if self.feed is not None:
            try:
                muted = bool(getattr(self.feed, "muted", False))
                if not muted and hasattr(self.feed, "_quiet_until"):
                    muted = float(self.feed._quiet_until) > time.time()
            except Exception:  # noqa: BLE001
                muted = False
            if muted:
                self._suppressed_rate += 1
                return self.state(now)
        if self._rate_blocked(now):
            self._suppressed_rate += 1
            return self.state(now)
        if not self._conversation_idle(now):
            self._suppressed_rate += 1
            return self.state(now)

        observation = self._observation_text(watcher)
        if not observation:
            self._suppressed_rate += 1
            with self._lock:
                self._last_event_id = event.get("event_id", self._last_event_id)
            return self.state(now)
        sm = self._sensory_motivation
        if sm is not None and hasattr(sm, "observe"):
            try:
                signal = sm.observe(observation, now=time.time() if now is None else float(now))
            except Exception:  # noqa: BLE001
                signal = None
            # Motivation rises on novelty; trigger a proactive brain turn only when
            # it crosses threshold (or is explicitly triggered). Familiar/low-interest
            # observations are consumed silently (motivation decays) to avoid spam.
            if signal is not None and not getattr(signal, "triggered", False):
                with self._lock:
                    self._suppressed_motivation += 1
                    self._last_event_id = event.get("event_id", self._last_event_id)
                return self.state(now)
        seen_event = self._last_event_id
        prompt = _PROMPT_TEMPLATE.format(observation=observation[: self._max_description_chars])
        thread = threading.Thread(
            target=self._commentary_turn,
            args=(prompt, seen_event, observation),
            name="screen-commentary",
            daemon=True,
        )
        self._inflight = thread
        thread.start()
        return self.state(now)

    # ------------------------------------------------------------ internals

    def _fresh_event(self, watcher: Any) -> dict[str, Any] | None:
        try:
            events = list(watcher.events())[-8:]
        except Exception:  # noqa: BLE001 — degraded watcher must not break polls
            return None
        for event in reversed(events):
            eid = str(event.get("event_id") or "")
            if not eid or eid == self._last_event_id:
                continue
            description = str(event.get("description") or "").strip()
            if not description:
                continue
            stamp = _timestamp(str(event.get("created_at") or ""))
            return {"event_id": eid, "description": description, "created_at": stamp}
        return None

    def _observation_text(self, watcher: Any) -> str:
        try:
            events = list(watcher.events())[-12:]
        except Exception:  # noqa: BLE001
            return ""
        fresh: list[str] = []
        for event in reversed(events):
            description = str(event.get("description") or "").strip()
            if not description:
                continue
            fresh.append(description)
            if len(fresh) >= _GREATEST_EVENT_LIMIT:
                break
        return "\n".join(reversed(fresh))[: self._max_description_chars]

    def _rate_blocked(self, now: float | None) -> bool:
        now = time.time() if now is None else float(now)
        if now - self._last_commentary_at < self.min_gap_s:
            return True
        if self._delivery_times and now - self._delivery_times[0] < 3600.0:
            if sum(1 for ts in self._delivery_times if now - ts < 3600.0) >= self.max_per_hour:
                return True
        return False

    def _conversation_idle(self, now: float | None) -> bool:
        """Idle gate: no recent companion turn, so commentary cannot talk over."""
        history = getattr(self.gateway, "history_store", None)
        if history is None:
            return True
        try:
            turns = history.turns(limit=1)
        except Exception:  # noqa: BLE001
            return True
        if not turns:
            return True
        stamp = _timestamp(str(turns[-1].get("created_at") or ""))
        if not stamp:
            return True
        return (time.time() if now is None else float(now)) - stamp >= self.idle_after_turn_s

    def _commentary_turn(self, prompt: str, event_id: str, observation: str) -> None:
        text = ""
        admitted = True
        try:
            envelope = self.gateway.handle_text(
                prompt,
                session_id="local",
                history_user_text=prompt[:800],
            )
            if isinstance(envelope, dict):
                admitted = bool(envelope.get("admitted", True))
                text = str(envelope.get("text") or "").strip()
        except Exception as exc:  # noqa: BLE001 — initiative must never crash
            self.last_error = f"{type(exc).__name__}: {exc}"[:240]
        with self._lock:
            self._last_event_id = event_id
            self._last_event_taken = time.time()
        if not admitted or not text:
            with self._lock:
                self._suppressed_silence += 1
            return
        if _SILENCE_RE.match(text):
            with self._lock:
                self._suppressed_silence += 1
            return
        if _is_noise_answer(text):
            with self._lock:
                self._suppressed_silence += 1
            return
        with self._lock:
            self._last_commentary_at = time.time()
        if self.feed is None:
            return
        try:
            self.feed.deliver_direct(text[:_MAX_TEXT], source="screen_commentary")
            self._delivered_count += 1
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"deliver: {type(exc).__name__}: {exc}"[:240]


def _is_noise_answer(text: str) -> bool:
    """Reject filler-rate answers («Работаю», «Готово») the owner rejected."""
    clean = _sanitize_delivery(str(text or ""))
    if clean is None:
        return True
    lowered = clean.casefold().strip(" .!?\u2026«»\"'")
    if lowered in {"готово", "работаю", "хорошо", "ок", "окей", "проверка", "понял", "поняла"}:
        return True
    words = len(re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", lowered))
    if words <= 1 and not re.search(r"[.!?]", lowered):
        return True
    return False
