import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.jawl_adapter import JawlTerminalAdapter  # noqa: E402


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
                connection.sendall(json.dumps({"text": "Ответ настоящего JAWL"}).encode("utf-8") + b"\n")

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                port_file = Path(directory) / "terminal.port"
                port_file.write_text(str(port), encoding="utf-8")
                answer = JawlTerminalAdapter(port_file, timeout=2).respond("Привет, JAWL")
        finally:
            listener.close()
            thread.join(timeout=2)

        self.assertEqual(received["handshake"], b"JAWL_HANDSHAKE\n")
        self.assertEqual(received["payload"], {"text": "Привет, JAWL"})
        self.assertEqual(answer, "Ответ настоящего JAWL")

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
                    adapter.respond("Тест без broadcast")
                self.assertEqual(adapter.last_status, "no_broadcast")
        finally:
            listener.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
