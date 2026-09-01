"""Bounded read-only bridge to JAWL's local web console."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class JawlWebUnavailable(ConnectionError):
    """Raised when JAWL's optional web console cannot be read."""


class JawlWebAdapter:
    """Read safe JAWL summaries without opening its database directly."""

    _MAX_RESPONSE_BYTES = 128 * 1024
    _SAFE_CONFIG = (
        "settings:identity.agent_name",
        "settings:llm.language",
        "settings:system.proactive_guidance",
        "settings:system.continuous_cycle",
        "settings:system.heartbeat_interval",
        "settings:llm.is_multimodal",
    )

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 2.0,
        opener: Callable[..., Any] = urlopen,
    ):
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("JAWL web URL must be an HTTP(S) URL")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("JAWL web URL must point to the local machine")
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token or ""
        self.timeout_seconds = max(0.2, min(float(timeout_seconds), 10.0))
        self._opener = opener
        self.last_status = "not_checked"

    def status(self) -> str:
        try:
            self._get("/api/agent/status")
        except JawlWebUnavailable:
            self.last_status = "offline"
        else:
            self.last_status = "online"
        return self.last_status

    def overview(self) -> dict[str, Any]:
        sources = {
            "agent": "/api/agent/status",
            "tick": "/api/tick",
            "memory": "/api/db/stats",
            "drives": "/api/drives",
            "persona": "/api/config",
        }
        result: dict[str, Any] = {
            "configured": True,
            "status": "ok",
            "base_url": self.base_url,
            "sources": {},
            "errors": {},
        }
        for name, path in sources.items():
            try:
                result["sources"][name] = self._get(path)
            except JawlWebUnavailable as exc:
                result["errors"][name] = str(exc)
        if result["errors"]:
            result["status"] = "degraded"
        result["sources"]["persona"] = self._safe_persona(result["sources"].get("persona"))
        return result

    def memory(self) -> dict[str, Any]:
        stats = self._get("/api/db/stats")
        drives = self._get("/api/drives")
        return {
            "configured": True,
            "status": "ok",
            "database": self._memory_stats(stats),
            "drives": self._bounded_drives(drives),
        }

    def persona(self) -> dict[str, Any]:
        config = self._get("/api/config")
        return {
            "configured": True,
            "status": "ok",
            "settings": self._safe_persona(config),
        }

    def _get(self, path: str) -> dict[str, Any]:
        request = Request(urljoin(self.base_url, path.lstrip("/")), headers={
            "Accept": "application/json",
            **({"X-Console-Token": self.token} if self.token else {}),
        })
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self._MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise JawlWebUnavailable("JAWL web console is not reachable") from exc
        if len(raw) > self._MAX_RESPONSE_BYTES:
            raise JawlWebUnavailable("JAWL web response exceeds the bounded limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JawlWebUnavailable("JAWL web returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise JawlWebUnavailable("JAWL web returned a JSON object")
        return payload

    @classmethod
    def _safe_persona(cls, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"available": False}
        values = payload.get("values")
        if not isinstance(values, dict):
            return {"available": False}
        return {key: values[key] for key in cls._SAFE_CONFIG if key in values}

    @staticmethod
    def _memory_stats(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: payload[key]
            for key in ("ok", "sql", "vector", "graph")
            if key in payload
        }

    @staticmethod
    def _bounded_drives(payload: dict[str, Any]) -> dict[str, Any]:
        drives = payload.get("drives")
        if not isinstance(drives, list):
            return {key: payload[key] for key in ("ok", "dynamicReduction") if key in payload}
        return {
            key: payload[key]
            for key in ("ok", "dynamicReduction")
            if key in payload
        } | {"drives": drives[:20]}
