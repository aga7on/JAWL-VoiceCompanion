"""Minimal RFC 6455 WebSocket server support for the stdlib control plane.

The companion intentionally has no async web framework: this module adds
just enough of the WebSocket protocol (handshake, masked client frames,
fragmentation, ping/pong/close) for the P2 single-connection transport
between the browser and the Companion.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from typing import Any

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_FRAME_BYTES = 256 * 1024
_MAX_MESSAGE_BYTES = 1024 * 1024

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class WebSocketError(RuntimeError):
    """Raised when a peer violates the WebSocket protocol."""


def is_websocket_upgrade(headers: Any) -> bool:
    try:
        upgrade = str(headers.get("Upgrade") or "").strip().lower()
        connection = str(headers.get("Connection") or "").lower()
        key = str(headers.get("Sec-WebSocket-Key") or "").strip()
        version = str(headers.get("Sec-WebSocket-Version") or "").strip()
    except Exception:  # noqa: BLE001 - a broken header block is not an upgrade
        return False
    return (
        upgrade == "websocket"
        and "upgrade" in connection
        and bool(key)
        and version == "13"
    )


def handshake_accept(key: str) -> str:
    digest = hashlib.sha1((key + _GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def send_handshake_response(handler: Any) -> None:
    key = str(handler.headers.get("Sec-WebSocket-Key") or "").strip()
    accept = handshake_accept(key)
    handler.send_response(101, "Switching Protocols")
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()


def _read_exact(stream: Any, count: int) -> bytes:
    buffer = bytearray()
    while len(buffer) < count:
        chunk = stream.read(count - len(buffer))
        if not chunk:
            raise WebSocketError("websocket connection closed")
        buffer.extend(chunk)
    return bytes(buffer)


def read_frame(stream: Any) -> tuple[int, bool, bytes]:
    """Read one frame; returns (opcode, fin, payload)."""
    header = _read_exact(stream, 2)
    first, second = header[0], header[1]
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(stream, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(stream, 8))[0]
    if length > _MAX_FRAME_BYTES:
        raise WebSocketError("websocket frame exceeds the bounded limit")
    if not masked:
        raise WebSocketError("client frames must be masked")
    mask = _read_exact(stream, 4)
    payload = bytearray(_read_exact(stream, length))
    for index in range(length):
        payload[index] ^= mask[index % 4]
    return opcode, fin, bytes(payload)


def _encode_frame(opcode: int, payload: bytes) -> bytes:
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    return bytes(header) + payload


class WebSocketConnection:
    """Server-side connection bound to one handler thread."""

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer
        self.closed = False
        self._fragments: list[bytes] = []
        self._fragment_opcode: int | None = None

    def read_message(self) -> str | None:
        """Return the next complete text message, or None after close."""
        while not self.closed:
            try:
                opcode, fin, payload = read_frame(self._reader)
            except WebSocketError:
                self.closed = True
                return None
            if opcode == OPCODE_CLOSE:
                try:
                    self.send_close()
                except OSError:
                    pass
                self.closed = True
                return None
            if opcode == OPCODE_PING:
                try:
                    self.send_pong(payload)
                except OSError:
                    self.closed = True
                    return None
                continue
            if opcode == OPCODE_PONG:
                continue
            if opcode in (OPCODE_TEXT, OPCODE_BINARY):
                if fin:
                    data = payload
                else:
                    self._fragments = [payload]
                    self._fragment_opcode = opcode
                    continue
            elif opcode == OPCODE_CONTINUATION:
                if self._fragment_opcode is None:
                    raise WebSocketError("continuation frame without a start")
                self._fragments.append(payload)
                if not fin:
                    if sum(len(item) for item in self._fragments) > _MAX_MESSAGE_BYTES:
                        raise WebSocketError("websocket message exceeds the bounded limit")
                    continue
                data = b"".join(self._fragments)
                opcode = self._fragment_opcode
                self._fragments = []
                self._fragment_opcode = None
            else:
                raise WebSocketError("unsupported websocket opcode")
            if sum(len(item) for item in self._fragments) + len(data) > _MAX_MESSAGE_BYTES:
                raise WebSocketError("websocket message exceeds the bounded limit")
            if opcode == OPCODE_BINARY:
                return data.decode("latin-1")
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WebSocketError("websocket text frame is not utf-8") from exc
        return None

    def send_text(self, text: str) -> None:
        if self.closed:
            return
        self._writer.sendall(_encode_frame(OPCODE_TEXT, text.encode("utf-8")))

    def send_pong(self, payload: bytes) -> None:
        self._writer.sendall(_encode_frame(OPCODE_PONG, payload[:125]))

    def send_close(self, code: int = 1000) -> None:
        if self.closed:
            return
        self._writer.sendall(_encode_frame(OPCODE_CLOSE, struct.pack("!H", code)))
        self.closed = True
