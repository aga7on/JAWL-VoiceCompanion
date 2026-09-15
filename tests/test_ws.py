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


if __name__ == "__main__":
    unittest.main()
