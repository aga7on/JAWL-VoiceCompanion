"""Sliding-window fusion of perception channels into one observation.

The companion senses the world through independent asynchronous lanes (VLM
screen captions, active-window titles, music state, speech). The brain should
receive ONE combined observation instead of a stream of per-sensor fragments:
this bounded assembler keeps the freshest text per channel (with per-channel
TTL), plus a short visual-event window distinct from the current screen caption,
and renders them as a single Russian summary. No LLM here: deterministic
composition keeps the transport cheap; an LLM composer can replace the renderer
later.
"""

from __future__ import annotations

import time
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

_TTL_SECONDS = {
    "screen": 90.0,
    "window": 120.0,
    "music": 240.0,
    "music_candidate": 30.0,
    "speech": 300.0,
    "eg2": 60.0,
    "media": 300.0,
    "sound": 120.0,
    "audio_description": 60.0,
    "audio_candidates": 60.0,
    "audio_event_candidates": 30.0,
    "eg2_media": 120.0,
    "ocr": 120.0,
    "voice_delivery": 20.0,
}
_NOW_TTL = {
    "screen": 5.0,
    "media": 5.0,
    "sound": 5.0,
    # Live music events are refreshed by the rolling loopback detector; don't
    # let a stopped track remain in the current-scene prompt for four minutes.
    "music": 20.0,
    "music_candidate": 12.0,
    # Captions are independent of the music-presence detector and expire on
    # the same short live horizon as the underlying audio clip.
    "audio_description": 20.0,
    "audio_candidates": 20.0,
    "audio_event_candidates": 12.0,
    # System-audio transcript is useful to a live co-watching turn, but must
    # disappear quickly once its segment is no longer current.
    "speech": 20.0,
    "ocr": 5.0,
    "voice_delivery": 12.0,
}
# Live turns carry evidence per channel, separate from the legacy 1200-char
# text summary. Keep useful transcript/detail without allowing unbounded text.
_CHANNEL_TEXT_LIMITS = {
    "screen": 1000,
    "window": 2000,
    "music": 800,
    "music_candidate": 320,
    "speech": 2400,
    "eg2": 1000,
    "media": 1200,
    "sound": 800,
    "audio_description": 1600,
    "audio_candidates": 1200,
    "audio_event_candidates": 900,
    "eg2_media": 1000,
    "ocr": 2400,
    "voice_delivery": 500,
}
_VISUAL_EVENT_TTL_SECONDS = 15.0
_MAX_VISUAL_EVENTS = 5
_MAX_RENDERED_VISUAL_EVENTS = 4
_LABELS = {
    "window": "Окно",
    "music": "Звук",
    "music_candidate": "Слабый аудиосигнал",
    "speech": "Слышно",
    "eg2": "EG2",
    "media": "Медиа",
    "audio_description": "Описание аудио",
    "audio_candidates": "Гипотезы аудио",
    "ocr": "OCR",
}
_LABELS["audio_event_candidates"] = "YAMNet event hypotheses (unverified)"
_LABELS["sound"] = "Звук"
_LABELS["voice_delivery"] = "\u041f\u043e\u0434\u0430\u0447\u0430 \u0433\u043e\u043b\u043e\u0441\u0430"


def _bounded_channel_text(kind: str, value: Any) -> str:
    limit = _CHANNEL_TEXT_LIMITS.get(str(kind), 600)
    return str(value or "").replace("\x00", "").strip()[:limit]


def _audio_candidates_have_music_support(
    items: dict[str, tuple[str, float, dict[str, Any]]], moment: float,
) -> bool:
    """Require fresh YAMNet music evidence overlapping the candidate clip."""
    candidates = items.get("audio_candidates")
    music = items.get("music")
    if candidates is None or music is None:
        return False
    candidate_text, candidate_stamp, candidate_meta = candidates
    music_text, music_stamp, music_meta = music
    del candidate_text, music_text
    candidate_ttl = _NOW_TTL["audio_candidates"]
    music_ttl = _NOW_TTL["music"]
    if moment - candidate_stamp > candidate_ttl or moment - music_stamp > music_ttl:
        return False
    if candidate_meta.get("possibly_outdated") or music_meta.get("possibly_outdated"):
        return False
    if music_meta.get("music_state") != "music":
        return False
    try:
        candidate_start = float(candidate_meta["segment_started_monotonic"])
        candidate_end = float(candidate_meta["segment_ended_monotonic"])
        music_start = float(music_meta["segment_started_monotonic"])
        music_end = float(music_meta["segment_ended_monotonic"])
    except (KeyError, TypeError, ValueError):
        return False
    return max(candidate_start, music_start) < min(candidate_end, music_end)


@dataclass
class PerceptionFusion:
    """Bounded latest-value store, short visual timeline and one renderer."""

    _items: dict[str, tuple[str, float, dict[str, Any]]] = field(default_factory=dict, init=False, repr=False)
    _visual_events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=_MAX_VISUAL_EVENTS), init=False, repr=False
    )
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    media_buffer: Any | None = field(default=None, init=True, repr=False)
    eg2: Any | None = field(default=None, init=True, repr=False)
    describer: Any | None = field(default=None, init=True, repr=False)
    include_eg2_media_in_scene: bool = field(default=True, init=True)
    history_store: Any | None = field(default=None, init=True, repr=False)
    prompt_snapshot_path: Path | None = field(default=None, init=True, repr=False)
    _export_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _history_status_counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _history_write_errors: int = field(default=0, init=False, repr=False)
    _history_last_status: str | None = field(default=None, init=False, repr=False)
    _history_last_modality: str | None = field(default=None, init=False, repr=False)

    def _record_history(self, modality: str, text: str, **kwargs: Any) -> None:
        store = self.history_store
        if store is None:
            return
        try:
            result = store.record(modality, text, **kwargs)
            status = str(result.get("status") or "unknown") if isinstance(result, dict) else "unknown"
        except Exception:  # noqa: BLE001 - durable history must not block current perception
            status = "error"
        with self._lock:
            key = f"{modality}:{status}"[:64]
            self._history_status_counts[key] = min(2_147_483_647, self._history_status_counts.get(key, 0) + 1)
            if status == "error":
                self._history_write_errors = min(2_147_483_647, self._history_write_errors + 1)
            self._history_last_status = status
            self._history_last_modality = str(modality)[:20]

    def history_health(self) -> dict[str, Any]:
        """Return text-free persistence telemetry for the optional sensory archive."""
        store = self.history_store
        persistence: dict[str, Any] = {
            "enabled": None,
            "last_flush_age_seconds": None,
            "last_error": None,
            "last_error_stage": None,
            "load_blocked": None,
        }
        state_fn = getattr(store, "state", None) if store is not None else None
        if callable(state_fn):
            try:
                state = state_fn()
                if isinstance(state, dict):
                    persistence = {
                        "enabled": state.get("enabled") is True,
                        "last_flush_age_seconds": state.get("last_flush_age_seconds"),
                        "last_error": state.get("last_error"),
                        "last_error_stage": state.get("last_error_stage"),
                        "load_blocked": state.get("load_blocked") is True,
                    }
            except Exception:  # noqa: BLE001 - telemetry must not affect perception
                persistence["last_error"] = "telemetry_unavailable"
                persistence["last_error_stage"] = "telemetry"
        with self._lock:
            return {
                "configured": store is not None,
                "writes": dict(self._history_status_counts),
                "write_errors": self._history_write_errors,
                "last_status": self._history_last_status,
                "last_modality": self._history_last_modality,
                "persistence": persistence,
            }

    def _export_prompt_snapshot(self) -> None:
        if self.prompt_snapshot_path is None:
            return
        from .perception_packet import make_packet, save_packet
        try:
            with self._export_lock:
                save_packet(self.prompt_snapshot_path, make_packet(self.compose_snapshot(include_visual_history=False)))
        except (OSError, ValueError, TypeError):
            pass  # Live perception remains available if the disk handoff fails.

    def note(
        self,
        kind: str,
        text: str,
        *,
        now: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        channel = str(kind)[:40]
        clean = _bounded_channel_text(channel, text)
        if not clean:
            return
        moment = time.monotonic() if now is None else float(now)
        meta = dict(metadata or {})
        with self._lock:
            self._items[channel] = (clean, moment, meta)
        self._export_prompt_snapshot()
        if self.history_store is not None:
            modality = {"screen": "visual", "speech": "speech", "music": "music", "music_candidate": "sound", "sound": "sound"}.get(channel)
            if channel in {"audio_description", "audio_candidates", "audio_event_candidates"}:
                modality = "music" if meta.get("audio_kind") == "music" else "sound"
            if modality:
                observed_at = (
                    meta.get("observed_at")
                    or meta.get("captured_at")
                    or meta.get("observed_at_wall")
                )
                self._record_history(
                    modality,
                    clean,
                    observed_at=observed_at,
                    source=str(meta.get("source") or ""),
                    scene_id=str(meta.get("scene_id") or ""),
                    frame_id=str(meta.get("frame_id") or ""),
                    confidence=meta.get("confidence"),
                    verified=meta.get("verified"),
                    metadata=meta,
                )

    def compose(self, screen_summary: str = "", *, now: float | None = None) -> str:
        """Render fresh channels, recent screen history, and the current caption.

        When no explicit caption is supplied, the last VLM caption stored via
        :meth:`observe_screen` is rendered instead (while fresh).
        """
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
            visual_events = list(self._visual_events)
        return self._compose_items(
            items, visual_events=visual_events, screen_summary=screen_summary, moment=moment
        )

    def compose_snapshot(
        self,
        screen_summary: str = "",
        *,
        now: float | None = None,
        include_visual_history: bool = True,
    ) -> dict[str, Any]:
        """Return one atomic fused view plus bounded per-channel provenance.

        The view and metadata are derived from the same locked copy so callers
        can attach the exact source/frame/age and recent screen events that
        accompanied a brain turn.
        """
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
            visual_events = list(self._visual_events)
        if not include_visual_history:
            visual_events = []
        channels: dict[str, dict[str, Any]] = {}
        for kind, (text, stamp, metadata) in items.items():
            ttl = _NOW_TTL.get(kind, _TTL_SECONDS.get(kind, 120.0))
            age = max(0.0, moment - stamp)
            fresh = age <= ttl and not bool(metadata.get("possibly_outdated"))
            if kind == "audio_candidates":
                fresh = fresh and _audio_candidates_have_music_support(items, moment)
            channel = {
                "text": _bounded_channel_text(kind, text),
                "fresh": fresh,
                "age_ms": round(age * 1000.0, 1),
                "ttl_ms": round(ttl * 1000.0, 1),
                "metadata": dict(metadata),
            }
            caption_time = metadata.get("caption_time_monotonic") if kind == "screen" else None
            if isinstance(caption_time, (int, float)) and not isinstance(caption_time, bool):
                channel["caption_age_ms"] = round(max(0.0, moment - float(caption_time)) * 1000.0, 1)
            channels[kind] = channel
        return {
            "text": self._compose_items(
                items, visual_events=visual_events, screen_summary=screen_summary, moment=moment
            ),
            "channels": channels,
            "include_eg2_media_in_scene": self.include_eg2_media_in_scene,
            "recent_visual_events": self._visible_visual_events(items, visual_events, moment),
            "captured_monotonic": moment,
        }

    def _compose_items(
        self,
        items: dict[str, tuple[str, float, dict[str, Any]]],
        *,
        visual_events: list[dict[str, Any]],
        screen_summary: str,
        moment: float,
    ) -> str:
        parts: list[str] = []
        screen = str(screen_summary or "").strip()[:300]
        if not screen:
            stored = items.get("screen")
            if stored and not stored[2].get("possibly_outdated"):
                age_s = max(0.0, moment - stored[1])
                age_note = (
                    f"наблюдение {age_s:.1f} с назад"
                    if age_s <= _NOW_TTL.get("screen", 5.0) and not stored[2].get("possibly_outdated")
                    else f"последнее наблюдение {age_s:.1f} с назад; сцена могла измениться"
                )
                screen = f"[{age_note}] {stored[0][:260]}"
        media = items.get("media")
        media_fresh = bool(
            media and moment - media[1] <= _NOW_TTL.get("media", 5.0)
        )
        if media_fresh:
            parts.append(f"{_LABELS.get('media', 'Медиа')}: {media[0]}")
        if screen:
            parts.append(
                f"\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u044d\u043a\u0440\u0430\u043d [\u043d\u0435\u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u0430\u044f \u0433\u0438\u043f\u043e\u0442\u0435\u0437\u0430 \u0432\u0438\u0437\u0443\u0430\u043b\u044c\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438]: {screen}"
            )
        recent_events = self._visible_visual_events(items, visual_events, moment)
        if recent_events:
            rendered = [
                f"{event['age_s']:.1f} с назад ({event['scene_id'] or event['frame_id']}): {event['text']}"
                for event in recent_events[-_MAX_RENDERED_VISUAL_EVENTS:]
            ]
            parts.append("Недавняя последовательность экрана (история, не текущий кадр; модельные гипотезы могут быть ошибочны): " + " -> ".join(rendered))
        for kind in ("eg2_media", "eg2", "ocr", "sound", "window", "music", "music_candidate", "audio_candidates", "audio_event_candidates", "audio_description", "speech", "voice_delivery"):
            if kind == "eg2_media" and not self.include_eg2_media_in_scene:
                continue
            entry = items.get(kind)
            if not entry:
                continue
            text, stamp = entry[0], entry[1]
            ttl = _NOW_TTL.get(kind, _TTL_SECONDS.get(kind, 120.0))
            if moment - stamp > ttl or entry[2].get("possibly_outdated"):
                continue
            if kind == "audio_candidates" and not _audio_candidates_have_music_support(items, moment):
                continue
            parts.append(f"{_LABELS.get(kind, kind)}: {text}")
        clean_parts = [part.strip() for part in parts if part.strip()]
        sentences = [
            part
            if index == len(clean_parts) - 1 or part.endswith((".", "!", "?", "…"))
            else part + "."
            for index, part in enumerate(clean_parts)
        ]
        return " ".join(sentences)[:1200]

    @staticmethod
    def _visible_visual_events(
        items: dict[str, tuple[str, float, dict[str, Any]]],
        events: list[dict[str, Any]],
        moment: float,
    ) -> list[dict[str, Any]]:
        screen = items.get("screen")
        current_scene = ""
        if (
            screen
            and not screen[2].get("possibly_outdated")
            and moment - screen[1] <= _NOW_TTL.get("screen", 5.0)
        ):
            current_scene = str(screen[2].get("scene_id") or "")
        visible: list[dict[str, Any]] = []
        for event in events:
            age_s = max(0.0, moment - float(event["captured_monotonic"]))
            if age_s > _VISUAL_EVENT_TTL_SECONDS:
                continue
            if current_scene and str(event.get("scene_id") or "") == current_scene:
                continue
            visible.append({
                "text": str(event["text"]),
                "age_s": round(age_s, 1),
                "age_ms": round(age_s * 1000.0, 1),
                "ttl_ms": round(_VISUAL_EVENT_TTL_SECONDS * 1000.0, 1),
                "frame_id": str(event.get("frame_id") or ""),
                "scene_id": str(event.get("scene_id") or ""),
                "source": str(event.get("source") or ""),
                "captured_at": event.get("captured_at"),
                **({"roi": list(event["roi"])} if event.get("roi") is not None else {}),
            })
        return visible

    def record_visual_event(
        self,
        caption: str,
        *,
        captured_at_monotonic: float,
        captured_at_wall: float,
        frame_id: str,
        source: str,
        scene_id: str,
        roi: tuple[float, float, float, float] | None = None,
        now: float | None = None,
        persist_history: bool = False,
    ) -> bool:
        """Keep a short, timestamped visual event without making it current."""
        clean = str(caption or "").replace("\x00", "").strip()[:240]
        if not clean:
            return False
        moment = time.monotonic() if now is None else float(now)
        captured = float(captured_at_monotonic)
        if moment - captured > _VISUAL_EVENT_TTL_SECONDS:
            return False
        event: dict[str, Any] = {
            "text": clean,
            "captured_monotonic": captured,
            "captured_at": round(float(captured_at_wall), 3),
            "frame_id": str(frame_id)[:64],
            "source": str(source)[:120],
            "scene_id": str(scene_id)[:64],
        }
        if roi is not None:
            event["roi"] = tuple(round(float(value), 4) for value in roi)
        with self._lock:
            events = list(self._visual_events)
            scene = event["scene_id"]
            existing_index = next(
                (index for index, previous in enumerate(events) if scene and previous.get("scene_id") == scene),
                None,
            )
            if existing_index is None:
                events.append(event)
            elif captured >= float(events[existing_index]["captured_monotonic"]):
                events[existing_index] = event
            else:
                return False
            events = [
                item
                for item in events
                if moment - float(item["captured_monotonic"]) <= _VISUAL_EVENT_TTL_SECONDS
            ]
            events.sort(key=lambda item: float(item["captured_monotonic"]))
            self._visual_events.clear()
            self._visual_events.extend(events[-_MAX_VISUAL_EVENTS:])
        if persist_history and self.history_store is not None:
            self._record_history(
                "visual",
                clean,
                observed_at=float(captured_at_wall),
                source=str(source or "")[:100],
                scene_id=str(scene_id or "")[:64],
                frame_id=str(frame_id or "")[:64],
                verified=False,
                metadata={"history_only": True, "roi": list(roi) if roi is not None else None},
            )
        return True

    def observe_screen(self, caption: str) -> str:
        """Store the latest VLM caption and return the fused observation."""
        self.note("screen", caption)
        return self.compose()

    def current_state(self, kind: str, *, now: float | None = None) -> dict[str, Any]:
        """Report whether a channel is present in the current-context view."""
        channel = str(kind)[:40]
        moment = time.monotonic() if now is None else float(now)
        ttl = _NOW_TTL.get(channel, _TTL_SECONDS.get(channel, 120.0))
        with self._lock:
            entry = self._items.get(channel)
            items = dict(self._items)
        if entry is None:
            return {"channel": channel, "fresh": False, "age_ms": None, "ttl_ms": round(ttl * 1000.0, 1)}
        age = max(0.0, moment - entry[1])
        result = {
            "channel": channel,
            "fresh": age <= ttl and not bool(entry[2].get("possibly_outdated")),
            "age_ms": round(age * 1000.0, 1),
            "ttl_ms": round(ttl * 1000.0, 1),
            "metadata": dict(entry[2]),
        }
        if channel == "audio_candidates":
            result["fresh"] = bool(result["fresh"] and _audio_candidates_have_music_support(items, moment))
        caption_time = entry[2].get("caption_time_monotonic") if channel == "screen" else None
        if isinstance(caption_time, (int, float)) and not isinstance(caption_time, bool):
            result["caption_age_ms"] = round(max(0.0, moment - float(caption_time)) * 1000.0, 1)
        return result

    def confirm_caption(
        self,
        *,
        scene_id: str,
        confirmed_at_monotonic: float,
        confirmed_at_wall: float,
    ) -> bool:
        """Refresh current-screen confirmation only for the same observed scene.

        The model caption's original timestamp remains intact; repeated pixels
        confirm that it still describes the visible scene without another VLM call.
        """
        moment = float(confirmed_at_monotonic)
        with self._lock:
            entry = self._items.get("screen")
            if entry is None or str(entry[2].get("scene_id") or "") != str(scene_id or ""):
                return False
            if moment < entry[1]:
                return False
            metadata = dict(entry[2])
            metadata["confirmed_at"] = round(float(confirmed_at_wall), 3)
            metadata["confirmed_at_monotonic"] = moment
            self._items["screen"] = (entry[0], moment, metadata)
        self._export_prompt_snapshot()
        return True

    def invalidate(self, kind: str, *, now: float | None = None) -> None:
        """Mark a channel as potentially outdated without losing its timestamped value."""
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            channel = str(kind)[:40]
            channels = (
                ("screen", "ocr") if channel == "screen"
                else ("speech", "voice_delivery") if channel == "speech"
                else (channel, "audio_candidates") if channel == "music"
                else (channel,)
            )
            for target in channels:
                entry = self._items.get(target)
                if entry is None:
                    continue
                # Independent sensor workers can finish out of order. A late
                # invalidation from an older segment must not poison newer evidence.
                if moment < entry[1]:
                    continue
                metadata = dict(entry[2])
                metadata["possibly_outdated"] = True
                metadata["invalidated_at_monotonic"] = moment
                self._items[target] = (entry[0], entry[1], metadata)
        self._export_prompt_snapshot()

    def observe_caption(
        self,
        caption: str,
        *,
        captured_at_monotonic: float,
        captured_at_wall: float,
        frame_id: str,
        source: str,
        scene_id: str,
        roi: tuple[float, float, float, float] | None = None,
        now: float | None = None,
    ) -> str:
        """Store one Qwen caption with its original capture time and frame metadata.

        Repeated ``compose`` calls never refresh this entry: the TTL is measured
        from ``captured_at_monotonic``, not from delivery or reading.
        """
        metadata = {
            "captured_at": round(float(captured_at_wall), 3),
            "caption_time": round(float(captured_at_wall), 3),
            "caption_time_monotonic": float(captured_at_monotonic),
            "confirmed_at": round(float(captured_at_wall), 3),
            "frame_id": str(frame_id)[:64],
            "source": str(source)[:120],
            "scene_id": str(scene_id)[:64],
        }
        if roi is not None:
            metadata["roi"] = [round(float(value), 4) for value in roi]
        self.record_visual_event(
            caption,
            captured_at_monotonic=captured_at_monotonic,
            captured_at_wall=captured_at_wall,
            frame_id=frame_id,
            source=source,
            scene_id=scene_id,
            roi=roi,
            now=now,
            persist_history=False,
        )
        self.note("screen", caption, now=captured_at_monotonic, metadata=metadata)
        return self.compose(now=now)

    def eg2_cortex(self) -> Any | None:
        """Return the attached cortex, loading it lazily if weights are available."""
        if self.eg2 is not None:
            return self.eg2
        try:
            from .eg2_sensory import DEFAULT_EG2_ONNX_ROOT, EmbeddingGemmaSensoryCortex

            if (DEFAULT_EG2_ONNX_ROOT / "onnx" / "model_q4.onnx").is_file():
                self.eg2 = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT)
                try:
                    from .eg2_describer import DetailedSensoryDescriber
                    self.describer = DetailedSensoryDescriber(self.eg2)
                except Exception:
                    self.describer = None
        except Exception:  # noqa: BLE001 - perception must degrade without EG2
            self.eg2 = None
        return self.eg2

    def observe_media(
        self,
        observation: Any,
        *,
        now: float | None = None,
        modality: str | None = None,
        summary: str | None = None,
        vector: Any | None = None,
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
    ) -> str:
        """Store a compact media observation and return fused text."""
        payload = observation.to_dict() if hasattr(observation, "to_dict") else (
            observation if isinstance(observation, dict) else {"summary": str(observation or "")}
        )
        resolved = str(
            summary
            or payload.get("summary")
            or payload.get("description")
            or payload.get("top_label")
            or "media"
        ).strip()[:500]
        if self.media_buffer is not None:
            self.media_buffer.observe(
                observation,
                now=now,
                modality=modality,
                summary=resolved,
                vector=vector,
                metadata=metadata,
            )
        target = str(channel or "").strip()[:20]
        if not target:
            target = "sound" if str(modality or "").casefold() == "audio" else "media"
        self.note(target, resolved[:240], now=now)
        return self.compose(now=now)

    def observe_displays(
        self,
        image_bytes_list: list[bytes],
        *,
        cortex: Any | None = None,
        audio_wav_bytes: bytes | None = None,
        now: float | None = None,
    ) -> str:
        """Classify and fuse up to N displays (and optional system audio)."""
        moment = time.monotonic() if now is None else float(now)
        if cortex is None:
            cortex = self.eg2_cortex()
        description = "Дисплеи: нет данных"
        describer = getattr(self, "describer", None)
        if cortex is not None and hasattr(cortex, "describe_displays"):
            try:
                if describer is not None and hasattr(describer, "describe_displays_detailed"):
                    try:
                        description = describer.describe_displays_detailed(image_bytes_list or [])
                    except Exception:
                        description = "Дисплеи: ошибка классификации"
                else:
                    description = cortex.describe_displays(image_bytes_list or [])
            except Exception:  # noqa: BLE001 - degrade gracefully
                description = "Дисплеи: ошибка классификации"
        # Per-display notes for state visibility.
        if cortex is not None and hasattr(cortex, "classify_displays"):
            try:
                for index, obs in enumerate(cortex.classify_displays(image_bytes_list or [])):
                    self.note(f"display{index}", getattr(obs, "top_label", str(obs)), now=moment)
            except Exception:  # noqa: BLE001
                pass
        if audio_wav_bytes:
            try:
                if describer is not None and hasattr(describer, "describe_audio_detailed"):
                    from .audio_understanding import safe_detailed_audio_claim

                    audio_obs = describer.describe_audio_detailed(audio_wav_bytes)
                    safe_audio = safe_detailed_audio_claim(audio_obs)
                    if safe_audio["kind"] == "speech" or safe_audio["description"] == "Possible rhythmic sound; music is not independently verified.":
                        self.note("sound", safe_audio["description"], now=moment)
            except Exception:  # noqa: BLE001
                pass
        self.note("eg2_media", description, now=moment)
        return self.compose(now=moment)

    def observe_eg2(
        self, observation: Any, *, now: float | None = None, modality: str = "eg2"
    ) -> str:
        """Store a compact EmbeddingGemma 2 observation and return fused text."""
        payload = observation.to_dict() if hasattr(observation, "to_dict") else (
            observation if isinstance(observation, dict) else {"summary": str(observation or "")}
        )
        summary = str(
            payload.get("summary")
            or payload.get("description")
            or payload.get("top_label")
            or "eg2"
        ).strip()
        parts = [summary[:120]]
        audio = str(payload.get("audio_top_label") or "").strip()
        if audio:
            parts.append(f"audio={audio}")
        vibe = payload.get("vibe_score")
        if isinstance(vibe, (int, float)):
            parts.append(f"vibe={float(vibe):.3f}")
        reflex = payload.get("reflex")
        if isinstance(reflex, dict) and reflex.get("emotion"):
            parts.append(f"reflex={reflex['emotion']}")
        self.note("eg2", " ".join(parts), now=now)
        if self.media_buffer is not None:
            self.media_buffer.observe(
                observation, now=now, modality=modality, summary=summary
            )
        return self.compose(now=now)

    def state(self, *, now: float | None = None) -> dict[str, Any]:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
            visual_events = list(self._visual_events)
        fresh = {
            kind: {
                "text": entry[0],
                "age_s": round(moment - entry[1], 1),
                **({"metadata": entry[2]} if len(entry) > 2 and entry[2] else {}),
            }
            for kind, entry in items.items()
            if moment - entry[1] <= _NOW_TTL.get(kind, _TTL_SECONDS.get(kind, 120.0))
            and not bool(entry[2].get("possibly_outdated"))
        }
        return {
            "fresh": fresh,
            "recent_visual_events": self._visible_visual_events(items, visual_events, moment),
        }
