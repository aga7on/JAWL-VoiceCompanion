import base64
import json
import os
import socket
import struct
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402


def _client_text_frame(text: str) -> bytes:
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(0x80 | len(payload))
    else:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", len(payload)))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + masked


def _read_server_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = sock.recv(2)
    if len(header) < 2:
        raise AssertionError("server closed the socket")
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    payload = bytearray()
    while len(payload) < length:
        payload.extend(sock.recv(length - len(payload)))
    return opcode, bytes(payload)


def _client_frame(opcode: int, payload: bytes = b"", *, fin: bool = True, mask: bool = True, rsv: int = 0) -> bytes:
    header = bytearray([(0x80 if fin else 0x00) | ((rsv & 0x07) << 4) | (opcode & 0x0F)])
    length = len(payload)
    flags = 0x80 if mask else 0x00
    if length < 126:
        header.append(flags | length)
    elif length < 65536:
        header.append(flags | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(flags | 127)
        header.extend(struct.pack("!Q", length))
    if mask:
        mask_key = os.urandom(4)
        header.extend(mask_key)
        payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + payload


class WebSocketTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _connect(self, *, cookie: bool = True):
        sock = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        lines = [
            "GET /api/ws HTTP/1.1",
            f"Host: {self.host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            f"Origin: http://{self.host}",
        ]
        if cookie:
            lines.append(f"Cookie: companion_session={self.server.session_token}")
        request = "\r\n".join(lines) + "\r\n\r\n"
        sock.sendall(request.encode("ascii"))
        return sock

    def test_handshake_requires_session(self):
        sock = self._connect(cookie=False)
        try:
            response = sock.recv(4096).decode("latin-1")
            self.assertIn("403", response.split("\r\n", 1)[0])
        finally:
            sock.close()

    def test_ping_and_chat_roundtrip(self):
        sock = self._connect()
        sock.settimeout(5)
        try:
            response = b""
            while b"\r\n\r\n" not in response:
                response += sock.recv(4096)
            self.assertIn("101", response.decode("latin-1").split("\r\n", 1)[0])

            sock.sendall(_client_text_frame(json.dumps({"action": "ping"})))
            opcode, payload = _read_server_frame(sock)
            self.assertEqual(opcode, 0x1)
            self.assertEqual(json.loads(payload.decode("utf-8")), {"type": "pong"})

            sock.sendall(_client_text_frame(json.dumps({"action": "chat", "text": "привет"})))
            kinds = []
            final_text = ""
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                opcode, payload = _read_server_frame(sock)
                message = json.loads(payload.decode("utf-8"))
                kinds.append(message.get("type"))
                if message.get("type") == "final":
                    final_text = str(message.get("response", {}).get("text", ""))
                    break
            self.assertIn("delta", kinds)
            self.assertIn("final", kinds)
            self.assertIn("на связи", final_text)

            sock.sendall(_client_text_frame(json.dumps({"action": "nope"})))
            opcode, payload = _read_server_frame(sock)
            self.assertEqual(json.loads(payload.decode("utf-8"))["type"], "error")
        finally:
            sock.close()

    def test_voice_chunk_reports_voice_mem_gap(self):
        sock = self._connect()
        sock.settimeout(5)
        try:
            response = b""
            while b"\r\n\r\n" not in response:
                response += sock.recv(4096)
            sock.sendall(_client_text_frame(json.dumps({
                "action": "voice_chunk",
                "pcm16_base64": base64.b64encode(b"\x00\x01" * 160).decode("ascii"),
                "sample_rate": 16000,
                "channels": 1,
            })))
            opcode, payload = _read_server_frame(sock)
            message = json.loads(payload.decode("utf-8"))
            self.assertEqual(message["type"], "voice_ack")
            self.assertFalse(message["ok"])
            self.assertIn("VoiceMem", message["error"])
        finally:
            sock.close()


    def _handshake(self, sock: socket.socket) -> None:
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        self.assertIn("101", response.decode("latin-1").split("\r\n", 1)[0])

    def _expect_closed(self, sock: socket.socket) -> None:
        sock.settimeout(3)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    return
        except socket.timeout:
            raise AssertionError("server did not close the connection")

    def test_fragmented_message_is_assembled(self):
        sock = self._connect()
        sock.settimeout(5)
        try:
            self._handshake(sock)
            body = json.dumps({"action": "ping"}).encode("utf-8")
            sock.sendall(_client_frame(0x1, body[:8], fin=False))
            sock.sendall(_client_frame(0x0, body[8:], fin=True))
            opcode, payload = _read_server_frame(sock)
            self.assertEqual(opcode, 0x1)
            self.assertEqual(json.loads(payload.decode("utf-8")), {"type": "pong"})
        finally:
            sock.close()

    def test_ping_with_payload_is_echoed_in_pong(self):
        sock = self._connect()
        sock.settimeout(5)
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x9, b"hi"))
            opcode, payload = _read_server_frame(sock)
            self.assertEqual(opcode, 0xA)
            self.assertEqual(payload, b"hi")
        finally:
            sock.close()

    def test_close_frame_is_acknowledged_and_closed(self):
        sock = self._connect()
        sock.settimeout(5)
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x8, struct.pack("!H", 1000)))
            opcode, _ = _read_server_frame(sock)
            self.assertEqual(opcode, 0x8)
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_unmasked_frame_closes_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x1, b'{"action":"ping"}', mask=False))
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_reserved_bits_close_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x1, b'{"action":"ping"}', rsv=1))
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_fragmented_control_frame_closes_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x9, b"x", fin=False))
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_oversized_control_frame_closes_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x9, b"x" * 126))
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_data_frame_inside_fragmented_message_closes_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x1, b'{"action":', fin=False))
            sock.sendall(_client_frame(0x1, b'"ping"}'))
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_oversized_frame_claim_closes_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            header = bytearray([0x81, 0x80 | 127])
            header.extend(struct.pack("!Q", 300 * 1024))
            sock.sendall(bytes(header))
            self._expect_closed(sock)
        finally:
            sock.close()

    def test_invalid_utf8_text_closes_the_connection(self):
        sock = self._connect()
        try:
            self._handshake(sock)
            sock.sendall(_client_frame(0x1, b"\xff\xfe\xfd"))
            self._expect_closed(sock)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
