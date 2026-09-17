"""Bounded read-only bridge to JAWL's local web console."""

from __future__ import annotations

import json
import time
from uuid import uuid4
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .jawl_adapter import (
    JawlTurnCancelled,
    JawlUnsafeResponse,
    filter_user_delta,
    filter_user_response,
)


class JawlWebUnavailable(ConnectionError):
    """Raised when JAWL's optional web console cannot be read."""


class JawlWebAdapter:
    """Read safe JAWL summaries and optionally control its local lifecycle."""

    _MAX_RESPONSE_BYTES = 128 * 1024
    _LIFECYCLE_TIMEOUT_SECONDS = 120.0
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
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "JAWL web URL cannot contain credentials, query parameters or fragments"
            )
        self.base_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        ) + "/"
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
        result = {
            "configured": True,
            "status": "ok",
            "database": self._memory_stats(stats),
            "drives": self._bounded_drives(drives),
        }
        try:
            result["structured"] = self.structured_memory(limit=50)["memory"]
        except (JawlWebUnavailable, KeyError, TypeError):
            # Older JAWL consoles remain usable as a read-only compatibility
            # source; absence of the new route is visible to the caller.
            result["structured"] = {"available": False}
        return result

    def structured_memory(self, kind: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Read the canonical versioned memory projection from native JAWL."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("memory limit must be an integer from 1 to 100")
        query = urlencode({key: value for key, value in {"kind": kind or "", "limit": limit}.items() if value != ""})
        payload = self._get("/api/memory" + (f"?{query}" if query else ""))
        records = payload.get("memory")
        if payload.get("native") is not True or not isinstance(records, dict):
            raise JawlWebUnavailable("JAWL returned no native structured memory")
        return {"configured": True, "status": "ok", "memory": records}

    def _memory_mutation(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation not in {"remember", "revise", "forget", "archive"}:
            raise ValueError("unsupported memory operation")
        if not self.token:
            raise JawlWebUnavailable("JAWL memory control requires a console token")
        response = self._request_json(
            "/api/memory", method="POST", payload={"operation": operation, **payload}
        )
        result = response.get("memory")
        if response.get("ok") is not True or response.get("native") is not True or not isinstance(result, dict):
            raise JawlWebUnavailable("JAWL rejected the memory operation")
        if result.get("is_success") is not True:
            message = str(result.get("message") or "JAWL rejected the memory operation")[:300]
            raise JawlWebUnavailable(message)
        return {"status": "synchronized", "memory": result}

    def remember_memory(self, **payload: Any) -> dict[str, Any]:
        """Create one canonical memory item through JAWL's allowlisted control path."""
        return self._memory_mutation("remember", payload)

    def revise_memory(self, memory_key: str, **payload: Any) -> dict[str, Any]:
        """Append a corrected canonical memory revision."""
        return self._memory_mutation("revise", {"memory_key": memory_key, **payload})

    def forget_memory(self, memory_key: str, reason: str = "") -> dict[str, Any]:
        """Append a canonical forgotten revision without deleting history."""
        return self._memory_mutation("forget", {"memory_key": memory_key, "reason": reason})

    def archive_memory(self, memory_key: str, reason: str = "") -> dict[str, Any]:
        """Append a canonical archived revision without deleting history."""
        return self._memory_mutation("archive", {"memory_key": memory_key, "reason": reason})

    def autonomy_journal(
        self, limit: int = 20, state: str | None = None
    ) -> dict[str, Any]:
        """Read JAWL's bounded public projection of autonomous action plans."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("journal limit must be an integer from 1 to 50")
        allowed_states = {
            None, "completed", "failed", "cancelled", "error",
            "in_progress", "interrupted", "reconciled",
        }
        if state not in allowed_states:
            raise ValueError("unsupported journal state")
        params = {"limit": limit}
        if state is not None:
            params["state"] = state
        payload = self._get("/api/agent/journal?" + urlencode(params))
        journal = payload.get("journal")
        plans = journal.get("plans") if isinstance(journal, dict) else None
        if payload.get("native") is not True or not isinstance(journal, dict) or not isinstance(plans, list):
            raise JawlWebUnavailable("JAWL returned no native action journal")
        return {
            "configured": True,
            "status": "ok",
            "native": True,
            "source": "jawl.action_journal",
            "plans": plans[:50],
        }

    def chat_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read the bounded JAWL chat history rows (sender/text/time)."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("history limit must be an integer from 1 to 200")
        payload = self._get("/api/chat")
        history = payload.get("history")
        if not isinstance(history, list):
            raise JawlWebUnavailable("JAWL returned no chat history")
        rows: list[dict[str, Any]] = []
        for item in history[-limit:]:
            if not isinstance(item, dict):
                continue
            rows.append({
                "sender": str(item.get("sender", ""))[:80],
                "text": str(item.get("text", ""))[:4000],
                "time": str(item.get("time", ""))[:40],
            })
        return rows

    def execute_hostos_skill(self, skill: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one native JAWL HostOS skill; policy stays in JAWL."""
        if not isinstance(skill, str) or not skill.startswith(("HostOS", "HostTerminal")):
            raise ValueError("only native HostOS/HostTerminal skills are allowed")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        if not self.token:
            raise JawlWebUnavailable("JAWL HostOS control requires a console token")
        response = self._request_json(
            "/api/hostos/skill", method="POST", payload={"skill": skill, "arguments": arguments}
        )
        result = response.get("result")
        if response.get("ok") is not True or response.get("native") is not True or not isinstance(result, dict):
            raise JawlWebUnavailable("JAWL rejected the native HostOS skill")
        return {"status": "native", "result": result}

    def execute_debug_skill(self, skill: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one of JAWL's stable native Debug Broker skills."""
        allowed = {
            "DebugBroker.list_providers",
            "DebugBroker.search_operations",
            "DebugBroker.start_session",
            "DebugBroker.call_operation",
            "DebugBroker.wait_session",
            "DebugBroker.session_snapshot",
            "DebugBroker.stop_session",
        }
        if skill not in allowed:
            raise ValueError("only native DebugBroker skills are allowed")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        if not self.token:
            raise JawlWebUnavailable("JAWL Debug Broker control requires a console token")
        response = self._request_json(
            "/api/debug/skill", method="POST", payload={"skill": skill, "arguments": arguments}
        )
        result = response.get("result")
        if response.get("ok") is not True or response.get("native") is not True or not isinstance(result, dict):
            raise JawlWebUnavailable("JAWL rejected the native Debug Broker skill")
        return {"status": "native", "result": result}

    def native_skill_catalog(
        self,
        prefixes: tuple[str, ...] = ("HostOS", "HostTerminal", "DebugBroker"),
        limit: int = 256,
    ) -> dict[str, Any]:
        """Read JAWL's current native registry without creating a local copy."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 512:
            raise ValueError("skill catalog limit must be an integer from 1 to 512")
        if not isinstance(prefixes, tuple) or not prefixes:
            raise ValueError("skill catalog prefixes must be a non-empty tuple")
        if any(prefix not in {"HostOS", "HostTerminal", "DebugBroker"} for prefix in prefixes):
            raise ValueError("unsupported native skill namespace")
        query = urlencode({"limit": limit}, doseq=False)
        for prefix in dict.fromkeys(prefixes):
            query += "&" + urlencode({"prefix": prefix})
        payload = self._get("/api/skills/catalog?" + query)
        catalog = payload.get("catalog")
        skills = catalog.get("skills") if isinstance(catalog, dict) else None
        if payload.get("native") is not True or not isinstance(catalog, dict) or not isinstance(skills, list):
            raise JawlWebUnavailable("JAWL returned no native skill catalog")
        return {
            "configured": True,
            "status": "ok",
            "native": True,
            "schema_version": catalog.get("schema_version", 1),
            "prefixes": catalog.get("prefixes", []),
            "skills": skills[:512],
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
        result = {
            "configured": True,
            "status": "ok" if level is not None else "not_exposed",
            "enabled": settings.get("interfaces:host.os.enabled"),
            "access_level": level,
            "access_name": ("SANDBOX", "OBSERVER", "OPERATOR", "ROOT")[level] if level is not None else None,
        }
        # The config route is only a persisted setting.  When the native
        # runtime is alive, prefer its versioned policy snapshot so the UI does
        # not mistake configuration for effective authority.
        try:
            native = self.native_policy()
        except (JawlWebUnavailable, KeyError):
            native = None
        if native is not None:
            native_level = native.get("access_level")
            if isinstance(native_level, int) and native_level in range(4):
                result.update({
                    "status": "ok",
                    "access_level": native_level,
                    "access_name": ("SANDBOX", "OBSERVER", "OPERATOR", "ROOT")[native_level],
                })
            result["native_policy"] = native
        return result

    def native_policy(self) -> dict[str, Any]:
        """Read the effective policy from JAWL's native control authority."""
        payload = self._get("/api/hostos/policy")
        policy = payload.get("policy")
        if not isinstance(policy, dict) or payload.get("native") is not True:
            raise JawlWebUnavailable("JAWL returned no native HostOS policy")
        return policy

    def set_unattended(
        self,
        enabled: bool,
        *,
        ttl_seconds: int = 3600,
        actor: str = "companion",
    ) -> dict[str, Any]:
        """Issue or revoke the bounded native ROOT autonomy lease."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise ValueError("ttl_seconds must be an integer")
        if not self.token:
            raise JawlWebUnavailable("JAWL HostOS control requires a console token")
        payload = self._request_json(
            "/api/hostos/autonomy",
            method="POST",
            payload={
                "enabled": enabled,
                "confirm": True if enabled else None,
                "ttl_seconds": ttl_seconds,
                "actor": str(actor)[:80],
            },
        )
        if payload.get("ok") is not True or not isinstance(payload.get("policy"), dict):
            raise JawlWebUnavailable("JAWL rejected the autonomy lease change")
        return {"status": "synchronized", "policy": payload["policy"]}

    def emergency_stop(self, *, actor: str = "companion", reason: str = "") -> dict[str, Any]:
        """Latch the native emergency stop and stop native managed sessions."""
        if not self.token:
            raise JawlWebUnavailable("JAWL HostOS control requires a console token")
        payload = self._request_json(
            "/api/hostos/emergency-stop",
            method="POST",
            payload={"actor": str(actor)[:80], "reason": str(reason)[:2000]},
        )
        if payload.get("ok") is not True or not isinstance(payload.get("policy"), dict):
            raise JawlWebUnavailable("JAWL rejected the emergency stop")
        return {"status": "stopped", "policy": payload["policy"]}

    def reset_emergency_stop(self, *, actor: str = "companion") -> dict[str, Any]:
        """Clear the native emergency latch only after explicit confirmation."""
        if not self.token:
            raise JawlWebUnavailable("JAWL HostOS control requires a console token")
        payload = self._request_json(
            "/api/hostos/emergency-stop/reset",
            method="POST",
            payload={"confirm": True, "actor": str(actor)[:80]},
        )
        if payload.get("ok") is not True or not isinstance(payload.get("policy"), dict):
            raise JawlWebUnavailable("JAWL rejected the emergency-stop reset")
        return {"status": "reset", "policy": payload["policy"]}

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
        # Restart the agent so the new level takes effect. The console's
        # stop/start can be slow to report; retry a few times and only treat a
        # still-running old agent as a real failure.
        self._request_json("/api/agent/stop", method="POST", payload={})
        for _ in range(30):
            try:
                status = self._request_json("/api/agent/status")
                if not status.get("running"):
                    break
            except JawlWebUnavailable:
                pass
            time.sleep(1.0)
        started = None
        for attempt in range(5):
            try:
                started = self._request_json("/api/agent/start", method="POST", payload={})
                if started.get("ok") is True:
                    break
            except JawlWebUnavailable:
                started = None
            time.sleep(2.0)
        if not (isinstance(started, dict) and started.get("ok") is True):
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
        stopped = self._request_json(
            "/api/agent/stop", method="POST", payload={},
            request_timeout=self._LIFECYCLE_TIMEOUT_SECONDS,
        )
        if stopped.get("ok") is not True:
            raise JawlWebUnavailable("JAWL agent did not accept the stop request")
        return {"status": "stopped", "forced": bool(stopped.get("forced", False))}

    def start_agent(self) -> dict[str, Any]:
        """Start JAWL's native agent through its authenticated web API."""
        if not self.token:
            raise JawlWebUnavailable("JAWL agent control requires a console token")
        started = self._request_json(
            "/api/agent/start", method="POST", payload={},
            request_timeout=self._LIFECYCLE_TIMEOUT_SECONDS,
        )
        if started.get("ok") is not True:
            raise JawlWebUnavailable("JAWL agent did not accept the start request")
        pid = started.get("pid")
        return {"status": "started", **({"pid": pid} if isinstance(pid, int) else {})}

    def restart_agent(self, *, wait_for_memory: bool = False) -> dict[str, Any]:
        """Restart JAWL through the two authenticated native lifecycle calls."""

        stopped = self.stop_agent()
        started = self.start_agent()
        readiness_window = 180.0 if wait_for_memory else min(30.0, max(5.0, self.timeout_seconds * 6))
        deadline = time.monotonic() + readiness_window
        last_error = ""
        while time.monotonic() < deadline:
            try:
                status = self._request_json(
                    "/api/agent/status",
                    request_timeout=self._LIFECYCLE_TIMEOUT_SECONDS,
                )
                if status.get("running") is True and status.get("starting") is not True:
                    if wait_for_memory:
                        for probe in range(2):
                            memory = self.memory()
                            if memory.get("configured") is not True or memory.get("status") != "ok":
                                raise JawlWebUnavailable("JAWL memory projection is not ready after restart")
                            if probe == 0:
                                time.sleep(0.25)
                    return {
                        "status": "restarted",
                        "stopped": stopped,
                        "started": started,
                        "agent_ready": True,
                    }
            except JawlWebUnavailable as exc:
                last_error = str(exc)
            time.sleep(0.25)
        raise JawlWebUnavailable(
            "JAWL agent did not become ready after restart" + (f": {last_error}" if last_error else "")
        )

    def _get(self, path: str) -> dict[str, Any]:
        return self._request_json(path)

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        request_timeout: float | None = None,
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
            with self._opener(
                request, timeout=request_timeout or self.timeout_seconds
            ) as response:
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

    def has_pending(self) -> bool:
        """Return whether an already-read SSE packet still awaits delivery."""
        return not self._events.empty()

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
            # Dropping the oldest packet can hide a final/error event.  Stop
            # with an explicit integrity error so the caller can reconnect or
            # surface a terminal failure instead of inventing success.
            self.error = JawlWebUnavailable("JAWL chat stream event queue overflowed")
            self._stop.set()


class JawlWebChatAdapter(JawlWebAdapter):
    """Use JAWL's web POST plus SSE stream as a correlated chat transport."""

    _MAX_CHAT_RESPONSE_BYTES = 128 * 1024

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 2.0,
        chat_timeout_seconds: float = 120.0,
        native_gateway: bool = False,
        opener: Callable[..., Any] = urlopen,
    ):
        super().__init__(base_url, token=token, timeout_seconds=timeout_seconds, opener=opener)
        self.chat_timeout_seconds = max(1.0, min(float(chat_timeout_seconds), 300.0))
        self.native_gateway = bool(native_gateway)
        self.last_chat_status = "not_checked"
        self.last_chat_error = ""
        # JAWL owns one ReAct/SQLite lifecycle.  A newer Companion request may
        # cancel an older token, but must not POST a second native cycle until
        # the older adapter call has completed its cancellation cleanup.
        self._native_turn_lock = Lock()

    def chat_status(self) -> str:
        if self.last_chat_status == "not_checked":
            return self.status()
        return self.last_chat_status

    @property
    def supports_native_envelope(self) -> bool:
        return self.native_gateway

    def respond(self, text: str, cancel_event: Event | None = None, correlation_id: str | None = None) -> str:
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("JAWL chat text must not be empty")
        if self.native_gateway:
            return self.respond_envelope(clean, cancel_event=cancel_event, correlation_id=correlation_id)["text"]
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

    def respond_envelope(self, text: str, cancel_event: Event | None = None, correlation_id: str | None = None) -> dict[str, Any]:
        """Return JAWL's validated native ResponseEnvelope without rebuilding it."""
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("JAWL chat text must not be empty")
        if not self.native_gateway:
            raise JawlWebUnavailable("native JAWL envelope mode is disabled")
        return self._respond_native(clean, cancel_event, correlation_id)

    def _respond_native(self, text: str, cancel_event: Event | None, correlation_id: str | None = None) -> dict[str, Any]:
        with self._native_turn_lock:
            return self._respond_native_serialized(text, cancel_event, correlation_id)

    def _respond_native_serialized(self, text: str, cancel_event: Event | None, correlation_id: str | None = None) -> dict[str, Any]:
        """Use JAWL's typed correlated stream; no sequence/broadcast scraping."""
        try:
            for event in self._iter_native_events(text, cancel_event, correlation_id):
                if event.type == "assistant.final":
                    response = dict(event.payload["response"])
                    response["text"] = filter_user_response(response["text"])
                    return response
                if event.type == "turn.cancelled":
                    raise JawlTurnCancelled(event.payload.get("reason", "JAWL cancelled the turn"))
                if event.type == "turn.error":
                    raise JawlWebUnavailable(event.payload.get("reason", "JAWL turn failed"))
        except JawlTurnCancelled:
            self.last_chat_status = "cancelled"
            raise
        except JawlWebUnavailable:
            # Preserve the public adapter invariant used by health checks:
            # a terminal native error is an offline/degraded transport result,
            # while the detailed reason remains in ``last_chat_error``.
            self.last_chat_status = "offline"
            raise
        raise JawlWebUnavailable("JAWL produced no terminal Companion event")

    def stream_envelope(
        self,
        text: str,
        cancel_event: Event | None = None,
        correlation_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield safe native deltas and one authoritative final envelope.

        Older pinned JAWL builds emit only ``assistant.final``; in that case
        this iterator yields just the final event and the Companion gateway
        supplies the compatibility delta. Newer builds may emit
        ``assistant.delta`` fragments. Tool lifecycle events stay inside JAWL
        and are deliberately not exposed as assistant text.
        """

        if not self.native_gateway:
            raise JawlWebUnavailable("native JAWL envelope mode is disabled")
        for event in self._iter_native_events(text, cancel_event, correlation_id):
            if event.type == "assistant.delta":
                try:
                    fragment = filter_user_delta(event.payload.get("text", ""))
                except JawlUnsafeResponse as exc:
                    self.last_chat_status = "invalid_response"
                    raise JawlWebUnavailable("JAWL returned an unsafe Companion delta") from exc
                if fragment:
                    yield {"type": "delta", "text": fragment}
                continue
            if event.type == "assistant.final":
                response = dict(event.payload["response"])
                try:
                    response["text"] = filter_user_response(response["text"])
                except JawlUnsafeResponse as exc:
                    self.last_chat_status = "invalid_response"
                    raise JawlWebUnavailable("JAWL returned an unsafe Companion response") from exc
                yield {"type": "final", "response": response}
                return
            if event.type == "turn.cancelled":
                raise JawlTurnCancelled(event.payload.get("reason", "JAWL cancelled the turn"))
            if event.type == "turn.error":
                raise JawlWebUnavailable(event.payload.get("reason", "JAWL turn failed"))
        raise JawlWebUnavailable("JAWL produced no terminal Companion event")

    def _iter_native_events(
        self,
        text: str,
        cancel_event: Event | None,
        correlation_id: str | None,
    ) -> Iterator[Any]:
        """Read one correlated native stream with bounded reconnects."""

        from .jawl_gateway_contract import JawlGatewayEvent

        turn_id = str(correlation_id or f"turn-{uuid4().hex}")[:128]
        deadline = time.monotonic() + self.chat_timeout_seconds
        self.last_chat_status = "starting"
        self.last_chat_error = ""
        after = 0
        submitted = False
        for attempt in range(6):
            if attempt:
                # A transient gap (remote cursor still catching up while the
                # agent is busy) must not burn all reconnects in milliseconds.
                time.sleep(min(0.5, 0.2 * attempt))
            self._last_native_event_seq = max(0, after)
            stream_url = urljoin(self.base_url, "/api/companion/stream")
            if after:
                stream_url += "?" + urlencode({"after": str(after)})
            request = Request(stream_url, headers={
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
                **({"X-Console-Token": self.token} if self.token else {}),
            })
            reader = _SseReader(self._opener, request, self.chat_timeout_seconds)
            reader.start()
            try:
                while not reader.ready.is_set() and time.monotonic() < deadline:
                    self._check_cancel(cancel_event)
                    time.sleep(0.01)
                if reader.error:
                    raise reader.error
                if not reader.ready.is_set():
                    raise JawlWebUnavailable("JAWL Companion stream did not start")
                if not submitted:
                    self._post_native(text, turn_id)
                    submitted = True
                while time.monotonic() < deadline:
                    self._check_cancel(cancel_event)
                    packet = reader.get(min(0.1, max(0.01, deadline - time.monotonic())))
                    self._check_cancel(cancel_event)
                    if packet is not None:
                        cursor = packet.get("cursor")
                        if isinstance(cursor, dict):
                            # The console echoes the requested ``after`` on a
                            # gap, so a reconnect with it would gap forever.
                            # Jump to the newest buffered/latest sequence and
                            # let the next stream wait for live events.
                            for key in ("after", "latest_event_seq"):
                                value = cursor.get(key)
                                if isinstance(value, int) and value > self._last_native_event_seq:
                                    self._last_native_event_seq = value
                        raw_events = packet.get("events")
                        for raw_event in raw_events if isinstance(raw_events, list) else []:
                            try:
                                parsed = JawlGatewayEvent.from_mapping(raw_event)
                            except ValueError as exc:
                                self.last_chat_status = "invalid_response"
                                raise JawlWebUnavailable(
                                    "JAWL returned an invalid Companion event"
                                ) from exc
                            self._last_native_event_seq = max(
                                self._last_native_event_seq, parsed.event_seq
                            )
                            if parsed.turn_id != turn_id:
                                continue
                            if parsed.type == "assistant.final":
                                self.last_chat_status = "connected"
                            elif parsed.type == "turn.cancelled":
                                self.last_chat_status = "cancelled"
                            elif parsed.type == "turn.error":
                                self.last_chat_status = "error"
                            yield parsed
                            if parsed.type in {"assistant.final", "turn.cancelled", "turn.error"}:
                                return
                    self._check_cancel(cancel_event)
                    if reader.error:
                        raise reader.error
                    if reader.done.is_set() and not reader.has_pending():
                        self.last_chat_status = "no_broadcast"
                        raise JawlWebUnavailable(
                            "JAWL Companion stream closed without a final event"
                        )
                self.last_chat_status = "no_broadcast"
                raise JawlWebUnavailable("JAWL produced no final Companion event before timeout")
            except JawlTurnCancelled:
                if cancel_event is not None and cancel_event.is_set():
                    self._post_native_cancel(turn_id)
                self.last_chat_status = "cancelled"
                raise
            except JawlWebUnavailable as exc:
                self.last_chat_error = str(exc)
                next_after = max(after, int(getattr(self, "_last_native_event_seq", after)))
                reconnectable = (
                    self.last_chat_status == "no_broadcast"
                    and reader.done.is_set()
                    and reader.error is None
                )
                if reconnectable and time.monotonic() < deadline and attempt < 2:
                    after = next_after
                    continue
                if submitted:
                    self._post_native_cancel(turn_id)
                self.last_chat_status = "offline"
                raise
            finally:
                reader.stop()

    def _post_native(self, text: str, turn_id: str) -> None:
        body = json.dumps({"text": text, "turn_id": turn_id}, ensure_ascii=False).encode("utf-8")
        request = Request(urljoin(self.base_url, "/api/companion/turn"), data=body,
                          method="POST", headers={
                              "Accept": "application/json",
                              "Content-Type": "application/json",
                              **({"X-Console-Token": self.token} if self.token else {}),
                          })
        deadline = time.monotonic() + min(8.0, self.timeout_seconds)
        for attempt in range(6):
            offline = False
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    raw = response.read(self._MAX_CHAT_RESPONSE_BYTES + 1)
            except HTTPError as exc:
                # The console answers 409 while its agent bridge is still
                # warming up (idle -> connecting). The open native stream is
                # the watcher that brings it online, so a short retry wins.
                offline = exc.code == 409
                exc.close()
                if not offline:
                    self.last_chat_status = "offline"
                    raise JawlWebUnavailable("JAWL Companion turn request failed") from exc
            except (URLError, OSError, TimeoutError) as exc:
                offline = True
            if not offline:
                if len(raw) > self._MAX_CHAT_RESPONSE_BYTES:
                    raise JawlWebUnavailable("JAWL Companion turn response exceeds the bounded limit")
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise JawlWebUnavailable("JAWL Companion turn returned invalid JSON") from exc
                if isinstance(payload, dict) and payload.get("ok") is True and payload.get("turn_id") == turn_id:
                    return
                if not isinstance(payload, dict) or payload.get("offline") is not True:
                    raise JawlWebUnavailable("JAWL did not acknowledge the Companion turn")
            if attempt >= 5 or time.monotonic() >= deadline:
                break
            time.sleep(0.3)
        self.last_chat_status = "offline"
        raise JawlWebUnavailable("JAWL Companion turn bridge did not come online")

    def _post_native_cancel(self, turn_id: str) -> bool:
        """Forward local cancellation so JAWL stops the live ReAct task too."""

        body = json.dumps({"turn_id": turn_id}, ensure_ascii=False).encode("utf-8")
        request = Request(
            urljoin(self.base_url, "/api/companion/cancel"),
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **({"X-Console-Token": self.token} if self.token else {}),
            },
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self._MAX_CHAT_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            self.last_chat_error = "JAWL Companion cancel request returned HTTP error"
            return False
        except (URLError, OSError, TimeoutError):
            # The caller is already cancelling locally; network failure must
            # not turn a successful local cancellation into a hard error.
            self.last_chat_error = "JAWL Companion cancel request is not reachable"
            return False
        if len(raw) > self._MAX_CHAT_RESPONSE_BYTES:
            self.last_chat_error = "JAWL Companion cancel response exceeds the bounded limit"
            return False
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.last_chat_error = "JAWL Companion cancel returned invalid JSON"
            return False
        if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("turn_id") != turn_id:
            self.last_chat_error = "JAWL Companion cancel was not acknowledged for this turn"
            return False
        return True

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
            if reader.done.is_set() and not reader.has_pending():
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
            if reader.done.is_set() and not reader.has_pending():
                self.last_chat_status = "no_broadcast"
                raise JawlWebUnavailable("JAWL chat stream closed without an agent broadcast")
        self.last_chat_status = "no_broadcast"
        raise JawlWebUnavailable("JAWL produced no correlated chat broadcast before timeout")

    @staticmethod
    def _check_cancel(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise JawlTurnCancelled("JAWL response superseded by a newer turn")
