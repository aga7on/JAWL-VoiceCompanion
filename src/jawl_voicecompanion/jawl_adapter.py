"""Small synchronous adapter for JAWL's local HostTerminalClient protocol."""

from __future__ import annotations

import json
import re
import socket
import time
from pathlib import Path
from threading import Event


class JawlUnavailable(ConnectionError):
    """Raised when the configured JAWL terminal is not reachable."""


class JawlTurnCancelled(ConnectionError):
    """Raised when a newer turn cancels a pending JAWL response."""


class JawlUnsafeResponse(ValueError):
    """Raised when a model response still contains internal control markup."""


_HIDDEN_BLOCK = re.compile(
    r"<(?P<tag>think|analysis|reasoning|reflection|tool_call|tool_result)\b[^>]*>"
    r".*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_FINAL_BLOCK = re.compile(r"<final\b[^>]*>(?P<text>.*?)</final\s*>", re.IGNORECASE | re.DOTALL)
_INTERNAL_TAG = re.compile(
    r"</?(?:think|analysis|reasoning|reflection|tool_call|tool_result)\b[^>]*>",
    re.IGNORECASE,
)
_INTERNAL_LINE = re.compile(
    r"^\s*(?:\[(?:thoughts?|observation|reasoning|reflection|action(?: result)?|tool(?: call| result)?)\]"
    r"|(?:thoughts?|observation|reasoning|reflection|action(?: result)?|tool(?: call| result)?)\s*:)",
    re.IGNORECASE | re.MULTILINE,
)


def filter_user_response(text: str) -> str:
    """Remove paired hidden blocks and reject unbounded internal markup."""
    clean = str(text or "").replace("\x00", "").strip()
    if not clean:
        raise JawlUnsafeResponse("JAWL returned an empty response")
    clean = re.sub(r"<!--.*?-->", "", clean, flags=re.DOTALL)
    clean = _HIDDEN_BLOCK.sub("", clean)
    final = _FINAL_BLOCK.search(clean)
    if final:
        clean = final.group("text").strip()
    if _INTERNAL_TAG.search(clean) or _INTERNAL_LINE.search(clean):
        raise JawlUnsafeResponse("JAWL response contains internal control markup")
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    if not clean:
        raise JawlUnsafeResponse("JAWL response contains no user-facing text")
    return clean


class JawlTerminalAdapter:
    """Send one text turn through JAWL's loopback terminal channel.

    The current JAWL channel is event/broadcast based: the input line queues
    a user message, and JAWL must call ``send_message_to_terminal`` to emit a
    response line. It has no response correlation ID, so this adapter uses a
    short-lived connection and consumes the first broadcast. A missing
    broadcast is an explicit degraded result, not a fabricated answer.
    """

    handshake = b"JAWL_HANDSHAKE\n"

    def __init__(self, port_file: Path, timeout: float = 30.0):
        self.port_file = Path(port_file)
        self.timeout = timeout
        self.last_status = "not_checked"

    def __call__(self, text: str) -> str:
        return self.respond(text)

    def status(self) -> str:
        if not self.port_file.exists():
            return "offline"
        try:
            int(self.port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return "invalid_port_file"
        if self.last_status in {"connected", "no_broadcast", "empty_response", "invalid_response", "offline"}:
            return self.last_status
        return "configured"

    def respond(self, text: str, cancel_event: Event | None = None) -> str:
        port = self._read_port()
        payload = (json.dumps({"text": text}, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=self.timeout) as connection:
                connection.settimeout(0.2 if cancel_event is not None else self.timeout)
                connection.sendall(self.handshake + payload)
                raw = self._read_response(connection, cancel_event)
        except (JawlTurnCancelled, JawlUnavailable):
            raise
        except (OSError, TimeoutError) as exc:
            self.last_status = "offline"
            raise JawlUnavailable("JAWL terminal is not reachable") from exc

        if not raw:
            self.last_status = "empty_response"
            raise JawlUnavailable("JAWL terminal closed without a response")
        response = raw.decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            parsed = {"text": response}
        answer = parsed.get("text") if isinstance(parsed, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            self.last_status = "invalid_response"
            raise JawlUnavailable("JAWL returned an invalid text response")
        try:
            answer = filter_user_response(answer)
        except JawlUnsafeResponse as exc:
            self.last_status = "invalid_response"
            raise JawlUnavailable("JAWL returned internal control markup") from exc
        self.last_status = "connected"
        return answer

    def _read_response(self, connection: socket.socket, cancel_event: Event | None) -> bytes:
        deadline = time.monotonic() + self.timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise JawlTurnCancelled("JAWL response superseded by a newer turn")
            try:
                chunk = connection.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return bytes(buffer)
            buffer.extend(chunk)
            if len(buffer) > 65536:
                raise JawlUnavailable("JAWL response exceeds the bounded limit")
            if b"\n" in buffer:
                return bytes(buffer.split(b"\n", 1)[0])
        self.last_status = "no_broadcast"
        raise JawlUnavailable("JAWL produced no terminal broadcast before timeout")

    def _read_port(self) -> int:
        try:
            port = int(self.port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            self.last_status = "offline"
            raise JawlUnavailable("JAWL terminal port file is unavailable") from exc
        if not 1 <= port <= 65535:
            self.last_status = "invalid_port_file"
            raise JawlUnavailable("JAWL terminal port is invalid")
        return port
