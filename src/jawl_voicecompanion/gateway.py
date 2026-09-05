"""Text gateway used before the real JAWL adapter is connected."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Callable, Iterator, Mapping
import re
from uuid import uuid4

from .hostos_policy import HostOSPolicy
from .arbiter import TurnArbiter, TurnPriority
from .jawl_adapter import JawlTurnCancelled
from .jawl_web import JawlWebAdapter


_REQUIRED_ENVELOPE_FIELDS = (
    "schema_version",
    "response_id",
    "turn_id",
    "text",
    "speak",
    "emotion",
    "avatar",
    "voice",
    "actions",
    "interruptible",
    "proactive",
)
_ALLOWED_ENVELOPE_FIELDS = frozenset(_REQUIRED_ENVELOPE_FIELDS)
_ALLOWED_AVATAR_STATES = frozenset({"idle", "listening", "thinking", "speaking", "error"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_ENVELOPE_TEXT = 16_000
_MAX_ACTIONS = 32
_MAX_ACTION_KEYS = 32


def _bounded_text(value: Any, field: str, *, allow_empty: bool = False, limit: int = 128) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if "\x00" in value or len(value) > limit or (not allow_empty and not value.strip()):
        raise ValueError(f"{field} is empty or exceeds its limit")


def _unit_interval(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{field} must be a finite number")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")


def validate_response_envelope(envelope: dict[str, Any]) -> None:
    """Validate the bounded v1 shape before a response leaves the gateway."""
    if not isinstance(envelope, dict):
        raise ValueError("response envelope must be an object")
    missing = [field for field in _REQUIRED_ENVELOPE_FIELDS if field not in envelope]
    if missing:
        raise ValueError(f"response envelope is missing fields: {', '.join(missing)}")
    unknown = sorted(set(envelope) - _ALLOWED_ENVELOPE_FIELDS)
    if unknown:
        raise ValueError(f"response envelope contains unknown fields: {', '.join(unknown)}")
    if isinstance(envelope["schema_version"], bool) or envelope["schema_version"] != 1:
        raise ValueError("unsupported response envelope schema")
    for field in ("response_id", "turn_id"):
        _bounded_text(envelope[field], field, limit=128)
        if not _SAFE_ID.fullmatch(envelope[field]):
            raise ValueError(f"{field} contains unsupported characters")
    _bounded_text(envelope["text"], "response text", allow_empty=True, limit=_MAX_ENVELOPE_TEXT)
    for field in ("speak", "interruptible", "proactive"):
        if not isinstance(envelope[field], bool):
            raise ValueError(f"{field} must be boolean")

    emotion = envelope["emotion"]
    if not isinstance(emotion, Mapping):
        raise ValueError("emotion must be an object")
    for field in ("id", "intensity", "confidence"):
        if field not in emotion:
            raise ValueError(f"emotion is missing {field}")
    _bounded_text(emotion["id"], "emotion.id")
    _unit_interval(emotion["intensity"], "emotion.intensity")
    _unit_interval(emotion["confidence"], "emotion.confidence")

    avatar = envelope["avatar"]
    if not isinstance(avatar, Mapping):
        raise ValueError("avatar must be an object")
    for field in ("expression", "motion", "state"):
        if field not in avatar:
            raise ValueError(f"avatar is missing {field}")
        _bounded_text(avatar[field], f"avatar.{field}")
    if avatar["state"] not in _ALLOWED_AVATAR_STATES:
        raise ValueError("avatar.state is unsupported")

    voice = envelope["voice"]
    if not isinstance(voice, Mapping):
        raise ValueError("voice must be an object")
    for field in ("provider", "voice_id", "rate"):
        if field not in voice:
            raise ValueError(f"voice is missing {field}")
    _bounded_text(voice["provider"], "voice.provider")
    _bounded_text(voice["voice_id"], "voice.voice_id")
    if isinstance(voice["rate"], bool) or not isinstance(voice["rate"], (int, float)):
        raise ValueError("voice.rate must be numeric")
    if not isfinite(float(voice["rate"])) or not 0.25 <= float(voice["rate"]) <= 4.0:
        raise ValueError("voice.rate must be between 0.25 and 4")
    if "style" in voice:
        _bounded_text(voice["style"], "voice.style", allow_empty=True, limit=240)

    actions = envelope["actions"]
    if not isinstance(actions, list) or len(actions) > _MAX_ACTIONS:
        raise ValueError("actions must be a bounded array")
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping) or len(action) > _MAX_ACTION_KEYS:
            raise ValueError(f"actions[{index}] must be a bounded object")
        if "requested_access_level" in action:
            raise ValueError("model actions cannot request an access level")
        for field in ("action_id", "tool", "type"):
            if field in action:
                _bounded_text(action[field], f"actions[{index}].{field}")
        for field in ("arguments", "target"):
            if field in action and not isinstance(action[field], Mapping):
                raise ValueError(f"actions[{index}].{field} must be an object")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TextGateway:
    """A deterministic text surface with a mock brain and real policy state."""

    policy: HostOSPolicy = field(default_factory=HostOSPolicy)
    responder: Callable[[str], str] | None = None
    jawl_web: JawlWebAdapter | None = None
    brain_name: str = "phase1_mock_brain"
    arbiter: TurnArbiter = field(default_factory=TurnArbiter)
    _brain_status: str = field(default="mock", init=False, repr=False)
    _turns: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def handle_text(self, text: str, session_id: str = "local") -> dict[str, Any]:
        clean = str(text or "").strip()
        response_id = str(uuid4())
        token = self.arbiter.begin(TurnPriority.USER_FINAL)
        turn_id = token.turn_id
        native_envelope: dict[str, Any] | None = None
        terminal_error = False
        if not clean:
            answer = "Я не услышала текст. Попробуй повторить команду."
            speak = False
            emotion = {"id": "confused", "intensity": 0.25, "confidence": 1.0}
        else:
            try:
                if self.responder:
                    envelope_method = getattr(self.responder, "respond_envelope", None)
                    if getattr(self.responder, "supports_native_envelope", False) and callable(envelope_method):
                        candidate = envelope_method(clean, cancel_event=token.cancel_event)
                        if not isinstance(candidate, dict):
                            raise ValueError("native responder returned a non-object envelope")
                        native_envelope = dict(candidate)
                        validate_response_envelope(native_envelope)
                        answer = native_envelope.get("text")
                    else:
                        responder_method = getattr(self.responder, "respond", None)
                        if callable(responder_method):
                            answer = responder_method(clean, cancel_event=token.cancel_event)
                        else:
                            answer = self.responder(clean)
                else:
                    answer = self._mock_response(clean)
                if not isinstance(answer, str) or not answer.strip() or len(answer) > _MAX_ENVELOPE_TEXT:
                    raise ValueError("responder returned empty or oversized text")
                self._brain_status = "connected" if self.responder else "mock"
            except JawlTurnCancelled:
                self._brain_status = "cancelled"
                native_envelope = None
                answer = "Ответ отменён новым сообщением."
                speak = False
                emotion = {"id": "neutral", "intensity": 0.0, "confidence": 1.0}
            except (ConnectionError, OSError, TimeoutError, ValueError):
                self._brain_status = "offline_fallback"
                native_envelope = None
                terminal_error = bool(
                    self.responder and getattr(self.responder, "supports_native_envelope", False)
                )
                answer = "JAWL сейчас недоступен. Я сохранила текстовый fallback и готова продолжить после восстановления связи."
                speak = True
                emotion = {"id": "concerned", "intensity": 0.35, "confidence": 1.0}
                if terminal_error:
                    answer = "JAWL недоступен: текущий turn завершён с ошибкой."
                    speak = False
                    emotion = {"id": "error", "intensity": 0.35, "confidence": 1.0}
            else:
                speak = True
                emotion = {"id": "attentive", "intensity": 0.45, "confidence": 0.8}

        try:
            envelope = (
                self._preserve_native_envelope(native_envelope)
                if native_envelope is not None
                else self._build_envelope(clean, answer, response_id, turn_id, speak=speak, emotion=emotion)
            )
            self._record_turn(session_id, clean, envelope)
            return envelope
        finally:
            self.arbiter.complete(token)

    def stream_text(self, text: str, session_id: str = "local") -> Iterator[dict[str, Any]]:
        """Stream safe responder deltas and finish with one canonical envelope."""
        clean = str(text or "").strip()
        response_id = str(uuid4())
        token = self.arbiter.begin(TurnPriority.USER_FINAL)
        native_envelope: dict[str, Any] | None = None
        terminal_error = False
        try:
            if not clean:
                answer = "Я не услышала текст. Попробуй повторить команду."
                speak = False
                emotion = {"id": "confused", "intensity": 0.25, "confidence": 1.0}
            else:
                chunks: list[str] = []
                try:
                    envelope_method = getattr(self.responder, "respond_envelope", None) if self.responder else None
                    if self.responder and getattr(self.responder, "supports_native_envelope", False) and callable(envelope_method):
                        candidate = envelope_method(clean, cancel_event=token.cancel_event)
                        if not isinstance(candidate, dict):
                            raise ValueError("native responder returned a non-object envelope")
                        native_envelope = dict(candidate)
                        validate_response_envelope(native_envelope)
                        answer = native_envelope.get("text")
                        if not isinstance(answer, str) or not answer.strip():
                            raise ValueError("native responder returned empty text")
                        yield {"type": "delta", "text": answer, "turn_id": token.turn_id}
                    else:
                        stream_method = getattr(self.responder, "stream", None) if self.responder else None
                        if callable(stream_method):
                            source = stream_method(clean, cancel_event=token.cancel_event)
                            for chunk in source:
                                if token.cancel_event.is_set():
                                    raise JawlTurnCancelled()
                                if not isinstance(chunk, str):
                                    raise ValueError("stream responder must yield strings")
                                if chunk:
                                    chunks.append(chunk)
                                    yield {"type": "delta", "text": chunk, "turn_id": token.turn_id}
                            answer = "".join(chunks).strip()
                            if not answer:
                                raise ConnectionError("stream responder returned empty text")
                        elif self.responder:
                            responder_method = getattr(self.responder, "respond", None)
                            answer = responder_method(clean, cancel_event=token.cancel_event) if callable(responder_method) else self.responder(clean)
                            if not isinstance(answer, str) or not answer.strip():
                                raise ConnectionError("responder returned empty text")
                            yield {"type": "delta", "text": answer, "turn_id": token.turn_id}
                        else:
                            answer = self._mock_response(clean)
                            yield {"type": "delta", "text": answer, "turn_id": token.turn_id}
                    self._brain_status = "connected" if self.responder else "mock"
                    speak = True
                    emotion = {"id": "attentive", "intensity": 0.45, "confidence": 0.8}
                except JawlTurnCancelled:
                    self._brain_status = "cancelled"
                    native_envelope = None
                    answer = "Ответ отменён новым сообщением."
                    speak = False
                    emotion = {"id": "neutral", "intensity": 0.0, "confidence": 1.0}
                except (ConnectionError, OSError, TimeoutError, ValueError):
                    if chunks:
                        raise
                    self._brain_status = "offline_fallback"
                    native_envelope = None
                    terminal_error = bool(
                        self.responder and getattr(self.responder, "supports_native_envelope", False)
                    )
                    answer = "JAWL сейчас недоступен. Я сохранила текстовый fallback и готова продолжить после восстановления связи."
                    speak = True
                    emotion = {"id": "concerned", "intensity": 0.35, "confidence": 1.0}
                    if terminal_error:
                        answer = "JAWL недоступен: текущий turn завершён с ошибкой."
                        speak = False
                        emotion = {"id": "error", "intensity": 0.35, "confidence": 1.0}
                        yield {"type": "error", "error": "native_turn_failed", "turn_id": token.turn_id}
                    else:
                        yield {"type": "delta", "text": answer, "turn_id": token.turn_id}

            envelope = (
                self._preserve_native_envelope(native_envelope)
                if native_envelope is not None
                else self._build_envelope(clean, answer, response_id, token.turn_id, speak=speak, emotion=emotion)
            )
            self._record_turn(session_id, clean, envelope)
            yield {"type": "final", "response": envelope}
        finally:
            self.arbiter.complete(token)

    def _build_envelope(
        self,
        clean: str,
        answer: str,
        response_id: str,
        turn_id: str,
        *,
        speak: bool,
        emotion: dict[str, Any],
    ) -> dict[str, Any]:
        envelope = {
            "schema_version": 1,
            "response_id": response_id,
            "turn_id": turn_id,
            "text": answer,
            "speak": speak,
            "emotion": emotion,
            "avatar": {
                "expression": emotion["id"],
                "motion": "soft_nod" if clean else "blink",
                "state": "error" if emotion.get("id") == "error" else ("speaking" if speak else "idle"),
            },
            "voice": {"provider": "not_connected", "voice_id": "main_ru", "rate": 1.0},
            "actions": [],
            "interruptible": True,
            "proactive": False,
        }
        validate_response_envelope(envelope)
        return envelope

    @staticmethod
    def _preserve_native_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
        """Validate and pass through JAWL's canonical envelope unchanged."""
        result = dict(envelope)
        validate_response_envelope(result)
        return result

    def _record_turn(self, session_id: str, clean: str, envelope: dict[str, Any]) -> None:
        self._turns.append({"created_at": _now(), "session_id": session_id, "user": clean, "response": envelope})
        del self._turns[:-50]

    def health(self) -> dict[str, Any]:
        return {
            "status": "degraded",
            "mode": self.brain_name,
            "components": {
                "jawl": self._responder_status(),
                "jawl_web": self._jawl_web_status(),
                "voicemem": "not_connected",
                "tts": "not_connected",
                "hostos": "policy_only_dry_run",
            },
        }

    def _responder_status(self) -> str:
        if not self.responder:
            return "not_connected"
        chat_status = getattr(self.responder, "chat_status", None)
        if callable(chat_status):
            return chat_status()
        status = getattr(self.responder, "status", None)
        return status() if callable(status) else self._brain_status

    def _jawl_web_status(self) -> str:
        if self.jawl_web is None:
            return "not_configured"
        return self.jawl_web.status()

    def state(self) -> dict[str, Any]:
        return {
            "policy": self.policy.snapshot(),
            "recent_turns": len(self._turns),
            "last_turn": self._turns[-1] if self._turns else None,
            "turn_arbiter": self.arbiter.state(),
        }

    def audit(self) -> list[dict[str, Any]]:
        return self.policy.audit()

    @staticmethod
    def _mock_response(text: str) -> str:
        lowered = text.casefold()
        if any(greeting in lowered for greeting in ("привет", "здравствуй", "добрый день")):
            return "Привет. Я на связи и готова помочь."
        if "уров" in lowered and "доступ" in lowered:
            return "Текущий уровень доступа виден в панели управления. По умолчанию включён SANDBOX."
        return f"Я получила сообщение: «{text}». Текстовый контур работает, а JAWL пока подключается."
