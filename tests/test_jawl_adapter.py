import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_adapter import (  # noqa: E402
    JawlTerminalAdapter,
    JawlUnavailable,
)


class JawlAdapterTests(unittest.TestCase):
    def test_adapter_uses_jawl_handshake_and_json_lines(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        received = {}

        def serve_once():
            connection, _address = listener.accept()
            with connection:
                file = connection.makefile("rb")
                received["handshake"] = file.readline()
                received["payload"] = json.loads(file.readline().decode("utf-8"))
                connection.sendall(
                    json.dumps(
                        {"text": "\u041e\u0442\u0432\u0435\u0442 \u043d\u0430\u0441\u0442\u043e\u044f\u0449\u0435\u0433\u043e JAWL"},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    + b"\n"
                )

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                port_file = Path(directory) / "terminal.port"
                port_file.write_text(str(port), encoding="utf-8")
                answer = JawlTerminalAdapter(port_file, timeout=2).respond(
                    "\u041f\u0440\u0438\u0432\u0435\u0442, JAWL"
                )
        finally:
            listener.close()
            thread.join(timeout=2)

        self.assertEqual(received["handshake"], b"JAWL_HANDSHAKE\n")
        self.assertEqual(received["payload"], {"text": "\u041f\u0440\u0438\u0432\u0435\u0442, JAWL"})
        self.assertEqual(answer, "\u041e\u0442\u0432\u0435\u0442 \u043d\u0430\u0441\u0442\u043e\u044f\u0449\u0435\u0433\u043e JAWL")

    def test_no_broadcast_is_reported_as_degraded(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def serve_without_broadcast():
            connection, _address = listener.accept()
            with connection:
                connection.recv(4096)
                threading.Event().wait(0.25)

        thread = threading.Thread(target=serve_without_broadcast, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                port_file = Path(directory) / "terminal.port"
                port_file.write_text(str(port), encoding="utf-8")
                adapter = JawlTerminalAdapter(port_file, timeout=0.1)
                with self.assertRaises(ConnectionError):
                    adapter.respond("\u0422\u0435\u0441\u0442 \u0431\u0435\u0437 broadcast")
                self.assertEqual(adapter.last_status, "no_broadcast")
        finally:
            listener.close()
            thread.join(timeout=2)

    def test_internal_markup_is_not_returned_as_user_text(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def serve_once():
            connection, _address = listener.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(
                    json.dumps(
                        {
                            "text": (
                                "<think>\u0441\u0435\u043a\u0440\u0435\u0442\u043d\u043e\u0435 \u0440\u0430\u0441\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u0435</think>"
                                "<final>\u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u044b\u0439 \u043e\u0442\u0432\u0435\u0442.</final>"
                            )
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    + b"\n"
                )

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                port_file = Path(directory) / "terminal.port"
                port_file.write_text(str(port), encoding="utf-8")
                self.assertEqual(
                    JawlTerminalAdapter(port_file, timeout=2).respond("\u0422\u0435\u0441\u0442"),
                    "\u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u044b\u0439 \u043e\u0442\u0432\u0435\u0442.",
                )
        finally:
            listener.close()
            thread.join(timeout=2)

    def test_unclosed_internal_markup_degrades_without_leaking_text(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def serve_once():
            connection, _address = listener.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(
                    json.dumps(
                        {"text": "<think>\u0441\u0435\u043a\u0440\u0435\u0442\u043d\u043e\u0435 \u0440\u0430\u0441\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u0435"},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    + b"\n"
                )

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                port_file = Path(directory) / "terminal.port"
                port_file.write_text(str(port), encoding="utf-8")
                adapter = JawlTerminalAdapter(port_file, timeout=2)
                with self.assertRaises(JawlUnavailable):
                    adapter.respond("\u0422\u0435\u0441\u0442")
                self.assertEqual(adapter.last_status, "invalid_response")
        finally:
            listener.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
