"""Correlation context shared by the native JAWL Companion Gateway."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from math import isfinite
import re
from typing import Any, Mapping
from uuid import uuid4


_TURN_ID: ContextVar[str] = ContextVar("jawl_companion_turn_id", default="")
_TURN_STATE: ContextVar[Any] = ContextVar("jawl_companion_turn_state", default=None)
_CYCLE: ContextVar[Any] = ContextVar("jawl_native_delivery_cycle", default=None)
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


class CompanionTurnState:
    """Per-turn companion chat state bound around a correlated ReAct run.

    Carries the raw user message of the turn (for the fast-conversation lane)
    and a probe for durable Goal activity. The state contains no model context
    and is never published; it only guides wire-envelope decisions.
    """

    __slots__ = ("message", "_goal_active")

    def __init__(self, message: Any, goal_active: Any) -> None:
        self.message = str(message or "")[:4000]
        self._goal_active = goal_active

    def goal_active(self) -> bool:
        probe = self._goal_active
        if not callable(probe):
            return False
        try:
            return bool(probe())
        except Exception:
            return False


def bind_companion_turn_state(state: CompanionTurnState) -> Token:
    return _TURN_STATE.set(state)


def reset_companion_turn_state(token: Token) -> None:
    _TURN_STATE.reset(token)


def current_companion_turn_state() -> "CompanionTurnState | None":
    return _TURN_STATE.get()


_CYCLE_TURN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DELIVERY_INSTALL_ATTR = "__jawl_native_delivery_guard_installation__"
MISSING_REPLY_REASON = (
    "Native ReAct cycle ended without a correlated terminal response."
)


@dataclass
class CompanionCycleState:
    """Per-turn delivery cycle state bound around a correlated ReAct run.

    Tracks whether exactly one terminal gateway event confirmed the cycle,
    guards against repeated terminal broadcasts, and remembers the terminal
    client that spoke for the turn. Parent links keep nested runs isolated.
    """

    turn_id: str
    parent: Any = None
    terminal_event: str = ""
    terminal_client: Any = None
    closed: bool = False
    suppress_private_completion: bool = False
    terminal_result: Any = None
    policy_denied: bool = False
    native_loop: Any = None
    spoken_text: str = ""
    user_message: str = ""
    emit_lock: Any = field(default_factory=asyncio.Lock)
    broadcast_lock: Any = field(default_factory=asyncio.Lock)


def valid_cycle_turn_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if _CYCLE_TURN_ID.fullmatch(value) else ""


def bind_companion_cycle(state: CompanionCycleState) -> Token:
    return _CYCLE.set(state)


def reset_companion_cycle(token: Token) -> None:
    _CYCLE.reset(token)


def current_companion_cycle() -> "CompanionCycleState | None":
    return _CYCLE.get()


def find_active_cycle(turn_id: Any) -> "CompanionCycleState | None":
    turn_id = valid_cycle_turn_id(turn_id)
    state = _CYCLE.get()
    while state is not None:
        if not state.closed and state.turn_id == turn_id:
            return state
        state = state.parent
    return None


def record_cycle_terminal_event(
    client: Any, turn_id: Any, event_type: Any, result: Any
) -> None:
    current = _CYCLE.get()
    turn_id = valid_cycle_turn_id(turn_id)
    if (
        current is None
        or not turn_id
        or event_type not in {"assistant.final", "turn.error", "turn.cancelled"}
        or not isinstance(result, dict)
        or result.get("turn_id") != turn_id
        or result.get("type") != event_type
    ):
        return
    state = current
    while state is not None:
        if not state.closed and state.turn_id == turn_id:
            state.terminal_client = client
            state.terminal_event = event_type
            state.terminal_result = result
        state = state.parent


def remember_cycle_terminal_client(client: Any, turn_id: Any) -> None:
    current = _CYCLE.get()
    turn_id = valid_cycle_turn_id(turn_id)
    state = current
    while state is not None:
        if not state.closed and state.turn_id == turn_id:
            state.terminal_client = client
        state = state.parent


async def emit_active_delta(text: str, *, event_format: str = "speech") -> bool:
    """Emit one bounded ``assistant.delta`` for the active correlated cycle.

    The reply sentence is already extracted from the partially generated JSON
    envelope, so the Companion can start speaking before the envelope closes.
    Never raises into the model path.
    """
    fragment = str(text or "").strip()
    if not fragment:
        return False
    state = _CYCLE.get()
    if state is None or state.closed or state.terminal_event:
        return False
    # A later ReAct step may repeat the same sentence; speak each sentence once.
    if fragment in state.spoken_text:
        return False
    state.spoken_text = (state.spoken_text + " " + fragment)[-4000:]
    client = state.terminal_client
    if client is None:
        installation = vars(type(state.native_loop)).get(_DELIVERY_INSTALL_ATTR)
        if installation is None:
            return False
        try:
            client = installation.terminal_client_resolver(state.native_loop)
        except Exception:
            return False
    emit = getattr(client, "emit_gateway_event", None)
    if not callable(emit):
        return False
    try:
        await emit(
            state.turn_id,
            "assistant.delta",
            {"text": fragment[:2000], "format": str(event_format)[:20]},
        )
        return True
    except Exception:
        return False


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
