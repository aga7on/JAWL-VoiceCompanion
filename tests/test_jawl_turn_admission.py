"""Focused lifecycle regressions for native JAWL turn admission."""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled  # noqa: E402
from jawl_voicecompanion.jawl_web import JawlWebChatAdapter, JawlWebUnavailable  # noqa: E402


def _event(kind: str, text: str = "ok") -> SimpleNamespace:
    payload = {"text": text} if kind == "assistant.delta" else {
        "response": {"text": text},
    } if kind == "assistant.final" else {}
    return SimpleNamespace(type=kind, payload=payload)


class _Response:
    def __init__(self, payload: object):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.body


class _RawResponse(_Response):
    def __init__(self, body: bytes):
        self.body = body


class _SseResponse:
    def __init__(self):
        self.lines = Queue()
        self.closed = threading.Event()
        self.lines.put(b"data: {}\n")
        self.lines.put(b"\n")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def readline(self, _limit: int = -1) -> bytes:
        while not self.closed.is_set():
            try:
                return self.lines.get(timeout=0.05)
            except Empty:
                continue
        return b""

    def close(self) -> None:
        self.closed.set()


class TurnAdmissionTests(unittest.TestCase):
    def adapter(self, opener=None) -> JawlWebChatAdapter:
        return JawlWebChatAdapter(
            "http://127.0.0.1:1", native_gateway=True,
            chat_timeout_seconds=2, opener=opener or (lambda *_args, **_kwargs: None),
        )

    def wait_for(self, predicate, timeout: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return bool(predicate())

    def test_sync_and_stream_calls_share_one_serialized_producer(self):
        adapter = self.adapter()
        first_inside = threading.Event()
        release_first = threading.Event()
        state_lock = threading.Lock()
        active = 0
        peak = 0
        starts: list[str] = []
        results: dict[str, object] = {}

        def serialized(text, cancel, correlation):
            nonlocal active, peak
            del cancel, correlation
            with state_lock:
                active += 1
                peak = max(peak, active)
                starts.append(text)
            try:
                if text == "sync":
                    first_inside.set()
                    release_first.wait(1)
                    yield _event("assistant.final", "sync-result")
                else:
                    yield _event("assistant.delta", "stream-")
                    yield _event("assistant.final", "stream-result")
            finally:
                with state_lock:
                    active -= 1

        adapter._iter_native_events_serialized = serialized

        def sync_call():
            results["sync"] = adapter.respond_envelope("sync")

        def stream_call():
            results["stream"] = list(adapter.stream_envelope("stream"))

        sync_thread = threading.Thread(target=sync_call)
        stream_thread = threading.Thread(target=stream_call)
        sync_thread.start()
        self.assertTrue(first_inside.wait(1))
        stream_thread.start()
        self.assertFalse(self.wait_for(lambda: len(starts) > 1, 0.08))
        release_first.set()
        sync_thread.join(1)
        stream_thread.join(1)
        self.assertFalse(sync_thread.is_alive())
        self.assertFalse(stream_thread.is_alive())
        self.assertEqual(peak, 1)
        self.assertEqual(starts, ["sync", "stream"])
        self.assertEqual(results["sync"]["text"], "sync-result")
        self.assertEqual([item["type"] for item in results["stream"]], ["delta", "final"])

    def test_cancelled_waiter_and_pre_cancel_make_no_native_requests(self):
        calls = []
        adapter = self.adapter(lambda request, **_kwargs: calls.append(request))
        adapter._native_turn_lock.acquire()
        cancel = threading.Event()
        result: dict[str, object] = {}

        def wait_for_admission():
            try:
                adapter.respond_envelope("wait", cancel_event=cancel)
            except Exception as exc:  # asserted below
                result["error"] = exc

        waiter = threading.Thread(target=wait_for_admission)
        waiter.start()
        cancel.set()
        waiter.join(1)
        adapter._native_turn_lock.release()
        self.assertFalse(waiter.is_alive())
        self.assertIsInstance(result.get("error"), JawlTurnCancelled)
        self.assertEqual(calls, [])

        pre_cancelled = threading.Event()
        pre_cancelled.set()
        with self.assertRaises(JawlTurnCancelled):
            adapter.respond_envelope("pre-cancel", cancel_event=pre_cancelled)
        self.assertEqual(calls, [])

    def test_invalid_turn_ids_are_rejected_before_admission_or_io(self):
        calls = []
        adapter = self.adapter(lambda request, **_kwargs: calls.append(request))
        invalid = ("", "has spaces", "ключ", "a" * 129, True, 7, ["x"])
        for value in invalid:
            with self.subTest(turn_id=value):
                with self.assertRaises(ValueError):
                    adapter.respond_envelope("invalid id", correlation_id=value)
                self.assertFalse(adapter._native_turn_lock.locked())
        self.assertEqual(calls, [])

    def test_valid_128_character_turn_id_is_preserved_exactly(self):
        adapter = self.adapter()
        identifier = "a" * 128
        received = []

        def serialized(text, cancel, correlation):
            del text, cancel
            received.append(correlation)
            yield _event("assistant.final", "valid")

        adapter._iter_native_events_serialized = serialized
        result = adapter.respond_envelope("valid", correlation_id=identifier)
        self.assertEqual(result["text"], "valid")
        self.assertEqual(received, [identifier])

    def test_paused_consumer_cancellation_releases_admission_and_queue_is_bounded(self):
        adapter = self.adapter()
        cancel = threading.Event()
        source_closed = threading.Event()
        queue_seen = []
        original_queue = __import__("jawl_voicecompanion.jawl_web", fromlist=["Queue"]).Queue

        def recording_queue(*args, **kwargs):
            result = original_queue(*args, **kwargs)
            queue_seen.append(result)
            return result

        def serialized(text, source_cancel, correlation):
            del text, correlation
            try:
                for index in range(100):
                    if source_cancel.is_set():
                        return
                    yield _event("assistant.delta", str(index))
            finally:
                source_closed.set()

        adapter._iter_native_events_serialized = serialized
        with mock.patch("jawl_voicecompanion.jawl_web.Queue", side_effect=recording_queue):
            consumer = adapter._iter_native_events("paused", cancel, None)
            next(consumer)
            self.assertTrue(self.wait_for(lambda: bool(queue_seen) and queue_seen[0].full()))
            self.assertEqual(queue_seen[0].maxsize, 32)
            self.assertLessEqual(queue_seen[0].qsize(), 32)
            cancel.set()
            self.assertTrue(source_closed.wait(1))

            replacement = adapter._iter_native_events("replacement", None, None)
            self.assertEqual(next(replacement).payload["text"], "0")
            replacement.close()
            consumer.close()

    def test_closing_old_consumer_does_not_release_inflight_lease_early(self):
        adapter = self.adapter()
        inflight = threading.Event()
        settle_post = threading.Event()
        old_source_closed = threading.Event()
        starts = []

        def serialized(text, cancel, correlation):
            del correlation
            starts.append(text)
            if text == "old":
                try:
                    yield _event("assistant.delta", "old-started")
                    inflight.set()
                    settle_post.wait(2)  # models an already-started POST settling
                    yield _event("assistant.final", "old")
                finally:
                    old_source_closed.set()
            else:
                yield _event("assistant.final", "replacement")

        adapter._iter_native_events_serialized = serialized
        old = adapter._iter_native_events("old", None, None)
        self.assertEqual(next(old).payload["text"], "old-started")
        self.assertTrue(inflight.wait(1))
        old.close()
        self.assertNotIn("replacement", starts)

        settle_post.set()
        self.assertTrue(old_source_closed.wait(1))
        replacement = adapter._iter_native_events("replacement", None, None)
        self.assertEqual(next(replacement).payload["response"]["text"], "replacement")
        replacement.close()

    def test_thread_constructor_failure_is_reported_without_lock_leak(self):
        adapter = self.adapter()
        adapter._iter_native_events_serialized = lambda *_args: iter((_event("assistant.final"),))
        with mock.patch("jawl_voicecompanion.jawl_web.Thread", side_effect=RuntimeError("ctor")):
            with self.assertRaisesRegex(RuntimeError, "ctor"):
                next(adapter._iter_native_events("ctor", None, None))
        self.assertFalse(adapter._native_turn_lock.locked())

    def test_diagnostic_claim_failure_releases_admission(self):
        adapter = self.adapter()
        with mock.patch.object(adapter, "_claim_native_diagnostics", side_effect=RuntimeError("diagnostic claim")):
            with self.assertRaisesRegex(RuntimeError, "diagnostic claim"):
                next(adapter._iter_native_events("claim", None, None))
        self.assertFalse(adapter._native_turn_lock.locked())

    def test_queue_constructor_failure_is_reported_without_lock_leak(self):
        adapter = self.adapter()
        adapter._iter_native_events_serialized = lambda *_args: iter((_event("assistant.final"),))
        with mock.patch("jawl_voicecompanion.jawl_web.Queue", side_effect=RuntimeError("queue")):
            with self.assertRaisesRegex(RuntimeError, "queue"):
                next(adapter._iter_native_events("queue", None, None))
        self.assertFalse(adapter._native_turn_lock.locked())

    def test_producer_start_failure_releases_lock_for_next_turn(self):
        adapter = self.adapter()
        adapter._iter_native_events_serialized = lambda *_args: iter((_event("assistant.final"),))

        class FailingStart:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("start")

        with mock.patch("jawl_voicecompanion.jawl_web.Thread", FailingStart):
            with self.assertRaisesRegex(RuntimeError, "start"):
                next(adapter._iter_native_events("start", None, None))
        self.assertFalse(adapter._native_turn_lock.locked())
        self.assertEqual(next(adapter._iter_native_events("retry", None, None)).type, "assistant.final")

    def test_source_close_failure_is_reported_after_releasing_lock(self):
        adapter = self.adapter()

        class CloseFails:
            def __init__(self):
                self.sent = False

            def __iter__(self):
                return self

            def __next__(self):
                if self.sent:
                    raise StopIteration
                self.sent = True
                return _event("assistant.final", "first")

            def close(self):
                raise RuntimeError("source close")

        sources = [CloseFails(), iter((_event("assistant.final", "second"),))]
        adapter._iter_native_events_serialized = lambda *_args: sources.pop(0)
        consumer = adapter._iter_native_events("close", None, None)
        self.assertEqual(next(consumer).payload["response"]["text"], "first")
        with self.assertRaisesRegex(RuntimeError, "source close"):
            next(consumer)
        second = adapter._iter_native_events("next", None, None)
        self.assertEqual(next(second).payload["response"]["text"], "second")
        second.close()

    def test_post_failure_and_cancel_requests_use_one_post_and_exact_turn_id(self):
        scenarios = (
            ("lost-ack", lambda: URLError("lost response")),
            ("http-409", lambda: HTTPError("http://local/turn", 409, "conflict", {}, None)),
            ("offline", lambda: OSError("offline")),
            ("invalid-json", lambda: _RawResponse(b"not-json")),
        )
        for name, outcome in scenarios:
            with self.subTest(name=name):
                calls = []

                def opener(request, timeout):
                    del timeout
                    path = request.full_url.rsplit("/", 1)[-1]
                    payload = json.loads(request.data.decode("utf-8")) if request.data else None
                    calls.append((request.method, path, payload))
                    if path == "turn":
                        result = outcome()
                        if isinstance(result, BaseException):
                            raise result
                        return result
                    return _Response({"ok": True, "turn_id": payload["turn_id"]})

                adapter = self.adapter(opener)
                with self.assertRaises(JawlWebUnavailable):
                    adapter._post_native("submit-once", "turn-safe-1")
                self.assertTrue(adapter._post_native_cancel("turn-safe-1"))
                submits = [call for call in calls if call[1] == "turn"]
                cancels = [call for call in calls if call[1] == "cancel"]
                self.assertEqual(len(submits), 1)
                self.assertEqual(len(cancels), 1)
                self.assertEqual(submits[0][2]["turn_id"], "turn-safe-1")
                self.assertEqual(cancels[0][2], {"turn_id": "turn-safe-1"})

    def test_loopback_lost_ack_records_one_submit_and_scoped_cancel(self):
        records = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                records.append((self.path, payload))
                if self.path == "/api/companion/turn":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if self.path == "/api/companion/cancel":
                    body = json.dumps({"ok": True, "turn_id": payload["turn_id"]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server_thread.join, 1)
        self.addCleanup(server.shutdown)
        stream = _SseResponse()
        base_url = f"http://127.0.0.1:{server.server_port}"

        def opener(request, timeout):
            if request.full_url.endswith("/api/companion/stream"):
                return stream
            return urlopen(request, timeout=timeout)

        adapter = JawlWebChatAdapter(
            base_url, native_gateway=True, chat_timeout_seconds=2, opener=opener,
        )
        with self.assertRaises(JawlWebUnavailable):
            adapter.respond_envelope("actual lost ack", correlation_id="loopback-turn")
        submits = [payload for path, payload in records if path == "/api/companion/turn"]
        cancels = [payload for path, payload in records if path == "/api/companion/cancel"]
        self.assertEqual(len(submits), 1)
        self.assertEqual(len(cancels), 1)
        self.assertEqual(submits[0]["turn_id"], "loopback-turn")
        self.assertEqual(cancels[0], {"turn_id": "loopback-turn"})


if __name__ == "__main__":
    unittest.main()
