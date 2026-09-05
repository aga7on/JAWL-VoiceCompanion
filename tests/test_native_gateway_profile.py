import importlib.util
import json
from pathlib import Path
import queue
import sys
import threading
import unittest
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_native_gateway_profile", ROOT / "scripts" / "run_native_gateway_profile.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NativeGatewayProfileUnitTests(unittest.TestCase):
    def test_cursor_contract_is_strict_and_rejects_gap_type(self):
        cursor = {
            "schema_version": 1,
            "after": 4,
            "oldest_event_seq": 1,
            "latest_event_seq": 8,
            "gap": False,
        }
        self.assertEqual(MODULE._validate_cursor(cursor), cursor)
        broken = dict(cursor, gap="false")
        with self.assertRaises(MODULE.ProfileFailure):
            MODULE._validate_cursor(broken)

    def test_url_guard_rejects_remote_host_by_default(self):
        with self.assertRaises(ValueError):
            MODULE._loopback_url("http://example.com:8765")
        with self.assertRaises(ValueError):
            MODULE._loopback_url("http://127.0.0.1:8765/?token=leak")

    def test_report_requires_requested_turns_and_reconnect(self):
        report = MODULE.ProfileReport("http://127.0.0.1:8765", 2, True, True)
        report.completed_turns = 2
        report.cancellation_observed = True
        report.reconnect_resumed = True
        self.assertTrue(report.as_dict()["pass"])
        report.sequence_gaps.append({"expected": 3, "actual": 4})
        self.assertFalse(report.as_dict()["pass"])

    def test_sse_read_timeout_is_reported_after_connection(self):
        class TimeoutResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def readline(self):
                raise TimeoutError("idle read")

            def close(self):
                return None

        original_urlopen = MODULE.urlopen
        MODULE.urlopen = lambda _request, timeout: TimeoutResponse()
        try:
            reader = MODULE.SseBatchReader(
                "http://127.0.0.1:8765/api/companion/stream",
                {"Accept": "text/event-stream"},
                0.1,
            )
            reader.start()
            self.assertTrue(reader.done.wait(1))
            self.assertIsNotNone(reader.error)
            self.assertIn("read timed out after connection establishment", str(reader.error))
        finally:
            reader.stop()
            MODULE.urlopen = original_urlopen

    def test_profile_runs_against_a_controlled_sse_transport(self):
        class FakeResponse:
            def __init__(self, server, after):
                self.server = server
                self.after = after
                self.lines = queue.Queue()
                self.closed = threading.Event()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()
                return False

            def readline(self):
                while not self.closed.is_set():
                    try:
                        return self.lines.get(timeout=0.05)
                    except queue.Empty:
                        continue
                return b""

            def read(self, _limit):
                return self.body

            def close(self):
                if not self.closed.is_set():
                    self.closed.set()
                    self.server.streams.discard(self)

        class FakeGateway:
            def __init__(self):
                self.lock = threading.Lock()
                self.history = []
                self.streams = set()
                self.next_seq = 1

            def response(self, payload):
                result = FakeResponse(self, 0)
                result.body = json.dumps(payload).encode("utf-8")
                return result

            def packet(self, after):
                events = [event for event in self.history if event["event_seq"] > after]
                next_after = events[-1]["event_seq"] if events else after
                return {
                    "events": events,
                    "cursor": {
                        "schema_version": 1,
                        "after": next_after,
                        "oldest_event_seq": self.history[0]["event_seq"] if self.history else self.next_seq,
                        "latest_event_seq": self.history[-1]["event_seq"] if self.history else 0,
                        "gap": False,
                    },
                }

            def push(self, stream):
                packet = self.packet(stream.after)
                events = packet["events"]
                if events:
                    stream.after = events[-1]["event_seq"]
                raw = ("data: " + json.dumps(packet) + "\n\n").encode("utf-8")
                stream.lines.put(raw.splitlines(keepends=True)[0])
                stream.lines.put(b"\n")

            def emit(self, turn_id, event_type, payload):
                with self.lock:
                    event = {
                        "schema_version": 1,
                        "event_seq": self.next_seq,
                        "turn_id": turn_id,
                        "type": event_type,
                        "payload": payload,
                    }
                    self.next_seq += 1
                    self.history.append(event)
                    streams = list(self.streams)
                for stream in streams:
                    self.push(stream)

            def urlopen(self, request, timeout):
                del timeout
                parsed = urlsplit(request.full_url)
                if request.data is None:
                    after = int(parse_qs(parsed.query).get("after", ["0"])[0])
                    stream = FakeResponse(self, after)
                    with self.lock:
                        self.streams.add(stream)
                    self.push(stream)
                    return stream
                payload = json.loads(request.data.decode("utf-8"))
                if parsed.path.endswith("/turn"):
                    turn_id = payload["turn_id"]
                    self.emit(turn_id, "turn.started", {"source": "fake", "mode": "react"})
                    if "Cancellation probe" not in payload["text"]:
                        identity = {
                            "action_id": "action-1",
                            "tool": "fake_tool",
                            "status": "requested",
                        }
                        self.emit(turn_id, "tool.requested", identity)
                        self.emit(turn_id, "tool.started", dict(identity, status="started"))
                        self.emit(
                            turn_id,
                            "tool.completed",
                            dict(identity, status="completed", summary="fake"),
                        )
                        self.emit(turn_id, "assistant.final", {"response": {
                            "schema_version": 1,
                            "response_id": "resp-" + turn_id,
                            "turn_id": turn_id,
                            "text": "OK",
                            "speak": True,
                            "emotion": {"id": "attentive", "intensity": 0.4, "confidence": 0.8},
                            "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
                            "voice": {"provider": "fake", "voice_id": "ru", "rate": 1.0},
                            "actions": [],
                            "interruptible": True,
                            "proactive": False,
                        }})
                    return self.response({"ok": True, "turn_id": turn_id})
                if parsed.path.endswith("/cancel"):
                    self.emit(payload["turn_id"], "turn.cancelled", {"reason": "fake cancellation"})
                    return self.response({"ok": True, "turn_id": payload["turn_id"]})
                raise AssertionError(parsed.path)

        fake = FakeGateway()
        original_urlopen = MODULE.urlopen
        MODULE.urlopen = fake.urlopen
        try:
            args = MODULE._parser().parse_args(["--turns", "3", "--timeout", "1", "--turn-timeout", "1"])
            args.token = ""
            report = MODULE.NativeGatewayProfile(args).run()
        finally:
            MODULE.urlopen = original_urlopen
        self.assertTrue(report["pass"], report)
        self.assertTrue(report["reconnect_resumed"])
        self.assertTrue(report["cancellation_observed"])
        self.assertEqual(report["completed_turns"], 3)
        self.assertEqual(report["duplicate_events"], 0)


if __name__ == "__main__":
    unittest.main()
