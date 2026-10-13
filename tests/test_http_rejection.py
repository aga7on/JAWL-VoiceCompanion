"""Rejected HTTP bodies must not reset small clients or stall the server."""

import http.client
from contextlib import closing
import io
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.web import CompanionRequestHandler, MAX_BODY_BYTES, create_server


class HttpRejectionTests(unittest.TestCase):
    def _handler(self, body=b"invalid JSON", **headers):
        handler = object.__new__(CompanionRequestHandler)
        handler.command = "POST"
        handler.headers = {"Content-Length": str(len(body)), **headers}
        handler.connection = Mock()
        handler.connection.gettimeout.return_value = None
        handler.rfile = io.BytesIO(body)
        return handler

    def test_small_rejected_body_is_consumed_without_json_parsing(self):
        handler = self._handler()
        handler._discard_rejected_body()
        self.assertEqual(handler.rfile.read(), b"")
        self.assertTrue(handler._request_body_consumed)
        self.assertTrue(handler.close_connection)
        handler.connection.settimeout.assert_called_with(None)

    def test_consumed_body_is_never_read_again(self):
        handler = self._handler()
        handler._request_body_consumed = True
        handler._discard_rejected_body()
        self.assertEqual(handler.rfile.tell(), 0)
        handler.connection.settimeout.assert_not_called()

    def test_invalid_oversized_or_chunked_request_is_not_drained(self):
        for headers in ({"Content-Length": "bad"}, {"Content-Length": "-1"},
                        {"Content-Length": str(MAX_BODY_BYTES + 1)}, {"Transfer-Encoding": "chunked"}):
            with self.subTest(headers=headers):
                handler = self._handler(**headers)
                handler._discard_rejected_body()
                self.assertEqual(handler.rfile.tell(), 0)
                handler.connection.settimeout.assert_not_called()

    def test_drain_has_total_deadline_even_if_bytes_keep_arriving(self):
        handler = self._handler(**{"Content-Length": "64"})
        handler.rfile = Mock()
        handler.rfile.read1.return_value = b"x"
        with patch("jawl_voicecompanion.web.time.monotonic", side_effect=[0.0, 0.0, 0.1, 0.21]):
            handler._discard_rejected_body()
        self.assertEqual(handler.rfile.read1.call_count, 2)
        self.assertFalse(handler._request_body_consumed)
        handler.connection.settimeout.assert_called_with(None)

    def _server(self):
        server = create_server(port=0, frontend_dir=Path(__file__).resolve().parents[1] / "frontend")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.addCleanup(cleanup)
        return server

    def test_repeated_small_unauthenticated_posts_return_403(self):
        server = self._server()
        for _ in range(32):
            with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)) as client:
                client.request("POST", "/api/voice/preface", b'{"session_id":"fixture"}', {"Content-Type": "application/json"})
                response = client.getresponse()
                self.assertEqual(response.status, 403)
                self.assertIn(b"error", response.read())

    def test_missing_upload_bytes_do_not_block_rejection_indefinitely(self):
        server = self._server()
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as client:
            client.sendall(b"POST /api/voice/preface HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 32\r\n\r\n")
            response = http.client.HTTPResponse(client)
            response.begin()
            self.assertEqual(response.status, 403)
            response.read()


if __name__ == "__main__":
    unittest.main()
