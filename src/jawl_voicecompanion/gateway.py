"""Text gateway used before the real JAWL adapter is connected."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .hostos_policy import HostOSPolicy


_REQUIRED_ENVELOPE_FIELDS = (
    "schema_version",
    "response_id",
    "turn_id",
    "text",
    "speak",
    "emotion",
    "avatar",
    "actions",
    "interruptible",
    "proactive",
)


def validate_response_envelope(envelope: dict[str, Any]) -> None:
    """Validate the stable shape before a response leaves the gateway."""
    missing = [field for field in _REQUIRED_ENVELOPE_FIELDS if field not in envelope]
    if missing:
        raise ValueError(f"response envelope is missing fields: {', '.join(missing)}")
    if envelope["schema_version"] != 1:
        raise ValueError("unsupported response envelope schema")
    if not isinstance(envelope["text"], str):
        raise ValueError("response text must be a string")
    for field in ("speak", "interruptible", "proactive"):
        if not isinstance(envelope[field], bool):
            raise ValueError(f"{field} must be boolean")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TextGateway:
    """A deterministic text surface with a mock brain and real policy state."""

    policy: HostOSPolicy = field(default_factory=HostOSPolicy)
    responder: Callable[[str], str] | None = None
    brain_name: str = "phase1_mock_brain"
    _brain_status: str = field(default="mock", init=False, repr=False)
    _turns: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def handle_text(self, text: str, session_id: str = "local") -> dict[str, Any]:
        clean = str(text or "").strip()
        response_id = str(uuid4())
        turn_id = str(uuid4())
        if not clean:
            answer = "Я не услышала текст. Попробуй повторить команду."
            speak = False
            emotion = {"id": "confused", "intensity": 0.25, "confidence": 1.0}
        else:
            try:
                answer = self.responder(clean) if self.responder else self._mock_response(clean)
                self._brain_status = "connected" if self.responder else "mock"
            except (ConnectionError, OSError, TimeoutError):
                self._brain_status = "offline_fallback"
                answer = "JAWL сейчас недоступен. Я сохранила текстовый fallback и готова продолжить после восстановления связи."
            speak = True
            emotion = {"id": "attentive", "intensity": 0.45, "confidence": 0.8}

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
                "state": "speaking" if speak else "idle",
            },
            "voice": {"provider": "not_connected", "voice_id": "main_ru", "rate": 1.0},
            "actions": [],
            "interruptible": True,
            "proactive": False,
        }
        validate_response_envelope(envelope)
        self._turns.append({"created_at": _now(), "session_id": session_id, "user": clean, "response": envelope})
        del self._turns[:-50]
        return envelope

    def health(self) -> dict[str, Any]:
        return {
            "status": "degraded",
            "mode": self.brain_name,
            "components": {
                "jawl": self._responder_status(),
                "voicemem": "not_connected",
                "tts": "not_connected",
                "hostos": "policy_only_dry_run",
            },
        }

    def _responder_status(self) -> str:
        if not self.responder:
            return "not_connected"
        status = getattr(self.responder, "status", None)
        return status() if callable(status) else self._brain_status

    def state(self) -> dict[str, Any]:
        return {
            "policy": self.policy.snapshot(),
            "recent_turns": len(self._turns),
            "last_turn": self._turns[-1] if self._turns else None,
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
