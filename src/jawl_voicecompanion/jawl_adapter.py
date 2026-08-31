"""Small synchronous adapter for JAWL's local HostTerminalClient protocol."""

from __future__ import annotations

import json
import socket
from pathlib import Path


class JawlUnavailable(ConnectionError):
    """Raised when the configured JAWL terminal is not reachable."""


class JawlTerminalAdapter:
    """Send one text turn through JAWL's loopback terminal channel.

    The protocol has no response correlation ID yet, so this first adapter
    uses a short-lived connection per user turn and consumes the first agent
    response. A later streaming adapter will use a persistent session and
    explicit turn IDs.
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
        return "configured"

    def respond(self, text: str) -> str:
        port = self._read_port()
        payload = (json.dumps({"text": text}, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=self.timeout) as connection:
                connection.settimeout(self.timeout)
                connection.sendall(self.handshake + payload)
                raw = connection.makefile("rb").readline(65536)
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
        self.last_status = "connected"
        return answer.strip()

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

