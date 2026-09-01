"""Bounded read-only bridge to JAWL's local web console."""

from __future__ import annotations

import json
import time
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from .jawl_adapter import JawlTurnCancelled, JawlUnsafeResponse, filter_user_response


class JawlWebUnavailable(ConnectionError):
    """Raised when JAWL's optional web console cannot be read."""


class JawlWebAdapter:
    """Read safe JAWL summaries and optionally control its local lifecycle."""

    _MAX_RESPONSE_BYTES = 128 * 1024
    _SAFE_CONFIG = (
        "settings:identity.agent_name",
        "settings:llm.language",
        "settings:system.proactive_guidance",
        "settings:system.continuous_cycle",
        "settings:system.heartbeat_interval",
        "settings:llm.is_multimodal",
        "interfaces:host.os.enabled",
        "interfaces:host.os.access_level",
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
        result["sources"]["memory"] = self._memory_stats(result["sources"].get("memory", {}))
        result["sources"]["drives"] = self._bounded_drives(result["sources"].get("drives", {}))
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

    def hostos(self) -> dict[str, Any]:
        settings = self._safe_persona(self._get("/api/config"))
        level = settings.get("interfaces:host.os.access_level")
        if isinstance(level, bool) or not isinstance(level, int) or level not in range(4):
            level = None
        return {
            "configured": True,
            "status": "ok" if level is not None else "not_exposed",
            "enabled": settings.get("interfaces:host.os.enabled"),
            "access_level": level,
            "access_name": ("SANDBOX", "OBSERVER", "OPERATOR", "ROOT")[level] if level is not None else None,
        }

    def set_hostos_level(self, level: int) -> dict[str, Any]:
        """Persist and apply JAWL's native HostOS level through its web API."""
        if isinstance(level, bool) or not isinstance(level, int) or level not in range(4):
            raise ValueError("JAWL HostOS level must be an integer from 0 to 3")
        if not self.token:
            raise JawlWebUnavailable("JAWL HostOS control requires a console token")

        written = self._request_json(
            "/api/config",
            method="PUT",
            payload={
                "values": {
                    "interfaces:host.os.enabled": True,
                    "interfaces:host.os.access_level": level,
                },
                "lists": {},
            },
        )
        if written.get("ok") is not True:
            raise JawlWebUnavailable("JAWL rejected the HostOS configuration")
        stopped = self._request_json("/api/agent/stop", method="POST", payload={})
        if stopped.get("ok") is not True:
            raise JawlWebUnavailable("JAWL agent could not be stopped after HostOS configuration")
        started = self._request_json("/api/agent/start", method="POST", payload={})
        if started.get("ok") is not True:
            raise JawlWebUnavailable("JAWL agent could not be started with the new HostOS level")
        return {
            "status": "synchronized",
            "access_level": level,
            "access_name": ("SANDBOX", "OBSERVER", "OPERATOR", "ROOT")[level],
            "written": written.get("written", []),
            "agent_restarted": True,
        }

    def stop_agent(self) -> dict[str, Any]:
        """Stop JAWL's native agent through its authenticated web control API."""
        if not self.token:
            raise JawlWebUnavailable("JAWL agent control requires a console token")
        stopped = self._request_json("/api/agent/stop", method="POST", payload={})
        if stopped.get("ok") is not True:
            raise JawlWebUnavailable("JAWL agent did not accept the stop request")
        return {"status": "stopped", "forced": bool(stopped.get("forced", False))}

    def _get(self, path: str) -> dict[str, Any]:
        return self._request_json(path)

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if method != "GET" and not self.token:
            raise JawlWebUnavailable("JAWL control requires a console token")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(urljoin(self.base_url, path.lstrip("/")), headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
            **({"X-Console-Token": self.token} if self.token else {}),
        }, data=data, method=method)
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self._MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            raise JawlWebUnavailable("JAWL web console is not reachable") from exc
        except (URLError, OSError, TimeoutError) as exc:
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
        # JAWL may include reflections and implementation details here. Keep
        # the browser view a summary instead of a second memory dump.
        fields = (
            "id", "key", "name", "title", "type", "description", "decayRate",
            "decayIntervalSec", "deficit", "config", "pendingRestart",
        )
        bounded = []
        for drive in drives[:20]:
            if not isinstance(drive, dict):
                continue
            item = {key: drive[key] for key in fields if key in drive}
            if isinstance(item.get("description"), str):
                item["description"] = item["description"][:1000]
            bounded.append(item)
        return {
            key: payload[key]
            for key in ("ok", "dynamicReduction")
            if key in payload
        } | {"drives": bounded}


class _SseReader:
    """Read one bounded JAWL SSE stream without blocking the request thread."""

    _MAX_LINE_BYTES = 128 * 1024

    def __init__(self, opener: Callable[..., Any], request: Request, timeout: float):
        self._opener = opener
        self._request = request
        self._timeout = timeout
        self._stop = Event()
        self.ready = Event()
        self.done = Event()
        self.error: Exception | None = None
        self._events: Queue[dict[str, Any]] = Queue(maxsize=64)
        self._response: Any = None
        self._lock = Lock()
        self._thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def get(self, timeout: float) -> dict[str, Any] | None:
        try:
            return self._events.get(timeout=max(0.01, timeout))
        except Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        self._thread.join(timeout=0.5)

    def _run(self) -> None:
        data_lines: list[str] = []
        try:
            with self._opener(self._request, timeout=self._timeout) as response:
                with self._lock:
                    self._response = response
                self.ready.set()
                while not self._stop.is_set():
                    line = response.readline()
                    if not line:
                        break
                    if len(line) > self._MAX_LINE_BYTES:
                        raise JawlWebUnavailable("JAWL chat SSE line exceeds the bounded limit")
                    decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if decoded.startswith(":"):
                        continue
                    if decoded.startswith("data:"):
                        data_lines.append(decoded[5:].lstrip())
                    elif not decoded and data_lines:
                        self._publish("\n".join(data_lines))
                        data_lines.clear()
        except HTTPError as exc:
            exc.close()
            if not self._stop.is_set():
                self.error = JawlWebUnavailable("JAWL chat stream is not reachable")
        except (URLError, OSError, TimeoutError, ValueError):
            if not self._stop.is_set():
                self.error = JawlWebUnavailable("JAWL chat stream is not reachable")
        except Exception:  # noqa: BLE001 - a concurrent close may break http.client internals
            # `stop()` closes the response from the request thread.  On some
            # Python/HTTPResponse combinations readline() then raises an
            # implementation-level AttributeError instead of returning EOF.
            # Treat that race as normal cancellation; never leak a traceback
            # from the daemon reader thread.
            if not self._stop.is_set():
                self.error = JawlWebUnavailable("JAWL chat stream failed")
        finally:
            self.ready.set()
            self.done.set()

    def _publish(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            self.error = JawlWebUnavailable("JAWL chat stream returned invalid JSON")
            return
        if not isinstance(event, dict):
            return
        try:
            self._events.put_nowait(event)
        except Exception:
            try:
                self._events.get_nowait()
                self._events.put_nowait(event)
            except Empty:
                pass


class JawlWebChatAdapter(JawlWebAdapter):
    """Use JAWL's web POST plus SSE stream as a correlated chat transport."""

    _MAX_CHAT_RESPONSE_BYTES = 128 * 1024

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 2.0,
        chat_timeout_seconds: float = 120.0,
        opener: Callable[..., Any] = urlopen,
    ):
        super().__init__(base_url, token=token, timeout_seconds=timeout_seconds, opener=opener)
        self.chat_timeout_seconds = max(1.0, min(float(chat_timeout_seconds), 300.0))
        self.last_chat_status = "not_checked"
        self.last_chat_error = ""

    def chat_status(self) -> str:
        if self.last_chat_status == "not_checked":
            return self.status()
        return self.last_chat_status

    def respond(self, text: str, cancel_event: Event | None = None) -> str:
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("JAWL chat text must not be empty")
        request = Request(urljoin(self.base_url, "/api/chat/stream"), headers={
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            **({"X-Console-Token": self.token} if self.token else {}),
        })
        reader = _SseReader(self._opener, request, self.chat_timeout_seconds)
        reader.start()
        deadline = time.monotonic() + self.chat_timeout_seconds
        self.last_chat_status = "starting"
        self.last_chat_error = ""
        try:
            self._wait_until_online(reader, deadline, cancel_event)
            user_seq = self._post_chat(clean)
            return self._wait_for_agent(reader, user_seq, deadline, cancel_event)
        except JawlTurnCancelled:
            self.last_chat_status = "cancelled"
            raise
        except JawlWebUnavailable as exc:
            self.last_chat_error = str(exc)
            if self.last_chat_status not in {"no_broadcast", "offline"}:
                self.last_chat_status = "offline"
            raise
        finally:
            reader.stop()

    def _wait_until_online(
        self, reader: _SseReader, deadline: float, cancel_event: Event | None,
    ) -> None:
        while time.monotonic() < deadline:
            self._check_cancel(cancel_event)
            event = reader.get(min(0.1, max(0.01, deadline - time.monotonic())))
            self._check_cancel(cancel_event)
            if event is not None:
                status = event.get("status")
                if isinstance(status, dict) and status.get("state") == "online":
                    return
            if reader.error:
                raise reader.error
            if reader.done:
                raise JawlWebUnavailable("JAWL chat stream closed before becoming online")
        self.last_chat_status = "offline"
        raise JawlWebUnavailable("JAWL chat stream did not become online before timeout")

    def _post_chat(self, text: str) -> int:
        body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        request = Request(urljoin(self.base_url, "/api/chat"), data=body, method="POST", headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **({"X-Console-Token": self.token} if self.token else {}),
        })
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self._MAX_CHAT_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            self.last_chat_status = "offline"
            raise JawlWebUnavailable("JAWL chat request is not reachable") from exc
        except (URLError, OSError, TimeoutError) as exc:
            self.last_chat_status = "offline"
            raise JawlWebUnavailable("JAWL chat request is not reachable") from exc
        if len(raw) > self._MAX_CHAT_RESPONSE_BYTES:
            raise JawlWebUnavailable("JAWL chat response exceeds the bounded limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JawlWebUnavailable("JAWL chat returned invalid JSON") from exc
        message = payload.get("message") if isinstance(payload, dict) else None
        sequence = message.get("seq") if isinstance(message, dict) else None
        if payload.get("ok") is not True or not isinstance(sequence, int):
            raise JawlWebUnavailable("JAWL chat did not acknowledge the user message")
        return sequence

    def _wait_for_agent(
        self, reader: _SseReader, user_seq: int, deadline: float, cancel_event: Event | None,
    ) -> str:
        while time.monotonic() < deadline:
            self._check_cancel(cancel_event)
            event = reader.get(min(0.1, max(0.01, deadline - time.monotonic())))
            self._check_cancel(cancel_event)
            if event is not None:
                messages = event.get("messages")
                if isinstance(messages, list):
                    for message in messages:
                        if not isinstance(message, dict) or message.get("sender") == "User":
                            continue
                        sequence = message.get("seq")
                        answer = message.get("text")
                        if isinstance(sequence, int) and sequence > user_seq and isinstance(answer, str) and answer.strip():
                            try:
                                answer = filter_user_response(answer)
                            except JawlUnsafeResponse as exc:
                                self.last_chat_status = "invalid_response"
                                raise JawlWebUnavailable(
                                    "JAWL returned internal control markup"
                                ) from exc
                            self.last_chat_status = "connected"
                            return answer
            self._check_cancel(cancel_event)
            if reader.error:
                raise reader.error
            if reader.done:
                self.last_chat_status = "no_broadcast"
                raise JawlWebUnavailable("JAWL chat stream closed without an agent broadcast")
        self.last_chat_status = "no_broadcast"
        raise JawlWebUnavailable("JAWL produced no correlated chat broadcast before timeout")

    @staticmethod
    def _check_cancel(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise JawlTurnCancelled("JAWL response superseded by a newer turn")
