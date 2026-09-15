"""Persistent native Companion-gateway transport over JAWL's terminal socket.

This is the P0 transport from the N.E.K.O deep analysis: instead of routing
every chat turn through the console HTTP API plus its idle-prone bridge and
homegrown SSE cursors, the Companion keeps ONE long-lived TCP connection to
the JAWL agent's terminal server (the same protocol the console UI uses).
The handshake ``JAWL_GATEWAY <seq>`` subscribes to typed, correlated gateway
events with replay from the last seen cursor, so a reconnect picks up missed
``assistant.final`` events instead of cancelling the in-flight turn.

The console HTTP adapter stays for everything that is not a chat turn
(memory, journal, persona, hostos, history) and is reached through the
:class:`JawlChatRouter` delegation.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .jawl_adapter import (
    JawlTurnCancelled,
    JawlUnavailable,
    JawlUnsafeResponse,
    filter_user_delta,
    filter_user_response,
)

_RECONNECT_DELAYS = (0.2, 0.5, 1.0, 2.0)
_MAX_LINE_BYTES = 512 * 1024
_MAX_PENDING_EVENTS = 256
_MAX_PENDING_TURNS = 16
_DONE_TURNS_KEEP = 128
_DONE_TURNS_TTL_SECONDS = 300.0
_MAX_REPLAY_FILE_BYTES = 2 * 1024 * 1024


class JawlTerminalGateway:
    """Native correlated turns over one persistent terminal connection."""

    supports_native_envelope = True

    def __init__(
        self,
        port_file: str | Path,
        *,
        timeout_seconds: float = 60.0,
        connect_timeout: float = 3.0,
    ) -> None:
        self.port_file = Path(port_file)
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self.connect_timeout = max(0.5, float(connect_timeout))
        self.last_chat_status = "starting"
        self.last_chat_error = ""
        self._write_lock = threading.RLock()
        self._wait_lock = threading.Condition()
        self._pending: dict[str, deque[dict[str, Any]]] = {}
        self._done_turns: OrderedDict[str, float] = OrderedDict()
        self._broadcasts: deque[dict[str, Any]] = deque(maxlen=20)
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._running = False
        self._last_seq = 0
        self._failure_streak = 0
        self._blocked_until = 0.0

    # ------------------------------------------------------------------ API

    def start(self) -> None:
        """Connect eagerly so health reflects the real transport state."""
        self._ensure_reader()

    def recent_broadcasts(self) -> list[dict[str, Any]]:
        """Bounded window of the agent's autonomous (background) messages."""
        with self._wait_lock:
            return list(self._broadcasts)

    def chat_status(self) -> str:
        with self._write_lock:
            if self._socket is not None:
                return "connected"
        if self.last_chat_status in {"offline", "invalid_port_file"}:
            return self.last_chat_status
        return "starting" if self.port_file.exists() else "offline"

    def respond_envelope(
        self,
        text: str,
        cancel_event: threading.Event | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        for event in self.stream_envelope(text, cancel_event=cancel_event, correlation_id=correlation_id):
            if event.get("type") == "final":
                response = event.get("response")
                if isinstance(response, dict):
                    return response
        raise JawlUnavailable("JAWL terminal gateway produced no final envelope")

    def stream_envelope(
        self,
        text: str,
        cancel_event: threading.Event | None = None,
        correlation_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("JAWL chat text must not be empty")
        if time.monotonic() < self._blocked_until:
            raise JawlUnavailable("JAWL terminal gateway is cooling down after repeated failures")
        turn_id = str(correlation_id or f"turn-{uuid4().hex}")[:128]
        # A fresh submit must not inherit replayed events for a reused turn
        # id (the console journal replays on reconnect).
        with self._wait_lock:
            self._pending.pop(turn_id, None)
            self._done_turns.pop(turn_id, None)
        self.last_chat_status = "starting"
        self.last_chat_error = ""
        try:
            self._submit(clean, turn_id)
            for event in self._wait_events(turn_id, cancel_event):
                event_type = str(event.get("type") or "")
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                if event_type == "assistant.delta":
                    try:
                        fragment = filter_user_delta(payload.get("text", ""))
                    except JawlUnsafeResponse as exc:
                        self.last_chat_status = "invalid_response"
                        raise JawlUnavailable("JAWL returned an unsafe Companion delta") from exc
                    if fragment:
                        yield {"type": "delta", "text": fragment}
                elif event_type == "assistant.final":
                    response = dict(payload.get("response") or {})
                    try:
                        response["text"] = filter_user_response(response.get("text", ""))
                    except JawlUnsafeResponse as exc:
                        self.last_chat_status = "invalid_response"
                        raise JawlUnavailable("JAWL returned an unsafe Companion response") from exc
                    self.last_chat_status = "connected"
                    self._failure_streak = 0
                    yield {"type": "final", "response": response}
                    return
                elif event_type == "turn.cancelled":
                    self.last_chat_status = "cancelled"
                    raise JawlTurnCancelled("JAWL cancelled the turn")
                elif event_type == "turn.error":
                    self.last_chat_status = "offline"
                    raise JawlUnavailable(str(payload.get("reason") or "JAWL turn failed"))
            raise JawlUnavailable("JAWL produced no terminal Companion event")
        except JawlUnavailable:
            self._failure_streak += 1
            if self._failure_streak >= 4:
                # Circuit breaker: stop hammering a broken transport and let
                # it cool down before the next attempt.
                self._blocked_until = time.monotonic() + 30.0
                self._failure_streak = 0
            raise
        finally:
            self._finish_turn(turn_id)

    def respond(
        self,
        text: str,
        cancel_event: threading.Event | None = None,
        correlation_id: str | None = None,
    ) -> str:
        envelope = self.respond_envelope(text, cancel_event=cancel_event, correlation_id=correlation_id)
        return str(envelope.get("text", ""))

    def close(self) -> None:
        self._running = False
        with self._write_lock:
            connection = self._socket
            self._socket = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass

    # ------------------------------------------------------------- internals

    def _read_port(self) -> int:
        try:
            port = int(self.port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            self.last_chat_status = "invalid_port_file" if self.port_file.exists() else "offline"
            raise JawlUnavailable("JAWL terminal port file is unavailable") from exc
        if not 1 <= port <= 65535:
            self.last_chat_status = "invalid_port_file"
            raise JawlUnavailable("JAWL terminal port is invalid")
        return port

    def _ensure_reader(self) -> None:
        with self._write_lock:
            if self._reader is not None and self._reader.is_alive():
                return
            self._running = True
            self._reader = threading.Thread(target=self._run, name="jawl-terminal-gateway", daemon=True)
            self._reader.start()

    def _run(self) -> None:
        delay_index = 0
        while self._running:
            try:
                self._connect()
                delay_index = 0
                self._read_loop()
            except Exception as exc:  # noqa: BLE001 - the reader must survive any transport fault
                self.last_chat_error = f"{type(exc).__name__}: {exc}"[:200]
                if self.last_chat_status not in {"invalid_port_file"}:
                    self.last_chat_status = "offline"
            finally:
                with self._write_lock:
                    connection = self._socket
                    self._socket = None
                if connection is not None:
                    try:
                        connection.close()
                    except OSError:
                        pass
            if not self._running:
                break
            time.sleep(_RECONNECT_DELAYS[min(delay_index, len(_RECONNECT_DELAYS) - 1)])
            delay_index += 1

    def _connect(self) -> None:
        self._sync_cursor_with_replay_file()
        port = self._read_port()
        connection = socket.create_connection(("127.0.0.1", port), timeout=self.connect_timeout)
        connection.settimeout(0.5)
        handshake = f"JAWL_GATEWAY {self._last_seq}\n".encode("utf-8")
        connection.sendall(handshake)
        with self._write_lock:
            self._socket = connection
        self.last_chat_status = "connected"
        self.last_chat_error = ""

    def _sync_cursor_with_replay_file(self) -> None:
        """Reset a stale cursor when JAWL's sequence space was restarted.

        JAWL persists gateway events next to the terminal port file and
        continues ``event_seq`` across restarts. If that journal is wiped
        while the Companion keeps a high cursor, every new event would be
        seen as a stale replay and mute the stream forever. Comparing the
        persisted high-water mark with the cursor detects that reset.
        """
        events_file = self.port_file.parent / "gateway_events.json"
        try:
            if events_file.stat().st_size > _MAX_REPLAY_FILE_BYTES:
                return
            payload = json.loads(events_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            return
        high_water = 0
        for event in events:
            sequence = event.get("event_seq") if isinstance(event, dict) else None
            if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > high_water:
                high_water = sequence
        if high_water and high_water < self._last_seq:
            self._last_seq = 0

    def _read_loop(self) -> None:
        buffer = bytearray()
        while self._running:
            with self._write_lock:
                connection = self._socket
            if connection is None:
                raise JawlUnavailable("JAWL terminal channel is closed")
            try:
                chunk = connection.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise JawlUnavailable("JAWL terminal channel closed by JAWL")
            buffer.extend(chunk)
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                if 0 < len(raw) <= _MAX_LINE_BYTES:
                    self._dispatch_line(raw)
            if len(buffer) > _MAX_LINE_BYTES:
                # A peer that never sends a newline must not grow this buffer
                # without bound; reconnect instead of accumulating garbage.
                raise JawlUnavailable("JAWL terminal line exceeded the frame bound")

    def _dispatch_line(self, raw: bytes) -> None:
        try:
            packet = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return
        if not isinstance(packet, dict):
            return
        event = packet.get("gateway_event")
        if not isinstance(event, dict):
            # Legacy broadcast lines ({"text","time"}) carry the agent's
            # AUTONOMOUS messages (heartbeat cycles have no companion turn).
            # They never arrive as typed events, so keep a bounded recent
            # window for the shell to surface background activity.
            text = str(packet.get("text") or "").strip()
            if text:
                self._broadcasts.append({"text": text[:400], "ts": round(time.time(), 3)})
            return
        sequence = event.get("event_seq")
        if not isinstance(sequence, int) or sequence <= self._last_seq:
            return
        self._last_seq = sequence
        turn_id = str(event.get("turn_id") or "")
        if not turn_id:
            return
        with self._wait_lock:
            if turn_id in self._done_turns:
                return
            bucket = self._pending.get(turn_id)
            if bucket is None:
                while len(self._pending) >= _MAX_PENDING_TURNS:
                    oldest = next(iter(self._pending))
                    if oldest == turn_id:
                        break
                    self._pending.pop(oldest, None)
                bucket = self._pending.setdefault(turn_id, deque(maxlen=_MAX_PENDING_EVENTS))
            bucket.append(event)
            self._wait_lock.notify_all()

    def _finish_turn(self, turn_id: str) -> None:
        """Forget a finished turn and remember it briefly for late replays."""
        now = time.monotonic()
        with self._wait_lock:
            self._pending.pop(turn_id, None)
            self._done_turns[turn_id] = now
            self._done_turns.move_to_end(turn_id)
            while len(self._done_turns) > _DONE_TURNS_KEEP:
                self._done_turns.popitem(last=False)
            while self._done_turns:
                oldest_id = next(iter(self._done_turns))
                if now - self._done_turns[oldest_id] <= _DONE_TURNS_TTL_SECONDS:
                    break
                self._done_turns.popitem(last=False)

    def _submit(self, text: str, turn_id: str) -> None:
        self._ensure_reader()
        deadline = time.monotonic() + self.timeout_seconds
        line = (json.dumps({"text": text, "turn_id": turn_id}, ensure_ascii=False) + "\n").encode("utf-8")
        while time.monotonic() < deadline:
            with self._write_lock:
                connection = self._socket
                if connection is not None:
                    try:
                        connection.sendall(line)
                        return
                    except OSError:
                        self._socket = None
            time.sleep(0.1)
        raise JawlUnavailable("JAWL terminal channel did not come online")

    def _cancel_turn(self, turn_id: str) -> None:
        line = (
            json.dumps({"type": "cancel", "turn_id": turn_id, "reason": "Companion superseded the turn"}, ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        with self._write_lock:
            connection = self._socket
            if connection is None:
                return
            try:
                connection.sendall(line)
            except OSError:
                self._socket = None

    def _wait_events(self, turn_id: str, cancel_event: threading.Event | None) -> Iterator[dict[str, Any]]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            with self._wait_lock:
                bucket = self._pending.get(turn_id)
                event = bucket.popleft() if bucket else None
            if event is not None:
                if cancel_event is not None and cancel_event.is_set():
                    self._cancel_turn(turn_id)
                    raise JawlTurnCancelled("JAWL turn superseded by a newer message")
                yield event
                continue
            if cancel_event is not None and cancel_event.is_set():
                self._cancel_turn(turn_id)
                raise JawlTurnCancelled("JAWL turn superseded by a newer message")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JawlUnavailable("JAWL produced no terminal event before timeout")
            with self._wait_lock:
                self._wait_lock.wait(min(0.25, remaining))


class JawlChatRouter:
    """Route chat turns through the terminal gateway, everything else to the console."""

    supports_native_envelope = True

    def __init__(self, console: Any, terminal: JawlTerminalGateway) -> None:
        self.console = console
        self.terminal = terminal

    def chat_status(self) -> str:
        return self.terminal.chat_status()

    def recent_broadcasts(self) -> list[dict[str, Any]]:
        get = getattr(self.terminal, "recent_broadcasts", None)
        return get() if callable(get) else []

    def respond_envelope(self, text: str, cancel_event: threading.Event | None = None, correlation_id: str | None = None) -> dict[str, Any]:
        return self.terminal.respond_envelope(text, cancel_event=cancel_event, correlation_id=correlation_id)

    def stream_envelope(self, text: str, cancel_event: threading.Event | None = None, correlation_id: str | None = None) -> Iterator[dict[str, Any]]:
        return self.terminal.stream_envelope(text, cancel_event=cancel_event, correlation_id=correlation_id)

    def respond(self, text: str, cancel_event: threading.Event | None = None, correlation_id: str | None = None) -> str:
        return self.terminal.respond(text, cancel_event=cancel_event, correlation_id=correlation_id)

    def close(self) -> None:
        self.terminal.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.console, name)


__all__ = ["JawlChatRouter", "JawlTerminalGateway"]
