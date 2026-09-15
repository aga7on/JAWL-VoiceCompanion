import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_adapter import JawlTurnCancelled  # noqa: E402
from jawl_voicecompanion.jawl_terminal import JawlTerminalGateway  # noqa: E402


def _envelope(turn_id: str, text: str) -> dict:
    return {
        "schema_version": 1,
        "response_id": f"resp-{turn_id}",
        "turn_id": turn_id,
        "text": text,
        "speak": True,
        "emotion": {"id": "attentive", "intensity": 0.45, "confidence": 0.8},
        "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
        "voice": {"provider": "jawl", "voice_id": "main_ru", "rate": 1.0},
        "actions": [],
        "interruptible": True,
        "proactive": False,
    }


class FakeTerminal:
    """Scripted JAWL terminal server recording handshakes and client lines."""

    def __init__(self, on_message=None, on_connect=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.handshakes = []
        self.lines = []
        self.turn_id = ""
        self.on_message = on_message
        self.on_connect = on_connect
        self._conns = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        for connection in self._conns:
            try:
                connection.close()
            except OSError:
                pass

    def send_event(self, connection, event_type, payload, seq):
        event = {
            "schema_version": 1,
            "event_seq": seq,
            "turn_id": self.turn_id,
            "type": event_type,
            "payload": payload,
        }
        connection.sendall((json.dumps({"gateway_event": event}, ensure_ascii=False) + "\n").encode("utf-8"))

    def send_raw(self, connection, payload):
        connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    def _serve(self):
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                connection, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._conns.append(connection)
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection):
        connection.settimeout(0.2)
        buffer = bytearray()
        handshake_done = False
        while not self._stop.is_set():
            try:
                chunk = connection.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buffer.extend(chunk)
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                text = raw.decode("utf-8", "replace").strip()
                if not text:
                    continue
                if not handshake_done:
                    handshake_done = True
                    self.handshakes.append(text)
                    if self.on_connect:
                        self.on_connect(self, connection, text)
                    continue
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = {"text": text}
                self.lines.append(parsed)
                if self.on_message:
                    self.on_message(self, connection, parsed)


class JawlTerminalGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _port_file(self, port):
        path = Path(self.tmp.name) / "terminal.port"
        path.write_text(str(port), encoding="utf-8")
        return path

    def test_roundtrip_streams_delta_and_final(self):
        def on_message(server, connection, parsed):
            server.turn_id = str(parsed.get("turn_id") or "")
            server.send_raw(connection, {"text": "legacy broadcast"})
            server.send_event(connection, "turn.started", {}, 1)
            server.send_event(connection, "assistant.delta", {"text": "Привет, "}, 2)
            server.send_event(
                connection, "assistant.final",
                {"response": _envelope(server.turn_id, "Привет, мир")}, 3,
            )

        server = FakeTerminal(on_message=on_message).start()
        self.addCleanup(server.stop)
        gateway = JawlTerminalGateway(self._port_file(server.port), timeout_seconds=5)
        self.addCleanup(gateway.close)
        events = list(gateway.stream_envelope("тест", correlation_id="turn-round1"))
        self.assertEqual([event["type"] for event in events], ["delta", "final"])
        self.assertEqual(events[0]["text"], "Привет, ")
        self.assertEqual(events[1]["response"]["text"], "Привет, мир")
        self.assertEqual(server.handshakes[0], "JAWL_GATEWAY 0")
        self.assertEqual(gateway.chat_status(), "connected")

    def test_cancel_sends_control_line(self):
        def on_message(server, connection, parsed):
            server.turn_id = str(parsed.get("turn_id") or "")
            server.send_event(connection, "assistant.delta", {"text": "частично"}, 1)

        server = FakeTerminal(on_message=on_message).start()
        self.addCleanup(server.stop)
        gateway = JawlTerminalGateway(self._port_file(server.port), timeout_seconds=5)
        self.addCleanup(gateway.close)
        cancel_event = threading.Event()
        outcome = []

        def consume():
            try:
                for event in gateway.stream_envelope("тест", cancel_event=cancel_event, correlation_id="turn-cancel1"):
                    outcome.append(event["type"])
                    cancel_event.set()
            except JawlTurnCancelled:
                outcome.append("cancelled")

        worker = threading.Thread(target=consume)
        worker.start()
        worker.join(timeout=6)
        self.assertIn("cancelled", outcome)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(line.get("type") == "cancel" for line in server.lines):
                break
            time.sleep(0.05)
        cancels = [line for line in server.lines if line.get("type") == "cancel"]
        self.assertTrue(cancels)
        self.assertEqual(cancels[0]["turn_id"], "turn-cancel1")

    def test_reconnect_replays_from_cursor(self):
        state = {"dropped": False}

        def on_message(server, connection, parsed):
            server.turn_id = str(parsed.get("turn_id") or "")
            server.send_event(connection, "assistant.delta", {"text": "часть "}, 1)
            connection.close()

        def on_connect(server, connection, handshake):
            if handshake == "JAWL_GATEWAY 1":
                server.send_event(
                    connection, "assistant.final",
                    {"response": _envelope(server.turn_id, "часть собрана")}, 2,
                )

        server = FakeTerminal(on_message=on_message, on_connect=on_connect).start()
        self.addCleanup(server.stop)
        gateway = JawlTerminalGateway(self._port_file(server.port), timeout_seconds=6)
        self.addCleanup(gateway.close)
        events = list(gateway.stream_envelope("тест", correlation_id="turn-replay1"))
        self.assertEqual([event["type"] for event in events], ["delta", "final"])
        self.assertEqual(events[1]["response"]["text"], "часть собрана")
        self.assertIn("JAWL_GATEWAY 1", server.handshakes)

    def test_circuit_breaker_after_repeated_failures(self):
        def on_message(server, connection, parsed):
            server.turn_id = str(parsed.get("turn_id") or "")
            server.send_event(connection, "turn.error", {"reason": "boom"}, 1)

        server = FakeTerminal(on_message=on_message).start()
        self.addCleanup(server.stop)
        gateway = JawlTerminalGateway(self._port_file(server.port), timeout_seconds=4)
        self.addCleanup(gateway.close)
        for index in range(4):
            with self.assertRaises(ConnectionError):
                list(gateway.stream_envelope("тест", correlation_id=f"turn-break{index}"))
        lines_before = len(server.lines)
        with self.assertRaises(ConnectionError):
            list(gateway.stream_envelope("тест", correlation_id="turn-break-last"))
        self.assertEqual(len(server.lines), lines_before)

    def test_turn_error_event_raises(self):
        def on_message(server, connection, parsed):
            server.turn_id = str(parsed.get("turn_id") or "")
            server.send_event(connection, "turn.error", {"reason": "boom"}, 1)

        server = FakeTerminal(on_message=on_message).start()
        self.addCleanup(server.stop)
        gateway = JawlTerminalGateway(self._port_file(server.port), timeout_seconds=5)
        self.addCleanup(gateway.close)
        with self.assertRaises(ConnectionError):
            list(gateway.stream_envelope("тест", correlation_id="turn-error1"))


class JawlTerminalGatewayBoundsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _dispatch(self, gateway, event):
        gateway._dispatch_line(
            json.dumps({"gateway_event": event}, ensure_ascii=False).encode("utf-8")
        )

    def _event(self, seq, turn_id, event_type="assistant.delta", payload=None):
        return {
            "schema_version": 1,
            "event_seq": seq,
            "turn_id": turn_id,
            "type": event_type,
            "payload": payload if payload is not None else {"text": "x"},
        }

    def test_completed_turn_ignores_late_replay(self):
        gateway = JawlTerminalGateway(Path(self.tmp.name) / "terminal.port", timeout_seconds=5)
        self.addCleanup(gateway.close)
        gateway._finish_turn("turn-done1")
        self._dispatch(gateway, self._event(10, "turn-done1"))
        self.assertNotIn("turn-done1", gateway._pending)

    def test_pending_turns_are_bounded(self):
        gateway = JawlTerminalGateway(Path(self.tmp.name) / "terminal.port", timeout_seconds=5)
        self.addCleanup(gateway.close)
        for index in range(40):
            self._dispatch(gateway, self._event(index + 1, f"turn-{index}"))
        self.assertLessEqual(len(gateway._pending), 16)

    def test_stale_cursor_resets_when_journal_is_behind(self):
        port_file = Path(self.tmp.name) / "terminal.port"
        port_file.write_text("9", encoding="utf-8")
        (Path(self.tmp.name) / "gateway_events.json").write_text(
            json.dumps(
                {"schema_version": 1, "events": [self._event(3, "turn-a")]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        gateway = JawlTerminalGateway(port_file, timeout_seconds=5)
        self.addCleanup(gateway.close)
        gateway._last_seq = 50
        gateway._sync_cursor_with_replay_file()
        self.assertEqual(gateway._last_seq, 0)
        gateway._last_seq = 2
        gateway._sync_cursor_with_replay_file()
        self.assertEqual(gateway._last_seq, 2)

    def test_oversized_unterminated_line_reconnects(self):
        from jawl_voicecompanion import jawl_terminal as jt

        left, right = socket.socketpair()
        self.addCleanup(right.close)
        gateway = JawlTerminalGateway(Path(self.tmp.name) / "terminal.port", timeout_seconds=5)
        self.addCleanup(gateway.close)
        gateway._socket = left
        gateway._running = True
        left.settimeout(0.5)
        payload = b"x" * (jt._MAX_LINE_BYTES + 1024)

        def feed():
            try:
                right.sendall(payload)
            except OSError:
                pass

        threading.Thread(target=feed, daemon=True).start()
        with self.assertRaises(jt.JawlUnavailable):
            gateway._read_loop()
        gateway._socket = None


if __name__ == "__main__":
    unittest.main()
