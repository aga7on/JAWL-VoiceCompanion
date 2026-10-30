"""Deterministic loopback coverage for the owned HTTP request lifecycle."""

import socket
import ssl
import ipaddress
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from urllib.error import HTTPError
from urllib.request import Request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jawl_voicecompanion.http_lifecycle import (  # noqa: E402
    HttpCallCancelled,
    HttpCallDeadline,
    read_scoped,
)


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, handler):
        self.seen = []
        self.seen_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), handler)


class _TlsLoopbackServer(_LoopbackServer):
    def __init__(self, handler, context):
        self.tls_context = context
        super().__init__(handler)

    def process_request_thread(self, request, client_address):
        try:
            request = self.tls_context.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError):
            request.close()
            return
        super().process_request_thread(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    @property
    def owner(self):
        return self.server

    def _record(self):
        with self.owner.seen_lock:
            self.owner.seen.append((self.command, self.path, self.headers.get("X-Console-Token")))

    def _reply(self, status=200, body=b"ok", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def do_GET(self):
        self._record()
        if self.path == "/wait-for-close":
            self.owner.request_seen.set()
            self.connection.settimeout(1.5)
            try:
                if self.connection.recv(1) == b"":
                    self.owner.peer_eof.set()
            except (socket.timeout, OSError):
                pass
            return
        if self.path == "/headers-trickle":
            try:
                for part in (b"HTTP/1.1 200 OK\r\n", b"Content-Length: 2\r\n", b"\r\n", b"o", b"k"):
                    self.connection.sendall(part)
                    time.sleep(0.07)
            except OSError:
                pass
            return
        if self.path == "/body-trickle":
            try:
                self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n")
                for byte in b"12345678":
                    self.connection.sendall(bytes((byte,)))
                    time.sleep(0.07)
            except OSError:
                pass
            return
        if self.path == "/large":
            self._reply(body=b"0123456789abcdef")
            return
        if self.path == "/redirect":
            self._reply(307, b"redirect", (("Location", self.owner.redirect_to),))
            return
        if self.path == "/error":
            self._reply(503, b"unavailable")
            return
        if self.path == "/wait-A":
            self.owner.a_started.set()
            self.owner.release_a.wait(1.5)
        self._reply(body=b"done")

    def do_POST(self):
        self._record()
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/post-redirect":
            self._reply(307, b"redirect", (("Location", self.owner.redirect_to),))
            return
        self._reply(body=b"accepted")


class HttpLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cert_temp = tempfile.TemporaryDirectory(prefix="jawl-http-test-")
        cert_dir = Path(cls._cert_temp.name)
        cls.ca_path = cert_dir / "test-ca.pem"
        cls.server_cert_path = cert_dir / "server.pem"
        cls.server_key_path = cert_dir / "server-key.pem"

        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "JAWL ephemeral test CA")])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=None,
                    decipher_only=None,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        leaf_cert = (
            x509.CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(ca_name)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        cls.ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        cls.server_cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
        cls.server_key_path.write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )

    @classmethod
    def tearDownClass(cls):
        cls._cert_temp.cleanup()

    def _start_server(self, server):
        server.request_seen = threading.Event()
        server.peer_eof = threading.Event()
        server.a_started = threading.Event()
        server.release_a = threading.Event()
        server.redirect_to = "http://127.0.0.1/unused"
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        thread.start()

        def cleanup():
            server.release_a.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive(), "loopback server thread leaked")

        self.addCleanup(cleanup)
        return server

    def _server(self):
        return self._start_server(_LoopbackServer(_Handler))

    def _tls_server(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.server_cert_path, self.server_key_path)
        return self._start_server(_TlsLoopbackServer(_Handler, context))

    @staticmethod
    def _request(server, path, *, method="GET", body=None, token=None):
        headers = {"X-Console-Token": token} if token is not None else {}
        return Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=body,
            headers=headers,
            method=method,
        )

    @staticmethod
    def _call_in_thread(result_queue, *args, **kwargs):
        try:
            result_queue.put(("result", read_scoped(*args, **kwargs)))
        except BaseException as exc:  # captured for assertions in the test thread
            result_queue.put(("error", exc))

    def _assert_no_deadline_threads(self):
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
            leaked = [t for t in threading.enumerate() if t.name == "jawl-http-deadline"]
            if not leaked:
                return
            time.sleep(0.01)
        self.assertEqual([], leaked, "HTTP deadline watchdog thread leaked")

    def test_pre_cancelled_request_never_reaches_server(self):
        server = self._server()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(HttpCallCancelled):
            read_scoped(self._request(server, "/never"), cancel_event=cancelled)
        self.assertEqual(server.seen, [])

    def test_cancel_before_headers_closes_peer_socket(self):
        server = self._server()
        cancelled = threading.Event()
        results = Queue()
        worker = threading.Thread(
            target=self._call_in_thread,
            args=(results, self._request(server, "/wait-for-close")),
            kwargs={"cancel_event": cancelled, "timeout_seconds": 1.2},
            daemon=True,
        )
        worker.start()
        self.assertTrue(server.request_seen.wait(1), "request did not reach loopback peer")
        cancelled.set()
        worker.join(1.2)
        self.assertFalse(worker.is_alive(), "cancelled HTTP call did not return")
        kind, value = results.get(timeout=0.2)
        self.assertEqual(kind, "error")
        self.assertIsInstance(value, HttpCallCancelled)
        self.assertTrue(server.peer_eof.wait(1), "peer did not observe cancellation as EOF")
        self._assert_no_deadline_threads()

    def test_trickling_headers_cannot_extend_absolute_deadline(self):
        server = self._server()
        started = time.monotonic()
        with self.assertRaises(HttpCallDeadline):
            read_scoped(self._request(server, "/headers-trickle"), timeout_seconds=0.28)
        self.assertLess(time.monotonic() - started, 1.3)
        self._assert_no_deadline_threads()

    def test_trickling_body_cannot_extend_absolute_deadline(self):
        server = self._server()
        started = time.monotonic()
        with self.assertRaises(HttpCallDeadline):
            read_scoped(self._request(server, "/body-trickle"), timeout_seconds=0.30)
        self.assertLess(time.monotonic() - started, 1.3)
        self._assert_no_deadline_threads()

    def test_post_is_sent_once_and_redirect_is_not_followed_or_forwarded(self):
        destination = self._server()
        origin = self._server()
        origin.redirect_to = f"http://127.0.0.1:{destination.server_port}/capture"
        with self.assertRaises(HTTPError) as caught:
            read_scoped(
                self._request(origin, "/post-redirect", method="POST", body=b"payload", token="fixture-secret"),
                timeout_seconds=1,
            )
        self.assertEqual(caught.exception.code, 307)
        self.assertTrue(caught.exception.fp.closed, "redirect response body was not closed")
        caught.exception.close()
        self.assertEqual(len(origin.seen), 1)
        self.assertEqual(origin.seen[0][:2], ("POST", "/post-redirect"))
        self.assertEqual(origin.seen[0][2], "fixture-secret")
        self.assertEqual(destination.seen, [])
        self._assert_no_deadline_threads()

    def test_cancelling_one_call_does_not_cancel_another_or_its_followup(self):
        server = self._server()
        cancel_a = threading.Event()
        a_results = Queue()
        a = threading.Thread(
            target=self._call_in_thread,
            args=(a_results, self._request(server, "/wait-A")),
            kwargs={"cancel_event": cancel_a, "timeout_seconds": 1.2},
            daemon=True,
        )
        a.start()
        self.assertTrue(server.a_started.wait(1))
        self.assertEqual(read_scoped(self._request(server, "/quick"), timeout_seconds=1), b"done")
        cancel_a.set()
        a.join(1.2)
        self.assertFalse(a.is_alive())
        kind, value = a_results.get(timeout=0.2)
        self.assertEqual(kind, "error")
        self.assertIsInstance(value, HttpCallCancelled)
        self.assertEqual(read_scoped(self._request(server, "/follow-up"), timeout_seconds=1), b"done")
        self.assertIn(("GET", "/quick", None), server.seen)
        self.assertIn(("GET", "/follow-up", None), server.seen)
        self._assert_no_deadline_threads()

    def test_read_is_bounded_to_max_bytes_plus_one(self):
        server = self._server()
        result = read_scoped(self._request(server, "/large"), max_bytes=7, timeout_seconds=1)
        self.assertEqual(result, b"01234567")
        self.assertLessEqual(len(result), 8)

    def test_http_error_propagates_and_deadline_thread_is_cleaned_up(self):
        server = self._server()
        with self.assertRaises(HTTPError) as caught:
            read_scoped(self._request(server, "/error"), timeout_seconds=1)
        self.assertEqual(caught.exception.code, 503)
        self.assertTrue(caught.exception.fp.closed, "HTTP error response body was not closed")
        caught.exception.close()
        self._assert_no_deadline_threads()

    def test_custom_cooperative_opener_receives_timeout_and_bounded_read(self):
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()
                return False

            def read(self, limit):
                calls.append(("read", limit))
                return b"x" * limit

            def close(self):
                calls.append(("close",))

        def opener(request, timeout):
            calls.append(("open", request.full_url, timeout))
            return Response()

        request = Request("http://127.0.0.1/custom")
        result = read_scoped(request, opener=opener, timeout_seconds=0.8, max_bytes=11)
        self.assertEqual(result, b"x" * 12)
        self.assertEqual(calls[0], ("open", request.full_url, 0.8))
        self.assertEqual(calls[1], ("read", 12))
        self.assertEqual(calls[2], ("close",))

    def test_normal_response_cleanup_leaves_no_deadline_thread(self):
        server = self._server()
        self.assertEqual(read_scoped(self._request(server, "/ok"), timeout_seconds=1), b"done")
        self._assert_no_deadline_threads()

    def test_https_rejects_ephemeral_untrusted_server_certificate(self):
        from urllib.error import URLError

        server = self._tls_server()
        request = Request(f"https://127.0.0.1:{server.server_port}/ok")
        with self.assertRaises(URLError):
            read_scoped(request, timeout_seconds=1)
        self._assert_no_deadline_threads()

    def test_https_succeeds_when_only_this_test_trusts_its_ephemeral_ca(self):
        from unittest.mock import patch

        server = self._tls_server()
        request = Request(f"https://127.0.0.1:{server.server_port}/ok")
        trusted_context = ssl.create_default_context(cafile=str(self.ca_path))
        with patch("ssl._create_default_https_context", return_value=trusted_context):
            result = read_scoped(request, timeout_seconds=1)
        self.assertEqual(result, b"done")
        self.assertEqual(server.seen[0][:2], ("GET", "/ok"))
        self._assert_no_deadline_threads()

    def test_stalled_tls_handshake_is_cancelled_and_peer_sees_close(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)
        peer_done = threading.Event()
        handshake_started = threading.Event()
        cancel = threading.Event()

        def stalled_peer():
            connection, _address = listener.accept()
            with connection:
                connection.settimeout(1.5)
                try:
                    if connection.recv(1):
                        handshake_started.set()
                        cancel.set()
                        while connection.recv(4096):
                            pass
                except (OSError, socket.timeout):
                    pass
                finally:
                    peer_done.set()

        peer = threading.Thread(target=stalled_peer, daemon=True)
        peer.start()
        self.addCleanup(listener.close)
        self.addCleanup(lambda: peer.join(timeout=2))
        results = Queue()
        request = Request(f"https://127.0.0.1:{listener.getsockname()[1]}/handshake")
        worker = threading.Thread(
            target=self._call_in_thread,
            args=(results, request),
            kwargs={"cancel_event": cancel, "timeout_seconds": 1.5},
            daemon=True,
        )
        worker.start()
        self.assertTrue(handshake_started.wait(1), "TLS client did not start handshake")
        worker.join(1.2)
        self.assertFalse(worker.is_alive(), "cancelled TLS handshake did not return")
        kind, value = results.get(timeout=0.2)
        self.assertEqual(kind, "error")
        self.assertIsInstance(value, HttpCallCancelled)
        self.assertTrue(peer_done.wait(1), "stalled TLS peer did not observe socket closure")
        self._assert_no_deadline_threads()


if __name__ == "__main__":
    unittest.main()
