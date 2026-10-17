"""Sliding-window fusion of perception channels into one observation.

The companion senses the world through independent asynchronous lanes (VLM
screen captions, active-window titles, music state, speech). The brain should
receive ONE combined observation instead of a stream of per-sensor fragments:
this bounded assembler keeps the freshest text per channel (with per-channel
TTL) and renders it as a single Russian summary for the attention gate and
the JAWL event bridge. No LLM here: deterministic composition keeps the
transport cheap; an LLM composer can replace the renderer later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from threading import RLock

_TTL_SECONDS = {
    "screen": 90.0,
    "window": 120.0,
    "music": 240.0,
    "speech": 300.0,
    "eg2": 60.0,
    "media": 300.0,
}
_LABELS = {
    "window": "Окно",
    "music": "Звук",
    "speech": "Слышно",
    "eg2": "EG2",
    "media": "Медиа",
}


@dataclass
class PerceptionFusion:
    """Bounded latest-value store with TTLs and one combined renderer."""

    _items: dict[str, tuple[str, float]] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    media_buffer: Any | None = field(default=None, init=True, repr=False)
    eg2: Any | None = field(default=None, init=True, repr=False)

    def note(self, kind: str, text: str, *, now: float | None = None) -> None:
        clean = str(text or "").replace("\x00", "").strip()[:600]
        if not clean:
            return
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            self._items[str(kind)[:20]] = (clean, moment)

    def compose(self, screen_summary: str = "", *, now: float | None = None) -> str:
        """Render the freshest channels plus the current screen caption.

        When no explicit caption is supplied, the last VLM caption stored via
        :meth:`observe_screen` is rendered instead (while fresh).
        """
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
        parts: list[str] = []
        screen = str(screen_summary or "").strip()[:600]
        if not screen:
            stored = items.get("screen")
            if stored and moment - stored[1] <= _TTL_SECONDS.get("screen", 90.0):
                screen = stored[0]
        if screen:
            parts.append(f"Экран: {screen}")
        for kind in ("eg2", "media", "window", "music", "speech"):
            entry = items.get(kind)
            if not entry:
                continue
            text, stamp = entry
            if moment - stamp > _TTL_SECONDS.get(kind, 120.0):
                continue
            parts.append(f"{_LABELS.get(kind, kind)}: {text}")
        return ". ".join(parts)[:1200]

    def observe_screen(self, caption: str) -> str:
        """Store the latest VLM caption and return the fused observation."""
        self.note("screen", caption)
        return self.compose()

    def eg2_cortex(self) -> Any | None:
        """Return the attached cortex, loading it lazily if weights are available."""
        if self.eg2 is not None:
            return self.eg2
        try:
            from .eg2_sensory import DEFAULT_EG2_ONNX_ROOT, EmbeddingGemmaSensoryCortex

            if (DEFAULT_EG2_ONNX_ROOT / "onnx" / "model_q4.onnx").is_file():
                self.eg2 = EmbeddingGemmaSensoryCortex(DEFAULT_EG2_ONNX_ROOT)
        except Exception:  # noqa: BLE001 - perception must degrade without EG2
            self.eg2 = None
        return self.eg2

    def observe_media(self, observation: Any, *, now: float | None = None, modality: str | None = None) -> str:
        """Store a compact media observation and return fused text."""
        if self.media_buffer is not None:
            self.media_buffer.observe(observation, now=now, modality=modality)
        payload = observation.to_dict() if hasattr(observation, "to_dict") else (
            observation if isinstance(observation, dict) else {"summary": str(observation or "")}
        )
        summary = str(payload.get("summary") or payload.get("top_label") or "media").strip()[:240]
        self.note("media", summary, now=now)
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
        if cortex is not None and hasattr(cortex, "describe_displays"):
            try:
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
                audio_obs = cortex.classify_audio_wav(audio_wav_bytes) if cortex is not None else None
                if audio_obs is not None:
                    self.note("music", f"audio={audio_obs.top_label}", now=moment)
            except Exception:  # noqa: BLE001
                pass
        self.note("screen", description, now=moment)
        return self.compose(now=moment)

    def observe_eg2(self, observation: Any, *, now: float | None = None) -> str:
        """Store a compact EmbeddingGemma 2 observation and return fused text."""
        payload = observation.to_dict() if hasattr(observation, "to_dict") else (
            observation if isinstance(observation, dict) else {"summary": str(observation or "")}
        )
        parts = [str(payload.get("top_label") or payload.get("summary") or "eg2").strip()[:120]]
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
            self.media_buffer.observe(observation, now=now, modality="eg2")
        return self.compose(now=now)

    def state(self, *, now: float | None = None) -> dict[str, Any]:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            items = dict(self._items)
        fresh = {
            kind: {"text": text, "age_s": round(moment - stamp, 1)}
            for kind, (text, stamp) in items.items()
            if moment - stamp <= _TTL_SECONDS.get(kind, 120.0)
        }
        return {"fresh": fresh}
