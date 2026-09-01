"""Replaceable delayed triage providers for ambient secondary memory.

Providers return a small, validated JSON candidate. They never receive tools,
never create user turns and never receive raw audio or frames.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class AmbientTriageUnavailable(RuntimeError):
    """Raised when a delayed triage provider is unavailable or unsafe."""


class AmbientTriageProvider(Protocol):
    name: str

    def triage(self, observations: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


_IMPORTANCE = {"ignore", "retain", "promote_candidate"}
_SOURCES = {"system_audio", "screen", "mixed"}
TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["importance", "summary", "topics", "confidence", "source", "source_event_ids"],
    "properties": {
        "importance": {"type": "string", "enum": sorted(_IMPORTANCE)},
        "summary": {"type": "string", "maxLength": 600},
        "topics": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "source": {"type": "string", "enum": sorted(_SOURCES)},
        "source_event_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
    },
}


def validate_triage_result(result: Any, event_ids: set[str]) -> dict[str, Any]:
    """Fail closed and return only the bounded fields accepted by memory."""
    if not isinstance(result, dict):
        raise AmbientTriageUnavailable("triage result is not an object")
    importance = result.get("importance")
    summary = result.get("summary")
    topics = result.get("topics")
    confidence = result.get("confidence")
    source = result.get("source")
    source_event_ids = result.get("source_event_ids")
    if importance not in _IMPORTANCE or not isinstance(summary, str) or not summary.strip():
        raise AmbientTriageUnavailable("triage result has invalid importance or summary")
    if not isinstance(topics, list) or len(topics) > 5 or any(not isinstance(item, str) for item in topics):
        raise AmbientTriageUnavailable("triage result has invalid topics")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise AmbientTriageUnavailable("triage result has invalid confidence")
    if source not in _SOURCES or not isinstance(source_event_ids, list) or not source_event_ids:
        raise AmbientTriageUnavailable("triage result has invalid provenance")
    ids = [item for item in source_event_ids if isinstance(item, str)]
    if len(ids) != len(source_event_ids) or len(set(ids)) != len(ids) or not set(ids) <= event_ids:
        raise AmbientTriageUnavailable("triage result cites an unknown event")
    return {
        "importance": importance,
        "summary": summary.replace("\x00", "").strip()[:600],
        "topics": [item.replace("\x00", "").strip()[:40] for item in topics][:5],
        "confidence": round(float(confidence), 3),
        "source": source,
        "source_event_ids": ids[:32],
    }


class OllamaTriageProvider:
    """CPU-first Ollama adapter; no dependency on the Ollama Python package."""

    name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        keep_alive: str | int = 0,
        num_ctx: int = 4096,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.model = str(model).strip()
        if not self.model:
            raise ValueError("ambient triage model is required")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = max(1.0, min(float(timeout), 600.0))
        self.keep_alive = keep_alive
        self.num_ctx = max(512, min(int(num_ctx), 32768))
        self._opener = opener

    def triage(self, observations: Sequence[dict[str, Any]]) -> dict[str, Any]:
        safe = [self._safe_observation(item) for item in list(observations)[:64]]
        if not safe:
            raise AmbientTriageUnavailable("triage batch is empty")
        event_ids = {item["event_id"] for item in safe}
        prompt = (
            "Сожми наблюдения в один кандидат вторичной памяти. Не выдумывай факты. "
            "Если данных недостаточно, importance=ignore. Верни только JSON по схеме.\n"
            + json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Ты модуль отложенного triage. Инструменты запрещены."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": TRIAGE_SCHEMA,
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_gpu": 0},
            "keep_alive": self.keep_alive,
        }
        request = Request(
            urljoin(self.base_url, "api/chat"),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = raw.get("message", {}).get("content")
            result = json.loads(content) if isinstance(content, str) else content
            return validate_triage_result(result, event_ids)
        except (
            AmbientTriageUnavailable,
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            if isinstance(exc, AmbientTriageUnavailable):
                raise
            raise AmbientTriageUnavailable(f"ollama triage failed: {type(exc).__name__}") from exc

    @staticmethod
    def _safe_observation(item: dict[str, Any]) -> dict[str, Any]:
        payload = item.get("payload") if isinstance(item, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        return {
            "event_id": str(item.get("event_id") or "")[:120],
            "stream": str(payload.get("stream") or "")[:32],
            "text": str(payload.get("text") or payload.get("summary") or "").replace("\x00", "")[:1200],
            "confidence": payload.get("confidence", 0.5),
            "source_app": str(payload.get("source_app") or "")[:80],
            "observed_at": str(payload.get("observed_at") or "")[:80],
        }


__all__ = [
    "AmbientTriageProvider",
    "AmbientTriageUnavailable",
    "OllamaTriageProvider",
    "TRIAGE_SCHEMA",
    "validate_triage_result",
]
