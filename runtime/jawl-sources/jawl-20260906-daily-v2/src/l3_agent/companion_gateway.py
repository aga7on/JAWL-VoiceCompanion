"""Correlation context shared by the native JAWL Companion Gateway."""

from __future__ import annotations

from contextvars import ContextVar, Token
from math import isfinite
import re
from typing import Any, Mapping
from uuid import uuid4


_TURN_ID: ContextVar[str] = ContextVar("jawl_companion_turn_id", default="")
_SPEECH_SINK: ContextVar["SpeechDeltaSink | None"] = ContextVar(
    "jawl_companion_speech_sink", default=None
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_AVATAR_STATES = {"idle", "listening", "thinking", "speaking", "error"}


class SpeechDeltaSink:
    """Per-turn sink for user-visible speech deltas.

    Fed by the provider speech-first tee (``llm/speech_first`` extracts
    complete reply sentences from the partially streamed JSON envelope).
    Each sentence is published once as ``COMPANION_SPEECH_DELTA`` so the
    terminal bridge can start TTS before the envelope closes.  Private
    envelope fields never reach this sink.
    """

    def __init__(self, event_bus: Any, turn_id: str) -> None:
        self._event_bus = event_bus
        self.turn_id = str(turn_id or "")[:128]
        self._spoken = ""
        self._closed = False

    async def emit(self, text: str) -> bool:
        fragment = str(text or "").strip()
        if not fragment or self._closed or not self.turn_id:
            return False
        # A later ReAct step may repeat the same sentence; speak each once.
        if fragment in self._spoken:
            return False
        self._spoken = (self._spoken + " " + fragment)[-4000:]
        try:
            await self._event_bus.publish(
                _speech_delta_event(),
                companion_turn_id=self.turn_id,
                speech_text=fragment[:2000],
                event_format="speech",
            )
        except Exception:
            return False
        return True

    def close(self) -> None:
        self._closed = True


def _speech_delta_event() -> Any:
    # Imported lazily: utils.event.registry pulls pydantic, and this module
    # stays importable for pure correlation contexts.
    from src.utils.event.registry import Events

    return Events.COMPANION_SPEECH_DELTA


def bind_speech_sink(sink: "SpeechDeltaSink | None") -> Token:
    return _SPEECH_SINK.set(sink)


def reset_speech_sink(token: Token) -> None:
    _SPEECH_SINK.reset(token)


def current_speech_sink() -> "SpeechDeltaSink | None":
    return _SPEECH_SINK.get()


def set_companion_turn_id(value: Any) -> Token[str]:
    """Bind one transport turn to the current ReAct task."""

    return _TURN_ID.set(str(value or "")[:128])


def reset_companion_turn_id(token: Token[str]) -> None:
    _TURN_ID.reset(token)


def current_companion_turn_id() -> str:
    return _TURN_ID.get()


def _bounded_text(
    value: Any, field: str, *, allow_empty: bool = False, limit: int = 128
) -> None:
    if not isinstance(value, str) or "\x00" in value or len(value) > limit:
        raise ValueError(f"{field} is invalid or exceeds its limit")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must not be empty")


def _unit_interval(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    if not isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")


def validate_response_envelope(
    envelope: Mapping[str, Any], *, expected_turn_id: str | None = None
) -> None:
    """Validate the bounded response contract before it leaves native JAWL."""

    required = {
        "schema_version", "response_id", "turn_id", "text", "speak",
        "emotion", "avatar", "voice", "actions", "interruptible", "proactive",
    }
    if not isinstance(envelope, Mapping) or set(envelope) != required:
        raise ValueError("response envelope fields are incomplete or unknown")
    if envelope["schema_version"] != 1 or isinstance(envelope["schema_version"], bool):
        raise ValueError("unsupported response envelope schema")
    for field in ("response_id", "turn_id"):
        _bounded_text(envelope[field], field)
        if not _SAFE_ID.fullmatch(envelope[field]):
            raise ValueError(f"{field} contains unsupported characters")
    if expected_turn_id is not None and envelope["turn_id"] != expected_turn_id:
        raise ValueError("response turn_id does not match the active turn")
    _bounded_text(envelope["text"], "text", allow_empty=True, limit=16000)
    for field in ("speak", "interruptible", "proactive"):
        if not isinstance(envelope[field], bool):
            raise ValueError(f"{field} must be boolean")

    emotion = envelope["emotion"]
    if not isinstance(emotion, Mapping) or set(emotion) != {"id", "intensity", "confidence"}:
        raise ValueError("emotion shape is invalid")
    _bounded_text(emotion["id"], "emotion.id")
    _unit_interval(emotion["intensity"], "emotion.intensity")
    _unit_interval(emotion["confidence"], "emotion.confidence")

    avatar = envelope["avatar"]
    if not isinstance(avatar, Mapping) or set(avatar) != {"expression", "motion", "state"}:
        raise ValueError("avatar shape is invalid")
    for field in ("expression", "motion", "state"):
        _bounded_text(avatar[field], f"avatar.{field}")
    if avatar["state"] not in _AVATAR_STATES:
        raise ValueError("avatar.state is unsupported")

    voice = envelope["voice"]
    if not isinstance(voice, Mapping) or not {"provider", "voice_id", "rate"}.issubset(voice):
        raise ValueError("voice shape is invalid")
    for field in ("provider", "voice_id"):
        _bounded_text(voice[field], f"voice.{field}")
    rate = voice["rate"]
    if (
        isinstance(rate, bool)
        or not isinstance(rate, (int, float))
        or not isfinite(float(rate))
        or not 0.25 <= float(rate) <= 4.0
    ):
        raise ValueError("voice.rate is invalid")
    if "style" in voice:
        _bounded_text(voice["style"], "voice.style", allow_empty=True, limit=240)

    actions = envelope["actions"]
    if not isinstance(actions, list) or len(actions) > 32:
        raise ValueError("actions must be a bounded array")
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping) or len(action) > 32:
            raise ValueError(f"actions[{index}] is invalid")
        if "requested_access_level" in action:
            raise ValueError("response actions cannot request access level")


def default_response(text: str, turn_id: str) -> dict[str, Any]:
    """Build neutral metadata for legacy JAWL terminal messages."""

    clean = str(text or "")
    response = {
        "schema_version": 1,
        "response_id": f"resp-{uuid4().hex}",
        "turn_id": turn_id,
        "text": clean,
        "speak": bool(clean.strip()),
        "emotion": {"id": "attentive", "intensity": 0.45, "confidence": 0.8},
        "avatar": {
            "expression": "attentive",
            "motion": "soft_nod",
            "state": "speaking" if clean.strip() else "idle",
        },
        "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
        "actions": [],
        "interruptible": True,
        "proactive": False,
    }
    validate_response_envelope(response, expected_turn_id=turn_id)
    return response
