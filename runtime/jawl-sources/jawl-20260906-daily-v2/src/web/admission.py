"""Owned HTTP admission extension; no agent, model, memory or tool authority.

Installed after native authentication, only in the owned console process.
The pinned ChatBridge writes synchronously before its first await in send().
Deduplication is bounded/process-local, never an exactly-once syscall claim.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import re
import time
from typing import Any, Callable
from uuid import uuid4

from aiohttp import web

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PREFIX = "/api/companion/"
MAX_BODY_BYTES = 128 * 1024


class _Rejected(Exception):
    def __init__(self, error: str, status: int = 400):
        self.error, self.status = error, status


@dataclass
class _Entry:
    expires: float
    pending: bool = True
    dispatched: bool = False
    cancelled: bool = False


class NativeAdmission:
    def __init__(self, bridge_factory: Callable[[], Any], *, ttl_seconds: float = 300,
                 max_entries: int = 1024, ready_timeout_seconds: float = 5,
                 send_timeout_seconds: float = 2):
        if (not 0 < ttl_seconds <= 3600 or isinstance(max_entries, bool)
                or not isinstance(max_entries, int) or not 1 <= max_entries <= 8192
                or not 0 < ready_timeout_seconds <= 10 or not 0 < send_timeout_seconds <= 10):
            raise ValueError("invalid native admission bounds")
        self.bridge_factory = bridge_factory
        self.ttl_seconds, self.max_entries = ttl_seconds, max_entries
        self.ready_timeout_seconds, self.send_timeout_seconds = ready_timeout_seconds, send_timeout_seconds
        self.clock = time.monotonic
        self._entries: dict[str, _Entry] = {}

    def _prune(self) -> None:
        now = self.clock()
        for key, entry in tuple(self._entries.items()):
            if not entry.pending and entry.expires <= now:
                del self._entries[key]

    def _new(self, turn_id: str) -> _Entry:
        self._prune()
        if len(self._entries) >= self.max_entries:
            raise _Rejected("admission_registry_full", 503)
        entry = _Entry(self.clock() + self.ttl_seconds)
        self._entries[turn_id] = entry
        return entry

    def _reserve(self, turn_id: str) -> _Entry:
        self._prune()
        if turn_id in self._entries:
            raise _Rejected("turn_cancelled" if self._entries[turn_id].cancelled else "duplicate_turn_id", 409)
        return self._new(turn_id)

    def _cancel(self, turn_id: str) -> _Entry:
        self._prune()
        entry = self._entries.get(turn_id)
        if entry is None:
            entry = self._new(turn_id)
            entry.pending = False
        entry.cancelled = True
        return entry

    @staticmethod
    def _closed(request: web.Request) -> bool:
        transport = request.transport
        return transport is None or transport.is_closing()

    @staticmethod
    def _reply(error: str, status: int, turn_id: str | None = None) -> web.Response:
        return web.json_response({"ok": False, "error": error,
                                  **({"turn_id": turn_id} if turn_id is not None else {})}, status=status)

    async def _forward_cancel(self, bridge: Any, turn_id: str, reason: str) -> bool:
        try:
            result = await asyncio.wait_for(bridge.cancel(turn_id, reason), timeout=1)
            return isinstance(result, dict) and result.get("ok") is True and result.get("turn_id") == turn_id
        except Exception:
            return False

    async def _submit(self, request: web.Request, text: str, turn_id: str) -> web.Response:
        entry = self._reserve(turn_id)
        bridge, acquired = None, False
        try:
            bridge = self.bridge_factory()
            await bridge.acquire()
            acquired = True
            deadline = self.clock() + self.ready_timeout_seconds
            while not bridge.connected:
                if entry.cancelled or self._closed(request):
                    entry.cancelled = True
                    return self._reply("turn_cancelled_before_dispatch", 409, turn_id)
                if self.clock() >= deadline:
                    return self._reply("native_bridge_offline_not_dispatched", 409, turn_id)
                await asyncio.sleep(min(0.05, max(0, deadline - self.clock())))

            async def dispatch():
                # wait_for schedules a task: recheck INSIDE that task, not just
                # before scheduling. No await separates this check and native
                # ChatBridge's synchronous write-before-drain.
                if entry.cancelled or self._closed(request):
                    entry.cancelled = True
                    return None
                entry.dispatched = True
                return await bridge.send(text, turn_id=turn_id)

            result = await asyncio.wait_for(dispatch(), timeout=self.send_timeout_seconds)
            if result is None or entry.cancelled:
                return self._reply("turn_cancelled", 409, turn_id)
            if self._closed(request):
                entry.cancelled = True
                await self._forward_cancel(bridge, turn_id, "client disconnected")
                return self._reply("client_disconnected", 409, turn_id)
            if isinstance(result, dict) and result.get("ok") is True:
                return web.json_response({"ok": True, "turn_id": turn_id})
            entry.cancelled = True
            await self._forward_cancel(bridge, turn_id, "admission unconfirmed")
            return self._reply("native_admission_unconfirmed_not_replayed", 409, turn_id)
        except asyncio.CancelledError:
            entry.cancelled = True
            if entry.dispatched and bridge is not None:
                await self._forward_cancel(bridge, turn_id, "HTTP handler cancelled")
            raise
        except Exception:
            # A timeout/exception after write is uncertain, never a retry.
            if entry.dispatched and bridge is not None:
                entry.cancelled = True
                await self._forward_cancel(bridge, turn_id, "admission unconfirmed")
            return self._reply("native_admission_unconfirmed_not_replayed", 502, turn_id)
        finally:
            entry.pending = False
            entry.expires = self.clock() + self.ttl_seconds
            if acquired:
                await bridge.release()

    async def _payload(self, request: web.Request) -> dict:
        async def read() -> bytes:
            body = bytearray()
            async for chunk in request.content.iter_chunked(16 * 1024):
                body.extend(chunk)
                if len(body) > MAX_BODY_BYTES:
                    raise _Rejected("body_too_large", 413)
            return bytes(body)
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise _Rejected("duplicate_json_field")
                    result[key] = value
                return result
            data = json.loads((await asyncio.wait_for(read(), timeout=1)).decode("utf-8"), object_pairs_hook=unique)
        except _Rejected:
            raise
        except asyncio.TimeoutError:
            raise _Rejected("body_deadline_exceeded", 408) from None
        except (ValueError, UnicodeError):
            raise _Rejected("invalid_json") from None
        if not isinstance(data, dict):
            raise _Rejected("expected_json_object")
        return data

    async def handle(self, request: web.Request, handler) -> web.StreamResponse:
        if request.method == "GET" and request.path == _PREFIX + "admission-capabilities":
            return await self.capabilities(request)
        if request.method != "POST" or request.path not in {_PREFIX + "turn", _PREFIX + "cancel"}:
            return await handler(request)
        turn_id = None
        try:
            payload = await self._payload(request)
            is_turn = request.path.endswith("/turn")
            allowed = {"turn_id", "text"} if is_turn else {"turn_id", "reason"}
            if set(payload) - allowed:
                raise _Rejected("unknown_fields")
            turn_id = payload.get("turn_id", f"turn-{uuid4().hex}" if is_turn else None)
            if not isinstance(turn_id, str) or not _ID.fullmatch(turn_id):
                turn_id = None
                raise _Rejected("invalid_turn_id")
            if is_turn:
                text = payload.get("text")
                if not isinstance(text, str) or not text.strip() or len(text) > 8000:
                    raise _Rejected("invalid_text")
                return await self._submit(request, text.strip(), turn_id)
            reason = payload.get("reason", "")
            if not isinstance(reason, str) or len(reason) > 2000:
                raise _Rejected("invalid_reason")
            entry = self._cancel(turn_id)  # no await before tombstone is visible
            # Unknown/expired HTTP history is NOT proof that native work never
            # started (other transports, restart, or a long-running turn).
            forwarded = await self._forward_cancel(self.bridge_factory(), turn_id, reason)
            if not entry.dispatched:
                return web.json_response({"ok": True, "turn_id": turn_id,
                                          "local_dispatch_prevented": True, "forwarded": forwarded})
            return web.json_response({"ok": forwarded, "turn_id": turn_id, "forwarded": forwarded},
                                     status=200 if forwarded else 409)
        except _Rejected as exc:
            return self._reply(exc.error, exc.status, turn_id)

    async def capabilities(self, _request: web.Request) -> web.Response:
        return web.json_response({"schema_version": 1, "feature": "http-turn-admission-v1",
                                  "process_id": os.getpid(),
                                  "cancel_ack_scope": "local_tombstone_plus_best_effort_native_forward",
                                  "cancel_before_dispatch": True, "max_entries": self.max_entries,
                                  "ttl_seconds": self.ttl_seconds, "durable": False, "exactly_once": False})


def install_native_admission(app: web.Application, bridge_factory: Callable[[], Any], **bounds) -> NativeAdmission:
    controller = NativeAdmission(bridge_factory, **bounds)

    @web.middleware
    async def admission(request, handler):
        return await controller.handle(request, handler)

    app.middlewares.append(admission)  # native authentication remains outermost
    return controller
