"""Text gateway used before the real JAWL adapter is connected."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
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
        if not clean:
            answer = "Я не услышала текст. Попробуй повторить команду."
            speak = False
            emotion = {"id": "confused", "intensity": 0.25, "confidence": 1.0}
        else:
            try:
                if self.responder:
                    responder_method = getattr(self.responder, "respond", None)
                    if callable(responder_method):
                        answer = responder_method(clean, cancel_event=token.cancel_event)
                    else:
                        answer = self.responder(clean)
                else:
                    answer = self._mock_response(clean)
                self._brain_status = "connected" if self.responder else "mock"
            except JawlTurnCancelled:
                self._brain_status = "cancelled"
                answer = "Ответ отменён новым сообщением."
                speak = False
                emotion = {"id": "neutral", "intensity": 0.0, "confidence": 1.0}
            except (ConnectionError, OSError, TimeoutError):
                self._brain_status = "offline_fallback"
                answer = "JAWL сейчас недоступен. Я сохранила текстовый fallback и готова продолжить после восстановления связи."
                speak = True
                emotion = {"id": "concerned", "intensity": 0.35, "confidence": 1.0}
            else:
                speak = True
                emotion = {"id": "attentive", "intensity": 0.45, "confidence": 0.8}

        try:
            envelope = self._build_envelope(
                clean, answer, response_id, turn_id, speak=speak, emotion=emotion,
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
        try:
            if not clean:
                answer = "РЇ РЅРµ СѓСЃР»С‹С€Р°Р»Р° С‚РµРєСЃС‚. РџРѕРїСЂРѕР±СѓР№ РїРѕРІС‚РѕСЂРёС‚СЊ РєРѕРјР°РЅРґСѓ."
                speak = False
                emotion = {"id": "confused", "intensity": 0.25, "confidence": 1.0}
            else:
                chunks: list[str] = []
                try:
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
                    answer = "РћС‚РІРµС‚ РѕС‚РјРµРЅС‘РЅ РЅРѕРІС‹Рј СЃРѕРѕР±С‰РµРЅРёРµРј."
                    speak = False
                    emotion = {"id": "neutral", "intensity": 0.0, "confidence": 1.0}
                except (ConnectionError, OSError, TimeoutError):
                    if chunks:
                        raise
                    self._brain_status = "offline_fallback"
                    answer = "JAWL СЃРµР№С‡Р°СЃ РЅРµРґРѕСЃС‚СѓРїРµРЅ. РЇ СЃРѕС…СЂР°РЅРёР»Р° С‚РµРєСЃС‚РѕРІС‹Р№ fallback Рё РіРѕС‚РѕРІР° РїСЂРѕРґРѕР»Р¶РёС‚СЊ РїРѕСЃР»Рµ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ СЃРІСЏР·Рё."
                    speak = True
                    emotion = {"id": "concerned", "intensity": 0.35, "confidence": 1.0}
                    yield {"type": "delta", "text": answer, "turn_id": token.turn_id}

            envelope = self._build_envelope(
                clean, answer, response_id, token.turn_id, speak=speak, emotion=emotion,
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
                "state": "speaking" if speak else "idle",
            },
            "voice": {"provider": "not_connected", "voice_id": "main_ru", "rate": 1.0},
            "actions": [],
            "interruptible": True,
            "proactive": False,
        }
        validate_response_envelope(envelope)
        return envelope

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
