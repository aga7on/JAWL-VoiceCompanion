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

import base64
import logging
import time

logger = logging.getLogger(__name__)
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
import threading
from threading import RLock
from typing import Any

_TTL_SECONDS = {
    "screen": 90.0,
    "visual": 90.0,
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
    "visual": 5.0,
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
    "visual": 1000,
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
_LABELS["visual"] = "Кадр экрана"


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
class CognitiveTurnDecision:
    """Outcome of central cognitive arbitration."""
    action: str  # 'none' | 'backchannel' | 'proactive_turn'
    backchannel_cue: str | None = None
    vrm_blendshapes: dict[str, float] | None = None
    dominant_expression: str = "neutral"
    proactive_packet: dict[str, Any] | None = None
    reason: str = ""


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
    vision_describer: Any | None = field(default=None, init=True, repr=False)
    visual_stream_worker: Any | None = field(default=None, init=True, repr=False)
    scene_state: Any | None = field(default=None, init=True, repr=False)
    event_policy: Any | None = field(default=None, init=True, repr=False)
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

    @staticmethod
    def _is_channel_hypothesis(kind: str, metadata: dict[str, Any]) -> bool:
        if metadata.get("hypothesis") is True:
            return True
        if metadata.get("hypothesis") is False:
            return False
        if metadata.get("verified") is True:
            return False
        if metadata.get("verified") is False:
            return True
        if metadata.get("confidence_calibrated") is False or metadata.get("calibrated") is False:
            return True
        if metadata.get("candidate_hypotheses") is True:
            return True
        if metadata.get("score_type") in ("uncalibrated_raw_model_score", "cosine_similarity_not_probability"):
            return True
        if bool(metadata.get("candidate_tags") and metadata.get("candidate_tags_calibrated") is False):
            return True
        if kind in (
            "screen",
            "ocr",
            "music_candidate",
            "audio_candidates",
            "audio_event_candidates",
            "audio_description",
        ):
            return True
        if kind == "music" and (
            metadata.get("music_state") in ("unknown", "unconfirmed")
            or metadata.get("calibrated") is False
            or bool(metadata.get("candidate_tags") and metadata.get("candidate_tags_calibrated") is False)
        ):
            return True
        return False

    @staticmethod
    def _extract_provenance(metadata: dict[str, Any]) -> dict[str, Any] | None:
        prov = metadata.get("provenance")
        if isinstance(prov, dict):
            return dict(prov)
        keys = (
            "source", "scene_id", "frame_id", "segment_id",
            "detector", "capture_source", "source_app", "app_category",
            "app_title", "app_pid", "caption_provider",
        )
        extracted = {k: metadata[k] for k in keys if k in metadata and metadata[k] is not None}
        return extracted if extracted else None

    @staticmethod
    def _extract_confidence(metadata: dict[str, Any]) -> float | None:
        val = metadata.get("confidence")
        if val is None:
            val = metadata.get("model_score")
        if val is None:
            val = metadata.get("music_score_max")
        if val is not None and not isinstance(val, bool):
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
        return None

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
        if self._is_channel_hypothesis(channel, meta):
            meta.setdefault("hypothesis", True)
            if meta.get("verified") is None:
                meta["verified"] = False
        conf = self._extract_confidence(meta)
        if conf is not None and "confidence" not in meta:
            meta["confidence"] = conf
        prov = self._extract_provenance(meta)
        if prov is not None and "provenance" not in meta:
            meta["provenance"] = prov
        with self._lock:
            existing = self._items.get(channel)
            if existing is not None:
                _, old_moment, old_meta = existing
                is_incoming_verified = meta.get("verified") is True
                is_existing_verified = old_meta.get("verified") is True
                if is_existing_verified and not is_incoming_verified:
                    ttl = _NOW_TTL.get(channel, 20.0)
                    if moment - old_moment <= ttl:
                        # Ground truth protection: keep fresh verified observation,
                        # do not let unverified acoustic/perceptual hypothesis stomp it.
                        return

            self._items[channel] = (clean, moment, meta)
        self._export_prompt_snapshot()
        if self.history_store is not None:
            modality = {
                "screen": "visual",
                "visual": "visual",
                "top_down_vision": "visual",
                "speech": "speech",
                "music": "music",
                "music_candidate": "sound",
                "sound": "sound",
            }.get(channel)
            if channel in {"audio_description", "audio_candidates", "audio_event_candidates"}:
                modality = "music" if meta.get("audio_kind") == "music" else "sound"
            if modality:
                # Cross-modal arbitration for history: if verified music is currently active,
                # suppress unverified music hypotheses from polluting the sensory history.
                if modality == "music" and not meta.get("verified", False):
                    with self._lock:
                        music_item = self._items.get("music")
                        if music_item is not None:
                            _, m_moment, m_meta = music_item
                            if m_meta.get("verified") is True and (moment - m_moment <= _NOW_TTL.get("music", 20.0)):
                                return

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
                    event_id=meta.get("event_id"),
                )

    _top_down_executor: Any | None = field(default=None, init=False, repr=False)
    _top_down_semaphore: Any | None = field(default=None, init=False, repr=False)

    def _get_top_down_executor(self) -> Any:
        with self._lock:
            executor = getattr(self, "_top_down_executor", None)
            if executor is None or getattr(executor, "_shutdown", False):
                import concurrent.futures
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="topdown_vlm"
                )
                self._top_down_executor = executor
                self._top_down_semaphore = threading.Semaphore(2)
            return executor

    def _get_top_down_semaphore(self) -> threading.Semaphore:
        with self._lock:
            sem = getattr(self, "_top_down_semaphore", None)
            if sem is None:
                sem = threading.Semaphore(2)
                self._top_down_semaphore = sem
            return sem

    def fetch_top_down_observation(
        self,
        query: str,
        *,
        target: str = "",
        region: str = "full_frame",
        timeout_s: float = 3.0,
        max_staleness_ms: float = 4000.0,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        """Performs a bounded Top-Down visual inspection with provenance and calibration.

        Acquires current frame and its timestamp from VisualStreamWorker/capture.
        Invokes vision_describer on the frame with strict timeout enforcement.
        Computes semantic_age = t_now - t_capture.
        Enforces staleness checks both pre- and post-inference.
        Monitors scene state to detect scene change during inference.
        Detects model uncertainty / hedging and degrades to NOT_OBSERVED (never claims verified fact).
        Distinguishes target-specific absence from generic or unrelated negative statements.
        Updates SceneState (positive detection or bounded negative inspection) without parallel memory.
        If VLM fails, times out, or is cancelled, returns explicit NOT_OBSERVED (never invents empty scene).
        """
        from .scene_state import EpistemicObservationState

        t_start = time.monotonic()
        clean_query = str(query or "").strip()
        focus_target = str(target or clean_query).strip()

        # 0. Check cancellation before doing any work
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": "cancelled",
                "reason": "Top-down visual inspection cancelled before dispatch",
                "captured_at": 0.0,
                "semantic_age_ms": 0.0,
                "inspection_quality": 0.0,
                "details": "",
                "needs_visual_refresh": True,
            }

        # 1. Acquire frame and captured_at timestamp strictly from configured worker or screen capture
        worker = getattr(self, "visual_stream_worker", None)
        frame = None
        t_capture = 0.0

        if worker is not None and hasattr(worker, "get_latest_frame_with_timestamp"):
            frame, t_capture = worker.get_latest_frame_with_timestamp(max_dimension=1280)
        elif worker is not None and hasattr(worker, "capture") and hasattr(worker.capture, "grab_pil_with_timestamp"):
            frame, t_capture = worker.capture.grab_pil_with_timestamp(max_dimension=1280)
        elif worker is not None and hasattr(worker, "capture") and hasattr(worker.capture, "grab_pil"):
            frame = worker.capture.grab_pil(max_dimension=1280)
            t_capture = getattr(worker.capture, "_last_frame_time", time.monotonic()) or time.monotonic()
        elif getattr(self, "screen_capture", None) is not None:
            cap = self.screen_capture
            if hasattr(cap, "grab_pil_with_timestamp"):
                frame, t_capture = cap.grab_pil_with_timestamp(max_dimension=1280)
            elif hasattr(cap, "grab_pil"):
                frame = cap.grab_pil(max_dimension=1280)
                t_capture = time.monotonic()

        if frame is None:
            # Capture unavailable: explicit NOT_OBSERVED! No rogue DXGIScreenCapture fallback!
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": "capture_unavailable",
                "reason": "Screen capture worker is not configured, paused, or returned no frame",
                "captured_at": t_capture,
                "semantic_age_ms": 0.0,
                "inspection_quality": 0.0,
                "details": "",
                "needs_visual_refresh": True,
            }

        # 2. Pre-inference staleness check
        t_pre = time.monotonic()
        pre_capture_age_ms = max(0.0, (t_pre - t_capture) * 1000.0) if t_capture > 0 else 0.0
        if t_capture > 0 and pre_capture_age_ms > max_staleness_ms:
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": "stale_frame",
                "reason": f"Captured frame is already stale ({pre_capture_age_ms:.1f}ms > max staleness {max_staleness_ms:.1f}ms)",
                "captured_at": t_capture,
                "semantic_age_ms": round(pre_capture_age_ms, 1),
                "inspection_quality": 0.0,
                "details": "",
                "needs_visual_refresh": True,
            }

        # 3. Acquire vision describer and identify real model/source
        describer = getattr(self, "vision_describer", None)
        if describer is None:
            semantic_age_ms = max(0.0, (time.monotonic() - t_capture) * 1000.0)
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": "not_configured",
                "reason": "Vision describer is not configured",
                "captured_at": t_capture,
                "semantic_age_ms": round(semantic_age_ms, 1),
                "inspection_quality": 0.0,
                "details": "",
                "needs_visual_refresh": True,
            }

        source_name = (
            getattr(describer, "model", None)
            or getattr(describer, "model_name", None)
            or getattr(describer, "source", None)
            or type(describer).__name__
        )

        # 4. Snapshot current scene ID and version for scene transition detection
        sc_state = getattr(self, "scene_state", None)
        initial_scene_id = getattr(sc_state, "scene_id", None)
        initial_scene_version = getattr(sc_state, "scene_version", 0)

        # Without a continuously running visual worker, take a local baseline
        # for this request. A separate detector avoids mutating the shared
        # capture detector while another observation is in flight.
        request_scene_detector = None
        if worker is None and getattr(self, "screen_capture", None) is not None:
            try:
                from .visual_stream import SceneDeltaDetector
                request_scene_detector = SceneDeltaDetector()
                request_scene_detector.compute_delta(frame, commit=True)
            except Exception:
                return {
                    "status": EpistemicObservationState.NOT_OBSERVED,
                    "target": focus_target, "region": region,
                    "source": "scene_verification_unavailable",
                    "reason": "Could not initialize scene verification",
                    "captured_at": t_capture, "inspection_quality": 0.0,
                    "semantic_age_ms": max(0.0, (time.monotonic() - t_capture) * 1000.0),
                    "details": "", "needs_visual_refresh": True,
                }

        # 5. Formulate targeted prompt and payload
        try:
            import base64
            import inspect
            import io

            buf = io.BytesIO()
            frame.save(buf, format="JPEG", quality=85)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            obs_payload = {
                "image": {"data_base64": b64_data, "media_type": "image/jpeg"},
                "target": focus_target,
                "region": region,
            }

            OPEN_TARGETS = {
                "экран", "кадр", "full_frame", "сцена", "детали на экране",
                "изображение", "текущий кадр", "содержимое экрана", "окно", "персонажи в кадре",
            }
            is_open_target = (
                not focus_target
                or focus_target.lower() in OPEN_TARGETS
                or focus_target.lower().startswith("full_")
                or any(t in focus_target.lower() for t in ["экран", "кадр", "сцена", "содержимое"])
                or (region == "full_frame" and any(w in focus_target.lower() for w in ["что", "опиши", "расскажи", "видно"]))
                or any(w in clean_query.lower() for w in ["что сейчас видно", "что видно", "опиши экран", "опиши кадр"])
            )

            if is_open_target:
                vlm_prompt = (
                    f"Опиши кратко и конкретно, что сейчас видно на экране: основные объекты, текст, геометрические фигуры и цвета. "
                    f"Не придумывай то, чего не видишь."
                )
            else:
                vlm_prompt = (
                    f"Ответь кратко и конкретно на вопрос о текущем кадре: '{clean_query}'. "
                    f"Если объекта или детали '{focus_target}' нет на экране, прямо напиши 'отсутствует'. "
                    f"Не придумывай то, чего не видишь."
                )

            def _invoke_describer() -> str:
                if hasattr(describer, "describe"):
                    accepts_cancel = False
                    try:
                        sig = inspect.signature(describer.describe)
                        accepts_cancel = "cancel_event" in sig.parameters
                    except (ValueError, TypeError):
                        accepts_cancel = False

                    if accepts_cancel:
                        res = describer.describe(vlm_prompt, obs_payload, cancel_event=cancel_event)
                    else:
                        res = describer.describe(vlm_prompt, obs_payload)
                    return str(res or "").strip()
                elif hasattr(describer, "look"):
                    accepts_cancel = False
                    try:
                        sig = inspect.signature(describer.look)
                        accepts_cancel = "cancel_event" in sig.parameters
                    except (ValueError, TypeError):
                        accepts_cancel = False

                    if accepts_cancel:
                        res = describer.look(vlm_prompt, cancel_event=cancel_event)
                    else:
                        res = describer.look(vlm_prompt)
                    if isinstance(res, dict):
                        return str(res.get("details") or res.get("text") or "").strip()
                    return str(res or "").strip()
                else:
                    raise ValueError(f"Describer {type(describer).__name__} does not implement describe or look")

            # Execute in bounded threadpool with real timeout enforcement and cancellation
            executor = self._get_top_down_executor()
            semaphore = self._get_top_down_semaphore()
            timeout_limit = max(0.01, float(timeout_s))

            # Bounded admission: do not block user if all worker slots are saturated
            if not semaphore.acquire(blocking=False):
                sem_age = max(0.0, (time.monotonic() - t_capture) * 1000.0)
                return {
                    "status": EpistemicObservationState.NOT_OBSERVED,
                    "target": focus_target,
                    "region": region,
                    "source": source_name,
                    "reason": "Top-down visual describer is busy (capacity limit reached, request dropped without queue accumulation)",
                    "captured_at": t_capture,
                    "semantic_age_ms": round(sem_age, 1),
                    "inspection_quality": 0.0,
                    "details": "",
                    "needs_visual_refresh": True,
                }

            deadline = time.monotonic() + timeout_limit

            def _worker_wrapper() -> str | None:
                try:
                    # Drop expired or cancelled requests before executing
                    if time.monotonic() >= deadline:
                        return None
                    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                        return None
                    return _invoke_describer()
                finally:
                    semaphore.release()

            try:
                future = executor.submit(_worker_wrapper)
            except Exception as submit_err:
                semaphore.release()
                raise submit_err

            t_wait_start = time.monotonic()
            vlm_text = None
            is_timed_out = False
            is_cancelled = False
            dispatch_err = None

            while True:
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    is_cancelled = True
                    break
                if not future.done():
                    elapsed = time.monotonic() - t_wait_start
                    if elapsed >= timeout_limit:
                        is_timed_out = True
                        break
                    time.sleep(min(0.02, max(0.001, timeout_limit - elapsed)))
                    continue
                try:
                    vlm_text = future.result(timeout=0)
                    break
                except Exception as ex:
                    dispatch_err = ex
                    break

            if is_cancelled:
                if future.cancel():
                    semaphore.release()
                sem_age = max(0.0, (time.monotonic() - t_capture) * 1000.0)
                return {
                    "status": EpistemicObservationState.NOT_OBSERVED,
                    "target": focus_target,
                    "region": region,
                    "source": source_name,
                    "reason": "Top-down visual inspection cancelled by user turn",
                    "captured_at": t_capture,
                    "semantic_age_ms": round(sem_age, 1),
                    "inspection_quality": 0.0,
                    "details": "",
                    "needs_visual_refresh": True,
                }

            if is_timed_out:
                if future.cancel():
                    semaphore.release()
                sem_age = max(0.0, (time.monotonic() - t_capture) * 1000.0)
                return {
                    "status": EpistemicObservationState.NOT_OBSERVED,
                    "target": focus_target,
                    "region": region,
                    "source": source_name,
                    "reason": f"Top-down visual inspection timed out after {timeout_limit:.2f}s",
                    "captured_at": t_capture,
                    "semantic_age_ms": round(sem_age, 1),
                    "inspection_quality": 0.0,
                    "details": "",
                    "needs_visual_refresh": True,
                }

            if dispatch_err is not None:
                raise dispatch_err

            if vlm_text is None:
                raise ValueError("VLM call returned empty result")

        except Exception as exc:
            semantic_age_ms = max(0.0, (time.monotonic() - t_capture) * 1000.0)
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": source_name,
                "reason": f"Top-down visual inspection failed or timed out: {type(exc).__name__}: {exc}",
                "captured_at": t_capture,
                "semantic_age_ms": round(semantic_age_ms, 1),
                "details": "",
                "inspection_quality": 0.0,
                "needs_visual_refresh": True,
            }

        # 6. Post-inference Scene Change check
        current_scene_id = getattr(sc_state, "scene_id", None)
        current_scene_version = getattr(sc_state, "scene_version", 0)
        scene_changed = (
            (initial_scene_id is not None and current_scene_id != initial_scene_id)
            or current_scene_version != initial_scene_version
        )
        scene_verification_failed = False
        if not scene_changed:
            detector = request_scene_detector or getattr(self, "delta_detector", None) or getattr(getattr(self, "screen_capture", None), "delta_detector", None)
            if detector is not None and hasattr(detector, "compute_delta"):
                try:
                    cap = getattr(self, "screen_capture", None)
                    if cap is not None and hasattr(cap, "grab_pil_with_timestamp"):
                        curr_frame, _ = cap.grab_pil_with_timestamp(max_dimension=1280)
                        if curr_frame is not None:
                            _, is_change, new_sid = detector.compute_delta(curr_frame, commit=False)
                            if is_change or (
                                getattr(sc_state, "scene_version", 0) != initial_scene_version
                            ):
                                scene_changed = True
                                if sc_state is not None and hasattr(sc_state, "transition_scene"):
                                    sc_state.transition_scene(new_sid)
                                current_scene_id = getattr(sc_state, "scene_id", new_sid)
                                current_scene_version = getattr(sc_state, "scene_version", initial_scene_version + 1)
                        elif request_scene_detector is not None:
                            scene_verification_failed = True
                except Exception:
                    scene_verification_failed = request_scene_detector is not None

        if scene_verification_failed:
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target, "region": region,
                "source": "scene_verification_unavailable",
                "reason": "Could not verify the scene after visual inspection",
                "captured_at": t_capture, "inspection_quality": 0.0,
                "semantic_age_ms": max(0.0, (time.monotonic() - t_capture) * 1000.0),
                "details": "", "needs_visual_refresh": True,
            }

        if scene_changed:
            sem_age = max(0.0, (time.monotonic() - t_capture) * 1000.0)
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": "scene_changed",
                "reason": f"Scene changed from '{initial_scene_id}' (v{initial_scene_version}) to '{current_scene_id}' (v{current_scene_version}) during visual inspection; observation discarded for current scene",
                "captured_at": t_capture,
                "semantic_age_ms": round(sem_age, 1),
                "inspection_quality": 0.0,
                "details": "",
                "needs_visual_refresh": True,
            }

        # 7. Post-inference Staleness check
        t_now = time.monotonic()
        semantic_age_ms = max(0.0, (t_now - t_capture) * 1000.0)
        if semantic_age_ms > max_staleness_ms:
            return {
                "status": EpistemicObservationState.NOT_OBSERVED,
                "target": focus_target,
                "region": region,
                "source": source_name,
                "reason": f"Observation expired: semantic age ({semantic_age_ms:.1f}ms) exceeds max staleness TTL ({max_staleness_ms:.1f}ms)",
                "captured_at": t_capture,
                "semantic_age_ms": round(semantic_age_ms, 1),
                "inspection_quality": 0.0,
                "details": vlm_text,
                "needs_visual_refresh": True,
            }

        # 8. Epistemic evaluation: uncertainty, targeted absence vs global absence, and positive observation
        import re

        vlm_lower = vlm_text.lower()

        UNCERTAIN_MARKERS = [
            "не уверен", "не уверена", "не могу разобрать", "не разобрать",
            "сложно сказать", "трудно сказать", "непонятно", "не разглядеть",
            "не ясно", "размыто", "не видно четко", "затрудняюсь",
            "не представляется возможным", "может быть", "кажется", "возможно",
            "похоже на", "предположительно", "нельзя точно",
            "not sure", "unclear", "cannot tell", "hard to say", "ambiguous",
            "low confidence", "uncertain", "cannot determine", "blurry",
        ]
        is_uncertain = any(m in vlm_lower for m in UNCERTAIN_MARKERS)

        OPEN_TARGETS = {
            "экран", "кадр", "full_frame", "сцена", "детали на экране",
            "изображение", "текущий кадр", "содержимое экрана", "окно", "персонажи в кадре",
        }
        is_open_target = (
            not focus_target
            or focus_target.lower() in OPEN_TARGETS
            or focus_target.lower().startswith("full_")
            or any(t in focus_target.lower() for t in ["экран", "кадр", "сцена", "содержимое"])
            or (region == "full_frame" and any(w in focus_target.lower() for w in ["что", "опиши", "расскажи", "видно"]))
            or any(w in clean_query.lower() for w in ["что сейчас видно", "что видно", "опиши экран", "опиши кадр"])
        )

        target_words = [w for w in re.findall(r"\w+", focus_target.lower()) if len(w) > 2]
        target_mentioned = any(tw in vlm_lower for tw in target_words)

        GLOBAL_ABSENCE_PHRASES = [
            "ничего нет", "пусто", "пустой экран", "кадр пуст",
            "ничего не видно", "ничего не обнаружено",
            "полностью отсутствует",
            "данный объект отсутствует", "объект отсутствует", "искомый объект отсутствует",
            "nothing is visible", "no objects", "empty screen", "the frame is empty",
            "nothing on the screen",
        ]
        # Partial-subject absence phrases: VLM reports that a specific KIND of thing
        # (people/persons) is not visible. This is NOT global scene absence: it may
        # coexist with a positive description of other scene contents ("виден дом,
        # никого не видно"), but for a targeted people question it IS evidence of absence.
        PARTIAL_SUBJECT_ABSENCE_PHRASES = [
            "никого не видно", "никого нет", "никого не обнаружено",
            "людей не видно", "человека не видно", "нет людей", "людей нет",
            "no people", "nobody is visible", "no one is visible", "no person",
            "no people are visible",
        ]
        is_global_absence = any(p in vlm_lower for p in GLOBAL_ABSENCE_PHRASES)
        has_partial_subject_absence = any(p in vlm_lower for p in PARTIAL_SUBJECT_ABSENCE_PHRASES)

        TARGET_ABSENCE_PHRASES = [
            "отсутствует", "отсутствуют", "отсутств", "не вижу", "не видно",
            "нет на кадре", "не обнаружен", "не обнаружена", "не обнаружено",
            "not present", "not found", "absent",
        ]

        # A targeted question about people ("кто в кадре?", "есть ли люди?") is its own
        # case: a people-absence phrase IS evidence of that specific target's absence.
        is_people_related_target = any(
            w in (focus_target.lower() + " " + clean_query.lower())
            for w in ["человек", "люд", "персонаж", "кто", "people", "person", "who"]
        )
        people_absence_evidence = has_partial_subject_absence and is_people_related_target

        # Residual content detection: strip all absence phrases and generic fillers;
        # whatever remains are real content words of a positive scene description.
        _FILLER_WORDS = {
            "на", "экране", "экран", "кадре", "кадр", "есть", "только", "но", "и",
            "the", "is", "a", "an", "in", "on", "at", "of", "and", "there", "it",
            "this", "that", "screen", "frame", "visible",
        }
        _residual = vlm_lower
        for _phrase in sorted(
            GLOBAL_ABSENCE_PHRASES + PARTIAL_SUBJECT_ABSENCE_PHRASES + TARGET_ABSENCE_PHRASES,
            key=len, reverse=True,
        ):
            _residual = _residual.replace(_phrase, " ")
        _content_words = [
            w for w in re.findall(r"[а-яёa-z]+", _residual)
            if len(w) > 2 and w not in _FILLER_WORDS
        ]
        describes_scene_content = len(_content_words) > 0

        # A purely negative answer ("Отсутствует", "ничего нет") cannot prove absence of the
        # WHOLE scene for an open/general query ("что видно на экране"): absence of an unnamed
        # target is non-informative, so it must degrade to NOT_OBSERVED instead of observed_absent.
        # Exception: a response that also DESCRIBES scene content ("виден дом, никого не видно")
        # is a positive observation with a partial-subject negative, not scene absence.
        is_uninformative_negative_for_open_target = (
            is_open_target
            and not describes_scene_content
            and (
                is_global_absence
                or has_partial_subject_absence
                or any(phrase in vlm_lower for phrase in TARGET_ABSENCE_PHRASES)
            )
        )

        is_target_absence = (
            ((not is_open_target) or people_absence_evidence)
            and (
                (target_mentioned and any(phrase in vlm_lower for phrase in TARGET_ABSENCE_PHRASES))
                or is_global_absence
                or people_absence_evidence
                or (vlm_lower.strip() in {"нет", "no", "отсутствует", "не обнаружен", "не найдено"} and len(target_words) > 0)
                or (vlm_lower.strip().startswith("нет,") and (target_mentioned or len(target_words) <= 1))
                or (vlm_lower.strip().startswith("нет ") and (target_mentioned or len(target_words) <= 1))
            )
        )

        if is_uncertain:
            quality = 0.40
            status = EpistemicObservationState.NOT_OBSERVED
            reason = f"VLM returned uncertain or hedged observation ({vlm_text[:60]}); not a verified fact"
            if sc_state is not None and hasattr(sc_state, "record_inspection"):
                sc_state.record_inspection(
                    target=focus_target,
                    region=region,
                    captured_at_ms=t_capture * 1000.0,
                    inspection_quality=quality,
                    verified_absent=False,
                    details=vlm_text,
                    source=source_name,
                )
        elif is_uninformative_negative_for_open_target:
            # Open/general query ("что видно на экране?") answered with a bare negative phrase:
            # this is a non-informative model output, NOT a proven absence of the whole scene.
            # Epistemically safe default: the scene state remains unknown.
            quality = 0.0
            status = EpistemicObservationState.NOT_OBSERVED
            reason = (
                f"Open-target query about scene contents got a non-informative negative answer "
                f"({vlm_text[:60]}); scene absence is not proven, visual state remains unknown "
                f"(source: {source_name})"
            )
        elif is_target_absence:
            # Calibrated bounded negative observation: absence is bounded by inspected region/frame, not absolute proof
            if (target_mentioned and len(vlm_text) > 8) or (is_global_absence and len(vlm_text) > 8):
                quality = 0.75
            elif len(vlm_text) > 4 and any(phrase in vlm_lower for phrase in TARGET_ABSENCE_PHRASES):
                quality = 0.70
            elif len(vlm_text) > 4:
                quality = 0.50
            else:
                quality = 0.40

            if quality >= 0.70:
                status = EpistemicObservationState.OBSERVED_ABSENT
                reason = f"Target '{focus_target}' actively inspected in '{region}' and not detected (bounded quality: {quality:.2f}, source: {source_name})"
                if sc_state is not None and hasattr(sc_state, "record_inspection"):
                    sc_state.record_inspection(
                        target=focus_target,
                        region=region,
                        captured_at_ms=t_capture * 1000.0,
                        inspection_quality=quality,
                        verified_absent=True,
                        details=vlm_text,
                        source=source_name,
                    )
            else:
                status = EpistemicObservationState.NOT_OBSERVED
                reason = f"Negative inspection quality too low ({quality:.2f}); visual state remains unknown"
        elif (is_open_target or target_mentioned) and len(vlm_text) > 5 and "error" not in vlm_lower:
            # A response that describes scene content is a POSITIVE observation even when it
            # additionally mentions absence of a specific kind of thing (e.g. "виден дом,
            # никого не видно"): absence of people is not absence of the scene contents.
            # Calibrated epistemic confidence for visual model hypothesis (never blindly 0.85)
            if target_mentioned and len(vlm_text) > 20:
                quality = 0.75
            elif is_open_target and len(vlm_text) > 20:
                quality = 0.70
            elif len(vlm_text) > 10:
                quality = 0.65
            else:
                quality = 0.50
            if has_partial_subject_absence and len(vlm_text) > 20:
                # Positive description carrying a partial-subject negative: keep positive
                # status with slightly conservative quality.
                quality = min(quality, 0.65)
            status = EpistemicObservationState.OBSERVED_PRESENT
            reason = f"Target '{focus_target}' observed as unverified visual hypothesis ({source_name})"
            if has_partial_subject_absence:
                reason += "; response additionally notes absence of a specific subject kind (not scene absence)"
            if sc_state is not None:
                if hasattr(sc_state, "record_unlocalized_presence"):
                    sc_state.record_unlocalized_presence(
                        traits={
                            "appearance": vlm_text,
                            "target": focus_target,
                            "region": region,
                            "hypothesis": True,
                            "verified": False,
                            "source": source_name,
                        },
                        confidence=quality,
                        evidence_id=f"topdown_{int(t_capture * 1000)}",
                        timestamp_ms=t_capture * 1000.0,
                    )
                if hasattr(sc_state, "record_inspection"):
                    sc_state.record_inspection(
                        target=focus_target,
                        region=region,
                        captured_at_ms=t_capture * 1000.0,
                        inspection_quality=quality,
                        verified_absent=False,
                        details=vlm_text,
                        source=source_name,
                    )
        else:
            quality = 0.40
            status = EpistemicObservationState.NOT_OBSERVED
            reason = f"Response did not clearly confirm requested target '{focus_target}'; visual presence unverified (source: {source_name})"

        obs = {
            "status": status,
            "target": focus_target,
            "region": region,
            "source": source_name,
            "verified": False,
            "hypothesis": status != EpistemicObservationState.NOT_OBSERVED,
            "provenance": {
                "source": source_name,
                "verified": False,
                "hypothesis": status != EpistemicObservationState.NOT_OBSERVED,
            },
            "details": vlm_text,
            "reason": reason,
            "captured_at": t_capture,
            "semantic_age_ms": round(semantic_age_ms, 1),
            "inspection_quality": round(quality, 2),
            "needs_visual_refresh": False if status != EpistemicObservationState.NOT_OBSERVED else True,
        }

        # Also register in fusion channel for unified perception packet
        self.note(
            "top_down_vision",
            f"[{status}] {focus_target}: {vlm_text}",
            metadata={
                "status": status,
                "target": focus_target,
                "region": region,
                "source": source_name,
                "semantic_age_ms": round(semantic_age_ms, 1),
                "captured_at": t_capture,
                "observed_at": time.time(),
                "inspection_quality": round(quality, 2),
                "verified": False,
                "hypothesis": status != EpistemicObservationState.NOT_OBSERVED,
            },
        )

        return obs

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
            is_hypo = self._is_channel_hypothesis(kind, metadata)
            meta = dict(metadata)
            if is_hypo:
                meta.setdefault("hypothesis", True)
                if meta.get("verified") is None:
                    meta["verified"] = False
            conf = self._extract_confidence(meta)
            prov = self._extract_provenance(meta)
            channel: dict[str, Any] = {
                "text": _bounded_channel_text(kind, text),
                "fresh": fresh,
                "age_ms": round(age * 1000.0, 1),
                "ttl_ms": round(ttl * 1000.0, 1),
                "hypothesis": is_hypo,
                "metadata": meta,
            }
            if conf is not None:
                channel["confidence"] = conf
            if prov is not None:
                channel["provenance"] = prov
            caption_time = meta.get("caption_time_monotonic") if kind == "screen" else None
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
        if getattr(self, "scene_state", None) is not None and hasattr(self.scene_state, "transition_scene"):
            if scene_id and getattr(self.scene_state, "scene_id", "") != str(scene_id):
                self.scene_state.transition_scene(str(scene_id))
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
        metadata = {
            "source": "vlm_screen",
            "verified": False,
            "hypothesis": True,
            "provenance": {"source": "vlm_screen"},
        }
        self.note("screen", caption, metadata=metadata)
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
        meta = dict(entry[2])
        is_hypo = self._is_channel_hypothesis(channel, meta)
        conf = self._extract_confidence(meta)
        prov = self._extract_provenance(meta)
        result = {
            "channel": channel,
            "fresh": age <= ttl and not bool(meta.get("possibly_outdated")),
            "age_ms": round(age * 1000.0, 1),
            "ttl_ms": round(ttl * 1000.0, 1),
            "hypothesis": is_hypo,
            "metadata": meta,
        }
        if conf is not None:
            result["confidence"] = conf
        if prov is not None:
            result["provenance"] = prov
        if channel == "audio_candidates":
            result["fresh"] = bool(result["fresh"] and _audio_candidates_have_music_support(items, moment))
        caption_time = meta.get("caption_time_monotonic") if channel == "screen" else None
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
            "verified": False,
            "hypothesis": True,
            "provenance": {
                "source": str(source)[:120],
                "scene_id": str(scene_id)[:64],
                "frame_id": str(frame_id)[:64],
            },
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

    def observe_smtc(
        self,
        track_info: dict[str, Any],
        *,
        now: float | None = None,
        event_id: str | None = None,
        observed_at: float | None = None,
        timestamp_source: str | None = None,
    ) -> bool:
        """Record verified music/media playback observation from Windows SMTC."""
        if not track_info or not isinstance(track_info, dict):
            return False
        if not track_info.get("has_active_playback"):
            return False

        title = str(track_info.get("title") or "").strip()
        artist = str(track_info.get("artist") or "").strip()
        album = str(track_info.get("album") or "").strip()
        app_id = str(track_info.get("app_id") or "").strip()
        status = str(track_info.get("playback_status") or "Playing").strip()

        parts = []
        if title:
            parts.append(f"«{title}»")
        if artist:
            parts.append(f"— {artist}")
        if album:
            parts.append(f"(альбом: {album})")
        if app_id:
            parts.append(f"[{app_id}]")

        track_str = " ".join(parts) if parts else "музыкальный трек"
        text = f"Воспроизводится трек: {track_str}"
        moment = time.monotonic() if now is None else float(now)

        self.note(
            "music",
            text,
            now=moment,
            metadata={
                "source": "windows_smtc",
                "event_id": event_id,
                "observed_at": observed_at,
                "timestamp_source": timestamp_source,
                "verified": True,
                "hypothesis": False,
                "smtc_verified": True,
                "title": title,
                "artist": artist,
                "album": album,
                "app_id": app_id,
                "playback_status": status,
                "confidence": 1.0,
            },
        )
        return True

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
                "hypothesis": self._is_channel_hypothesis(kind, entry[2]),
                **({"confidence": self._extract_confidence(entry[2])} if self._extract_confidence(entry[2]) is not None else {}),
                **({"provenance": self._extract_provenance(entry[2])} if self._extract_provenance(entry[2]) is not None else {}),
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

    def evaluate_cognitive_turn(
        self,
        *,
        affective_engine: Any | None = None,
        narrative_consolidator: Any | None = None,
        episodic_memory: Any | None = None,
        smtc_adapter: Any | None = None,
        spike_threshold: float = 0.35,
        silence_gap_threshold: float = 1.5,
        delta_arousal: float | None = None,
        force_proactive: bool = False,
        attention: Any | None = None,
        dnd: bool = False,
    ) -> CognitiveTurnDecision:
        """Evaluate cognitive arbitration: fast backchannel vs heavy proactive turn package."""
        is_dnd_active = bool(dnd)
        if attention is not None:
            if getattr(attention, "dnd", False) or getattr(attention, "is_dnd", False):
                is_dnd_active = True
        if is_dnd_active:
            return CognitiveTurnDecision(
                action="none",
                reason="dnd_active",
            )

        aff_state = affective_engine.get_state() if affective_engine is not None else {}
        blend_weights = aff_state.get("blend_weights", {})

        # 1. Fast-Path Backchanneling (High acoustic spike without waking LLM)
        is_spike = False
        if delta_arousal is not None and delta_arousal >= spike_threshold:
            is_spike = True
        elif aff_state.get("backchannel_ready"):
            is_spike = True

        if is_spike:
            cue = aff_state.get("backchannel_cue") or "Ого!"
            spike_expr = str(aff_state.get("dominant_expression", "surprised"))
            return CognitiveTurnDecision(
                action="backchannel",
                backchannel_cue=cue,
                vrm_blendshapes=blend_weights,
                dominant_expression=spike_expr,
                reason=f"Fast-path backchannel: acoustic spike delta >= {spike_threshold}",
            )

        # 2. Proactive Turn Package (Dialogue silence gap >= 1.5s)
        silence_sec = float(aff_state.get("silence_duration_sec", 0.0))
        if silence_sec >= silence_gap_threshold or force_proactive:
            episode_log = narrative_consolidator.get_last_story_line() if narrative_consolidator is not None else ""
            smtc_track = None
            if smtc_adapter is not None:
                try:
                    smtc_track = smtc_adapter.poll()
                except Exception:
                    smtc_track = None

            val = float(aff_state.get("valence", 0.0))
            arousal = float(aff_state.get("arousal", 0.0))
            expr = str(aff_state.get("dominant_expression", "neutral"))

            keyframe = None
            if narrative_consolidator is not None and getattr(narrative_consolidator, "_keyframes", None):
                keyframe = list(narrative_consolidator._keyframes)[-1]

            track_str = smtc_track.get("title", "нет") if (smtc_track and smtc_track.get("has_active_playback")) else "нет"
            prompt = (
                f"[ПРОАКТИВНЫЙ КОНТЕКСТ ДЛЯ SENSENOVA]\n"
                f"Сюжет: {episode_log or 'Без изменений'}\n"
                f"Музыка (SMTC): {track_str}\n"
                f"Эмоция: valence={val:+.2f}, arousal={arousal:+.2f} ({expr})\n"
                f"Пауза в диалоге: {silence_sec:.1f}с.\n"
                f"Задача: коротко и естественно прокомментируй происходящее одной фразой."
            )

            packet = {
                "episode_log": episode_log,
                "smtc_track": smtc_track,
                "valence": val,
                "arousal": arousal,
                "dominant_expression": expr,
                "blend_weights": blend_weights,
                "keyframe": keyframe,
                "silence_duration_sec": silence_sec,
                "prompt": prompt,
            }

            return CognitiveTurnDecision(
                action="proactive_turn",
                proactive_packet=packet,
                vrm_blendshapes=blend_weights,
                dominant_expression=expr,
                reason=f"Proactive turn package: dialogue silence gap {silence_sec:.1f}s >= {silence_gap_threshold}s",
            )

        return CognitiveTurnDecision(
            action="none",
            reason="No cognitive trigger threshold met",
        )


class SenseNovaPerceptionBridge:
    """Dispatches perception decisions between fast-path audio backchannel and SenseNova Loop 9B."""

    def __init__(
        self,
        sensenova_client: Any | None = None,
        perception_fusion: PerceptionFusion | None = None,
        *,
        tts_service: Any | None = None,
        broadcast_fn: Any | None = None,
        audio_player: Any | None = None,
        attention: Any | None = None,
    ) -> None:
        self.sensenova_client = sensenova_client
        self.perception_fusion = perception_fusion or PerceptionFusion()
        self.tts_service = tts_service
        self.broadcast_fn = broadcast_fn
        self.audio_player = audio_player
        self.attention = attention

    @staticmethod
    def _is_dnd_active(
        attention: Any | None,
        packet: dict[str, Any] | None,
        fusion: Any | None = None,
        client: Any | None = None,
        decision: Any | None = None,
    ) -> bool:
        if packet and isinstance(packet, dict):
            if packet.get("dnd") is True:
                return True
            att_pkt = packet.get("attention")
            if isinstance(att_pkt, dict) and att_pkt.get("dnd") is True:
                return True
            if getattr(att_pkt, "dnd", None) is True:
                return True

        if decision is not None:
            if getattr(decision, "dnd", None) is True:
                return True
            if getattr(decision, "reason", None) == "dnd_active":
                return True

        att_candidates = [
            attention,
            getattr(fusion, "attention", None) if fusion is not None else None,
            getattr(fusion, "dnd", None) if fusion is not None else None,
            getattr(client, "attention", None) if client is not None else None,
        ]
        for att in att_candidates:
            if att is True:
                return True
            if att is None:
                continue
            if isinstance(att, dict) and att.get("dnd") is True:
                return True
            if getattr(att, "dnd", None) is True:
                return True
            state_fn = getattr(att, "state", None)
            if callable(state_fn):
                try:
                    st = state_fn()
                    if isinstance(st, dict) and st.get("dnd") is True:
                        return True
                except Exception:
                    pass
        return False

    def process_turn_decision(
        self,
        decision: CognitiveTurnDecision,
        *,
        sensenova_client: Any | None = None,
        tts_service: Any | None = None,
        broadcast_fn: Any | None = None,
        audio_player: Any | None = None,
        attention: Any | None = None,
    ) -> dict[str, Any]:
        """Dispatch cognitive turn: fast-path backchannel vs heavy SenseNova turn."""
        client = sensenova_client or self.sensenova_client
        tts = tts_service or self.tts_service
        bcast = broadcast_fn or self.broadcast_fn
        player = audio_player or self.audio_player
        att = attention if attention is not None else self.attention

        if decision.action == "proactive_turn" and self._is_dnd_active(
            att,
            decision.proactive_packet,
            fusion=self.perception_fusion,
            client=client,
            decision=decision,
        ):
            return {
                "dispatched": False,
                "path": "suppressed_dnd",
                "speech_output": None,
                "llm_invoked": False,
                "text_generated": False,
                "queued": False,
                "audio_synthesized": False,
                "audio_delivered": False,
                "audio_playback_ack": "none",
                "transport_dispatched": False,
                "audio_bytes": 0,
                "reason": "dnd_active",
            }

        text_to_speak: str | None = None
        action_path = "none"
        llm_invoked = False
        proactive_packet = None

        if decision.action == "backchannel":
            action_path = "fast_backchannel"
            text_to_speak = decision.backchannel_cue

        elif decision.action == "proactive_turn":
            action_path = "sensenova_proactive"
            proactive_packet = decision.proactive_packet
            prompt = decision.proactive_packet.get("prompt", "") if decision.proactive_packet else ""
            reply_text = None
            if client is not None:
                try:
                    if hasattr(client, "handle_text"):
                        from .arbiter import TurnPriority
                        try:
                            res = client.handle_text(
                                prompt,
                                session_id="proactive_cognition",
                                correlation_id=f"proactive-{int(time.time() * 1000)}",
                                priority=TurnPriority.PROACTIVE,
                            )
                        except TypeError:
                            res = client.handle_text(
                                prompt,
                                session_id="proactive_cognition",
                                correlation_id=f"proactive-{int(time.time() * 1000)}",
                            )
                        if isinstance(res, dict):
                            if res.get("admitted") is False or res.get("status") == "deferred":
                                reply_text = None
                                llm_invoked = False
                            else:
                                raw_text = res.get("text")
                                if isinstance(raw_text, str) and raw_text.strip():
                                    reply_text = raw_text
                                    llm_invoked = True
                                else:
                                    reply_text = None
                                    llm_invoked = False
                        elif isinstance(res, str) and res.strip():
                            reply_text = res
                            llm_invoked = True
                        else:
                            reply_text = None
                            llm_invoked = False
                    elif hasattr(client, "complete"):
                        reply_text = str(client.complete(prompt))
                        llm_invoked = True
                    elif hasattr(client, "chat"):
                        reply_text = str(client.chat([{"role": "user", "content": prompt}]))
                        llm_invoked = True
                    elif callable(client) and not isinstance(client, type):
                        reply_text = str(client(prompt))
                        llm_invoked = True
                except Exception as exc:
                    logger.warning("SenseNova dispatch failed: %s", exc)
                    reply_text = None
                    llm_invoked = False
            text_to_speak = reply_text if (reply_text and reply_text.strip()) else None

        else:
            return {
                "dispatched": False,
                "path": "none",
                "speech_output": None,
                "llm_invoked": False,
                "text_generated": False,
                "queued": False,
                "audio_synthesized": False,
                "audio_delivered": False,
                "audio_playback_ack": "none",
                "transport_dispatched": False,
                "audio_bytes": 0,
                "reason": decision.reason,
            }

        text_generated = bool(text_to_speak and text_to_speak.strip())
        if not text_generated:
            return {
                "dispatched": False,
                "path": action_path,
                "speech_output": None,
                "llm_invoked": llm_invoked,
                "packet": proactive_packet,
                "text_generated": False,
                "queued": False,
                "audio_synthesized": False,
                "audio_delivered": False,
                "audio_playback_ack": "none",
                "transport_dispatched": False,
                "audio_bytes": 0,
                "reason": decision.reason,
            }

        # Handle speech synthesis & delivery
        wav_bytes: bytes | None = None
        audio_synthesized = False
        audio_delivered = False
        transport_dispatched = False
        queued = False
        audio_playback_ack = "none"

        # Single speech owner contract:
        # If a local audio_player is configured, the server owns speech playback directly:
        # it synthesizes audio via TTS and plays it through player.play_bytes / player(wav_bytes).
        # If no local player is provided, speech ownership belongs to the client (Electron desktop)
        # which polls /api/proactive and calls /api/tts/stream speakFinal.
        # To avoid duplicate synthesis and duplicate speech, the bridge MUST NOT synthesize
        # when speech is deferred to the client text queue.
        if player is not None:
            if tts is not None and text_to_speak:
                try:
                    wav_bytes = tts.synthesize(
                        text_to_speak,
                        emotion={
                            "expression": decision.dominant_expression,
                            "blendshapes": decision.vrm_blendshapes,
                        },
                    )
                    audio_synthesized = bool(wav_bytes and len(wav_bytes) > 0)
                except Exception as exc:
                    logger.warning("SenseNovaPerceptionBridge TTS synthesis failed: %s", exc)

            if wav_bytes:
                try:
                    if hasattr(player, "play_bytes") and callable(player.play_bytes):
                        player.play_bytes(wav_bytes)
                    elif callable(player):
                        player(wav_bytes)
                    else:
                        raise TypeError(f"audio_player {type(player)} is neither callable nor has play_bytes")
                    audio_delivered = True
                    audio_playback_ack = "confirmed"
                except Exception as exc:
                    logger.warning("SenseNovaPerceptionBridge audio player playback failed: %s", exc)
                    audio_delivered = False
                    audio_playback_ack = "none"

        # Dispatch to transport / client broadcast
        if bcast is not None and text_to_speak:
            try:
                # If local player already handled playback, instruct client not to speak again
                event_payload = {
                    "type": "audio" if (wav_bytes and audio_delivered) else "text",
                    "media_type": "audio/wav" if (wav_bytes and audio_delivered) else None,
                    "data_base64": base64.b64encode(wav_bytes).decode("ascii") if (wav_bytes and audio_delivered) else None,
                    "text": text_to_speak,
                    "speak": not audio_delivered,
                    "playback_active": audio_delivered,
                    "expression": decision.dominant_expression,
                    "blendshapes": decision.vrm_blendshapes,
                }
                bcast_result = bcast(event_payload)
                if isinstance(bcast_result, dict):
                    transport_dispatched = bool(bcast_result.get("accepted", False))
                    queued = bool(bcast_result.get("enqueued_proactive", False))
                elif bcast_result is True:
                    transport_dispatched = True
                else:
                    transport_dispatched = False
            except Exception as exc:
                logger.warning("SenseNovaPerceptionBridge broadcast failed: %s", exc)
                transport_dispatched = False

        if player is None:
            # Strictly False when audio playback is not confirmed by local player
            audio_delivered = False
            if queued:
                audio_playback_ack = "deferred_to_client"
            else:
                audio_playback_ack = "none"
        else:
            if audio_delivered:
                audio_playback_ack = "confirmed"
            else:
                audio_playback_ack = "none"

        return {
            "dispatched": True,
            "path": action_path,
            "speech_output": text_to_speak,
            "vrm_blendshapes": decision.vrm_blendshapes,
            "dominant_expression": decision.dominant_expression,
            "llm_invoked": llm_invoked,
            "packet": proactive_packet,
            "text_generated": text_generated,
            "transport_dispatched": transport_dispatched,
            "queued": queued,
            "audio_synthesized": audio_synthesized,
            "audio_delivered": audio_delivered,
            "audio_playback_ack": audio_playback_ack,
            "audio_bytes": len(wav_bytes) if wav_bytes else 0,
            "reason": decision.reason,
        }
