"""Focused regression coverage for bounded SSE reading and cancellation."""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_web import (  # noqa: E402
    JawlWebUnavailable,
    _SseReader,
)


class _RecordingResponse:
    def __init__(self, lines: list[bytes]):
        self.lines = Queue()
        for line in lines:
            self.lines.put(line)
        self.limits: list[int] = []
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def readline(self, limit=-1):
        self.limits.append(limit)
        try:
            return self.lines.get_nowait()
        except Empty:
            return b""

    def close(self):
        self.closed.set()


class _SseServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, handler_type):
        super().__init__(("127.0.0.1", 0), handler_type)
        self.preheaders_gate = threading.Event()
        self.body_gates: dict[str, threading.Event] = {}
        self.headers_sent: dict[str, threading.Event] = {}
        self.server_thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.server_thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_port}"

    def close(self):
        self.preheaders_gate.set()
        for gate in self.body_gates.values():
            gate.set()
        self.shutdown()
        self.server_close()
        self.server_thread.join(timeout=1)


def _handler_for():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            server = self.server
            if self.path == "/preheaders":
                server.preheaders_gate.wait()
                return
            gate = server.body_gates.setdefault(self.path, threading.Event())
            sent = server.headers_sent.setdefault(self.path, threading.Event())
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            sent.set()
            gate.wait()
            try:
                self.wfile.write(b'data: {"ok": true}\n\n')
                self.wfile.flush()
            except OSError:
                pass

    return Handler


class JawlSseReaderTests(unittest.TestCase):
    def setUp(self):
        self.server = _SseServer(_handler_for())

    def tearDown(self):
        self.server.close()

    def test_stalled_body_stop_closes_owned_socket_and_reaps_reader(self):
        reader = _SseReader(
            urlopen,
            Request(self.server.base_url + "/stall"),
            timeout=8.0,
        )
        reader.start()
        self.assertTrue(self.server.headers_sent.setdefault("/stall", threading.Event()).wait(1.0))
        self.assertTrue(reader.ready.wait(1.0))
        time.sleep(1.1)
        self.assertFalse(reader.done.is_set(), "socket read timeout was not restored after headers")

        started = time.monotonic()
        stopped = reader.stop()
        elapsed = time.monotonic() - started

        self.assertTrue(stopped)
        self.assertLess(elapsed, 1.5)
        self.assertFalse(reader._thread.is_alive())
        self.assertIsNone(reader.error)

    def test_preheaders_timeout_is_bounded_and_reader_is_reaped(self):
        reader = _SseReader(
            urlopen,
            Request(self.server.base_url + "/preheaders"),
            timeout=8.0,
        )
        reader.start()
        self.assertTrue(reader.done.wait(1.5), "initial header wait exceeded its one-second bound")
        self.assertIsInstance(reader.error, JawlWebUnavailable)
        started = time.monotonic()
        self.assertTrue(reader.stop())
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertFalse(reader._thread.is_alive())

    def test_stopping_reader_a_leaves_reader_b_and_its_socket_live(self):
        opener = urlopen
        reader_a = _SseReader(opener, Request(self.server.base_url + "/a"), timeout=8.0)
        reader_b = _SseReader(opener, Request(self.server.base_url + "/b"), timeout=8.0)
        reader_a.start()
        reader_b.start()
        self.assertTrue(self.server.headers_sent.setdefault("/a", threading.Event()).wait(1.0))
        self.assertTrue(self.server.headers_sent.setdefault("/b", threading.Event()).wait(1.0))
        self.assertTrue(reader_a.ready.wait(1.0))
        self.assertTrue(reader_b.ready.wait(1.0))

        self.assertTrue(reader_a.stop())
        self.assertFalse(reader_b.done.is_set())
        self.server.body_gates["/b"].set()
        event = None
        deadline = time.monotonic() + 1.0
        while event is None and time.monotonic() < deadline:
            event = reader_b.get(0.05)
        self.assertEqual(event, {"ok": True})
        self.assertTrue(reader_b.stop())
        self.assertFalse(reader_a._thread.is_alive())
        self.assertFalse(reader_b._thread.is_alive())

    def test_late_custom_response_is_closed_without_read_or_publication(self):
        entered = threading.Event()
        release = threading.Event()
        response = _RecordingResponse([b'data: {"late": true}\n', b"\n"])

        def opener(_request, timeout):
            self.assertEqual(timeout, 1.0)
            entered.set()
            release.wait(2.0)
            return response

        reader = _SseReader(opener, Request("http://127.0.0.1/late"), timeout=5.0)
        reader.start()
        self.assertTrue(entered.wait(1.0))
        started = time.monotonic()
        self.assertFalse(reader.stop())
        self.assertLess(time.monotonic() - started, 1.5)
        release.set()
        self.assertTrue(reader.done.wait(1.0))

        self.assertTrue(response.closed.is_set())
        self.assertEqual(response.limits, [])
        self.assertIsNone(reader.get(0.01))
        self.assertFalse(reader.has_pending())
        self.assertFalse(reader._thread.is_alive())

    def test_multiline_packet_and_oversized_line_use_bounded_read_limit(self):
        valid = _RecordingResponse([
            b'data: {"message":\n',
            b'data: "hello"}\n',
            b"\n",
        ])
        reader = _SseReader(lambda *_args, **_kwargs: valid, Request("http://127.0.0.1/"), timeout=2.0)
        reader.start()
        self.assertTrue(reader.done.wait(1.0))
        self.assertEqual(reader.get(0.01), {"message": "hello"})
        self.assertEqual(valid.limits, [128 * 1024 + 1] * 4)

        oversized = _RecordingResponse([b"x" * (128 * 1024 + 1)])
        reader = _SseReader(lambda *_args, **_kwargs: oversized, Request("http://127.0.0.1/"), timeout=2.0)
        reader.start()
        self.assertTrue(reader.done.wait(1.0))
        self.assertIsInstance(reader.error, JawlWebUnavailable)
        self.assertIn("line", str(reader.error))
        self.assertEqual(oversized.limits, [128 * 1024 + 1])
        self.assertTrue(reader.stop())

    def test_data_packet_overflow_fails_with_bounded_error(self):
        response = _RecordingResponse([
            b"data: " + b"a" * (70 * 1024) + b"\n",
            b"data: " + b"b" * (70 * 1024) + b"\n",
        ])
        reader = _SseReader(lambda *_args, **_kwargs: response, Request("http://127.0.0.1/"), timeout=2.0)
        reader.start()
        self.assertTrue(reader.done.wait(1.0))
        self.assertIsInstance(reader.error, JawlWebUnavailable)
        self.assertIn("event", str(reader.error))

    def test_queue_overflow_is_reported_and_stop_drains_pending_events(self):
        reader = _SseReader(lambda *_args, **_kwargs: None, Request("http://127.0.0.1/"), timeout=2.0)
        for value in range(64):
            reader._publish(json.dumps({"n": value}))
        with self.assertRaisesRegex(JawlWebUnavailable, "queue overflowed"):
            reader._publish('{"n": 64}')
        self.assertEqual(reader._events.qsize(), 64)
        self.assertTrue(reader.stop())
        self.assertFalse(reader.has_pending())
        with self.assertRaisesRegex(RuntimeError, "cannot be restarted"):
            reader.start()


if __name__ == "__main__":
    unittest.main()
