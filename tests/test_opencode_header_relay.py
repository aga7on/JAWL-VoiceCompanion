from __future__ import annotations

import importlib.util
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import requests


_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "opencode_header_relay", _ROOT / "scripts" / "opencode_header_relay.py"
)
assert _SPEC and _SPEC.loader
_RELAY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RELAY)


class _ChunkedProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for chunk in (b"data: first\n\n", b"data: [DONE]\n\n"):
            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def log_message(self, *_args: object) -> None:
        return


class RelayTests(unittest.TestCase):
    def test_reframes_chunked_stream_without_waiting_for_eof(self) -> None:
        provider = ThreadingHTTPServer(("127.0.0.1", 0), _ChunkedProvider)
        relay = _RELAY._RelayServer(("127.0.0.1", 0), _RELAY._RelayHandler)
        relay.relay_config = {
            "upstream": ("http", "127.0.0.1", provider.server_address[1], ""),
            "host": "127.0.0.1",
            "key": "test",
            "user_agent": "test",
            "session_id": "",
            "timeout": 5.0,
        }
        provider_thread = Thread(target=provider.serve_forever, daemon=True)
        relay_thread = Thread(target=relay.serve_forever, daemon=True)
        provider_thread.start()
        relay_thread.start()
        try:
            response = requests.post(
                f"http://127.0.0.1:{relay.server_address[1]}/v1/chat/completions",
                json={"stream": True},
                timeout=5,
                stream=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Transfer-Encoding"), "chunked")
            self.assertEqual(
                list(response.iter_lines()),
                [b"data: first", b"", b"data: [DONE]", b""],
            )
        finally:
            relay.shutdown()
            provider.shutdown()
            relay.server_close()
            provider.server_close()
