"""Small OpenAI-compatible chat adapter for temporary local or remote tests."""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_LLM_CHARS = 12_000


class LLMUnavailable(ConnectionError):
    """The configured chat provider is unavailable or returned invalid data."""


def _chat_url(value: str) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("LLM endpoint is required")
    if endpoint.endswith("/chat/completions"):
        return endpoint
    if endpoint.endswith("/v1"):
        return f"{endpoint}/chat/completions"
    return f"{endpoint}/v1/chat/completions"


class OpenAICompatibleChatClient:
    """Use one bounded chat request as a TextGateway responder."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str = "",
        timeout_seconds: float = 120.0,
        system_prompt: str = "Ты локальный AI-компаньон. Отвечай по-русски, кратко и естественно.",
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = _chat_url(endpoint)
        self.model = str(model or "").strip()
        if not self.model:
            raise ValueError("LLM model is required")
        self.api_key = str(api_key or "")
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 300.0))
        self.system_prompt = str(system_prompt or "").strip()[:4000]
        self._opener = opener

    def health(self) -> dict[str, Any]:
        request = Request(self._models_url(), headers=self._headers(), method="GET")
        try:
            with self._opener(request, timeout=min(self.timeout_seconds, 10.0)) as response:
                payload = json.loads(response.read(64 * 1024).decode("utf-8"))
        except (HTTPError, URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return {"status": "offline", "model": self.model}
        return {"status": "online", "model": self.model, "models_endpoint": isinstance(payload, dict)}

    def respond(self, text: str, *, cancel_event: threading.Event | None = None) -> str:
        clean = str(text or "").strip()
        if not clean or len(clean) > MAX_LLM_CHARS:
            raise ValueError("LLM text must be non-empty and at most 12000 characters")
        if cancel_event is not None and cancel_event.is_set():
            raise LLMUnavailable("LLM request cancelled")
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": clean})
        request = Request(
            self.endpoint,
            data=json.dumps({
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 800,
            }, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **self._headers()},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(256 * 1024).decode("utf-8"))
        except HTTPError as exc:
            raise LLMUnavailable(f"LLM endpoint returned HTTP {exc.code}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise LLMUnavailable("LLM endpoint is unavailable") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMUnavailable("LLM endpoint returned invalid JSON") from exc
        if cancel_event is not None and cancel_event.is_set():
            raise LLMUnavailable("LLM request cancelled")
        answer = self._extract_text(payload)
        if not answer:
            raise LLMUnavailable("LLM endpoint returned empty text")
        return answer[:MAX_LLM_CHARS]

    def _models_url(self) -> str:
        return self.endpoint.rsplit("/chat/completions", 1)[0].rsplit("/v1", 1)[0] + "/v1/models"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    @staticmethod
    def _extract_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        if not isinstance(content, str):
            return ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.IGNORECASE | re.DOTALL)
        return content.replace("<final>", "").replace("</final>", "").strip()


__all__ = ["LLMUnavailable", "OpenAICompatibleChatClient"]
