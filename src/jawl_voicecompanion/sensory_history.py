"""Bounded local history for text-only audio and visual observations."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
import time
from typing import Any, Callable
from uuid import uuid4

_HOUR = 3600.0
_DAY = 86400.0
_SECRET = re.compile(
    r"\b(password|passwd|passphrase|secret|api[_ -]?key|access[_ -]?token|authorization)\b|"
    r"\u043f\u0430\u0440\u043e\u043b[\u0430-\u044f\u0451]*|\u0441\u0435\u043a\u0440\u0435\u0442[\u0430-\u044f\u0451]*|"
    r"\u0442\u043e\u043a\u0435\u043d[\u0430-\u044f\u0451]*|\u043a\u043b\u044e\u0447\s+api",
    re.I,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_SALIENT = re.compile(r"\b(error|exception|failed|failure|warning|deadline|urgent|important|goal|quest|mission|completed|finished|started|crash|build|commit|task)\b", re.I)


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(float(stamp), tz=timezone.utc).isoformat()


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


class SensoryHistoryStore:
    """One-hour rolling text timeline plus seven-day compact hourly moments."""
    def __init__(self, path: str | os.PathLike[str], *, enabled: bool | Callable[[], bool] = False,
                 recent_seconds: float = _HOUR, retention_seconds: float = 7 * _DAY,
                 max_recent_events: int = 4096, max_moments_per_hour: int = 10,
                 flush_interval_seconds: float = 5, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self._enabled = enabled
        self.recent_seconds = max(60.0, min(float(recent_seconds), _HOUR))
        self.retention_seconds = max(_DAY, min(float(retention_seconds), 14 * _DAY))
        self.max_recent_events = max(64, min(int(max_recent_events), 8192))
        self.max_moments_per_hour = max(3, min(int(max_moments_per_hour), 20))
        self.flush_interval_seconds = max(1.0, min(float(flush_interval_seconds), 60.0))
        self._clock = clock
        self._lock = RLock()
        self._recent: deque[dict[str, Any]] = deque()
        self._hours: dict[str, dict[str, Any]] = {}
        self._last_flush = 0.0
        self._last_error: str | None = None
        self._load()

    def _is_enabled(self) -> bool:
        try:
            return bool(self._enabled() if callable(self._enabled) else self._enabled)
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _key(item: dict[str, Any]) -> tuple[str, str, str]:
        text = re.sub(r"\W+", " ", str(item.get("text") or "").casefold()).strip()
        return str(item.get("modality") or ""), str(item.get("scene_id") or ""), text

    def record(self, modality: str, text: str, *, observed_at: float | str | None = None,
               source: str = "", scene_id: str = "", frame_id: str = "",
               confidence: float | None = None, verified: bool | None = None,
               metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._is_enabled():
            return {"status": "disabled"}
        body = _clean(text)
        if not body:
            return {"status": "ignored", "reason": "empty_text"}
        if _SECRET.search(body) or _EMAIL.search(body):
            return {"status": "suppressed", "reason": "sensitive_text"}
        modality = str(modality or "").strip().lower()[:20]
        if modality not in {"visual", "speech", "music", "sound"}:
            return {"status": "ignored", "reason": "unsupported_modality"}
        now = self._clock()
        stamp = _timestamp(observed_at) or now
        meta = metadata if isinstance(metadata, dict) else {}
        importance = 1
        reasons: list[str] = []
        if modality == "visual" and scene_id:
            importance += 1
            reasons.append("scene_observation")
            if meta.get("scene_changed") is True:
                importance += 2
                reasons.append("scene_change")
        if modality == "speech" and _SALIENT.search(body):
            importance += 2
            reasons.append("salient_speech")
        if modality == "music" and meta.get("music_state") == "music":
            importance += 1
            reasons.append("music_detected")
        if meta.get("user_marked_important") is True:
            importance += 3
            reasons.append("user_marked")
        item = {"event_id": str(uuid4()), "observed_at": _iso(stamp), "timestamp": stamp,
                "modality": modality, "text": body, "source": _clean(source, 100),
                "scene_id": _clean(scene_id, 64), "frame_id": _clean(frame_id, 64),
                "confidence": round(max(0.0, min(1.0, float(confidence))), 3)
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
                "verified": bool(verified) if isinstance(verified, bool) else False,
                "importance": min(8, importance), "importance_reason": ",".join(reasons) or "observation",
                "first_seen_at": _iso(stamp), "last_seen_at": _iso(stamp), "sample_count": 1}
        with self._lock:
            self._prune(now)
            existing = next((event for event in reversed(self._recent)
                             if self._key(event) == self._key(item)
                             and 0 <= stamp - float(event.get("timestamp", stamp)) <= 90), None)
            if existing:
                existing["timestamp"] = stamp
                existing["observed_at"] = _iso(stamp)
                existing["last_seen_at"] = _iso(stamp)
                existing["sample_count"] = min(1_000_000, int(existing.get("sample_count", 1)) + 1)
                self._update_hour(existing, repeated=True)
                status, event_id = "coalesced", existing["event_id"]
            else:
                self._recent.append(item)
                if item["importance"] >= 2:
                    self._update_hour(item, repeated=False)
                status, event_id = "recorded", item["event_id"]
            self._prune(now)
            if now - self._last_flush >= self.flush_interval_seconds:
                self._flush(now)
        return {"status": status, "event_id": event_id, "importance": item["importance"]}

    def _update_hour(self, item: dict[str, Any], *, repeated: bool) -> None:
        stamp = float(item.get("timestamp") or self._clock())
        key = _iso(stamp - stamp % _HOUR)
        bucket = self._hours.setdefault(key, {"hour_start": key, "event_count": 0, "moments": []})
        if not repeated:
            bucket["event_count"] = int(bucket.get("event_count", 0)) + 1
        fields = ("event_id", "observed_at", "last_seen_at", "modality", "text", "source",
                  "scene_id", "confidence", "verified", "importance", "importance_reason", "sample_count")
        candidate = {name: item[name] for name in fields if item.get(name) is not None}
        moments = bucket.setdefault("moments", [])
        existing = next((entry for entry in moments if entry.get("event_id") == item.get("event_id")), None)
        if existing:
            existing.update(candidate)
        else:
            moments.append(candidate)
        moments.sort(key=lambda entry: (int(entry.get("importance", 0)), entry.get("observed_at", "")), reverse=True)
        del moments[self.max_moments_per_hour:]

    def _prune(self, now: float) -> None:
        cutoff = now - self.recent_seconds
        while self._recent and float(self._recent[0].get("timestamp", 0)) < cutoff:
            self._recent.popleft()
        while len(self._recent) > self.max_recent_events:
            self._recent.popleft()
        week_cutoff = now - self.retention_seconds
        self._hours = {key: bucket for key, bucket in self._hours.items()
                       if (_timestamp(bucket.get("hour_start")) or 0) >= week_cutoff}

    def _load(self) -> None:
        try:
            if not self.path.is_file() or self.path.stat().st_size > 8 * 1024 * 1024:
                return
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                return
            for event in payload.get("recent_events", [])[-self.max_recent_events:]:
                if not isinstance(event, dict) or event.get("modality") not in {"visual", "speech", "music", "sound"}:
                    continue
                stamp = _timestamp(event.get("timestamp") or event.get("observed_at"))
                text = _clean(event.get("text"))
                if stamp is not None and text:
                    normalized = dict(event); normalized["timestamp"] = stamp; normalized["text"] = text
                    self._recent.append(normalized)
            for bucket in payload.get("hourly_summaries", [])[-200:]:
                if isinstance(bucket, dict) and isinstance(bucket.get("hour_start"), str):
                    self._hours[bucket["hour_start"]] = {"hour_start": bucket["hour_start"],
                        "event_count": max(0, int(bucket.get("event_count", 0) or 0)),
                        "moments": [dict(moment) for moment in bucket.get("moments", [])[:self.max_moments_per_hour]
                                    if isinstance(moment, dict) and _clean(moment.get("text"))]}
            self._prune(self._clock())
        except (OSError, ValueError, TypeError):
            self._last_error = "history_file_unreadable"

    def _payload(self, now: float) -> dict[str, Any]:
        self._prune(now)
        recent = []
        for event in self._recent:
            value = dict(event); value.pop("timestamp", None); recent.append(value)
        return {"schema_version": 1, "updated_at": _iso(now),
                "policy": {"recent_window_seconds": self.recent_seconds,
                           "compact_retention_days": round(self.retention_seconds / _DAY, 1),
                           "raw_audio_persisted": False, "raw_video_persisted": False},
                "recent_events": recent,
                "hourly_summaries": sorted(self._hours.values(), key=lambda bucket: bucket["hour_start"])}

    def _flush(self, now: float) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False,
                                             dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp") as stream:
                temp = Path(stream.name)
                json.dump(self._payload(now), stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.path)
            self._last_flush = now; self._last_error = None
        except OSError as exc:
            self._last_error = f"history_write_failed:{type(exc).__name__}"
            try:
                if "temp" in locals(): temp.unlink(missing_ok=True)
            except OSError:
                pass

    def flush(self) -> dict[str, Any]:
        with self._lock:
            self._flush(self._clock())
            return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            self._prune(self._clock())
            return {"enabled": self._is_enabled(), "path": str(self.path),
                    "recent_window_seconds": self.recent_seconds, "recent_event_count": len(self._recent),
                    "hour_bucket_count": len(self._hours),
                    "compact_moment_count": sum(len(bucket.get("moments", [])) for bucket in self._hours.values()),
                    "raw_audio_persisted": False, "raw_video_persisted": False,
                    "last_error": self._last_error}

    def context_text(self, *, seconds: float = _HOUR, include_week: bool = False,
                     focus_seconds_ago: float | None = None, focus_window_seconds: float = 60.0,
                     max_chars: int = 6000) -> str:
        now = self._clock(); lookback = max(60.0, min(float(seconds), 7 * _DAY)); cutoff = now - lookback
        focus = None
        if focus_seconds_ago is not None:
            try:
                candidate = float(focus_seconds_ago)
                if 0.0 <= candidate <= 7 * _DAY:
                    focus = candidate
            except (TypeError, ValueError):
                focus = None
        radius = max(10.0, min(float(focus_window_seconds), 15 * 60.0)) / 2.0
        with self._lock:
            self._prune(now)
            if focus is not None and focus + radius <= self.recent_seconds:
                start = now - focus - radius
                end = now - focus + radius
                selected = [dict(event) for event in self._recent
                            if start <= float(event.get("timestamp", 0)) <= end]
            elif focus is not None and (include_week or lookback > self.recent_seconds):
                start = now - focus - radius
                end = now - focus + radius
                selected = [moment for bucket in self._hours.values() for moment in bucket.get("moments", [])
                            if start <= (_timestamp(moment.get("observed_at")) or 0) <= end]
                selected.sort(key=lambda item: item.get("observed_at", ""))
            elif include_week or lookback > self.recent_seconds:
                selected = [moment for bucket in self._hours.values() for moment in bucket.get("moments", [])
                            if (_timestamp(moment.get("observed_at")) or 0) >= cutoff]
                selected.sort(key=lambda item: item.get("observed_at", ""))
            else:
                selected = [dict(event) for event in self._recent if event.get("timestamp", 0) >= cutoff]
        if not selected:
            return "No sensory observations in the selected period."
        lines = []
        for item in selected:
            parts = [str(item.get("scene_id") or ""), str(item.get("source") or "")]
            if item.get("verified") is False: parts.append("unverified model observation")
            details = ", ".join(part for part in parts if part)
            lines.append(f"{item.get('observed_at', '')} {str(item.get('modality', 'unknown')).upper()} "
                         f"{f'({details}) ' if details else ''}{item.get('text', '')}")
        if focus is None:
            header = f"SENSORY HISTORY: last {int(lookback // 60)} min; text only, no stored raw audio/video.\n"
        else:
            header = (f"SENSORY HISTORY: observations around {focus / 60:g} min ago "
                      f"(±{radius:g}s); text only, no stored raw audio/video.\n")
        output = header + "\n".join(lines)
        if len(output) <= max_chars: return output
        keep = max(1, min(len(lines), int(max_chars / max(180, len(output) / len(lines)))))
        if keep < len(lines):
            half = max(1, keep // 2); tail = max(0, keep - half)
            middle = ["... intermediate observations compacted ..."] if keep > 2 else []
            lines = lines[:half] + middle + (lines[-tail:] if tail else [])
        return (header + "\n".join(lines))[:max_chars]

    def clear(self) -> dict[str, Any]:
        with self._lock:
            events, hours = len(self._recent), len(self._hours)
            self._recent.clear(); self._hours.clear(); self._flush(self._clock())
            if self.path.exists():
                try: self.path.unlink()
                except OSError: self._last_error = "history_clear_failed"
            return {"status": "cleared", "recent_events": events, "hour_buckets": hours}


__all__ = ["SensoryHistoryStore"]
