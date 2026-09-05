import base64
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import ssl
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402


class LanSecurityTests(unittest.TestCase):
    token = "lan-token-for-tests-1234"

    def setUp(self):
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            lan_mode=True,
            lan_access_token=self.token,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        credentials = base64.b64encode(f"tablet:{self.token}".encode("utf-8")).decode("ascii")
        self.auth = {"Authorization": f"Basic {credentials}"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _get(self, path, headers=None):
        request = Request(self.base + path, headers=headers or {})
        return urlopen(request, timeout=2)

    def test_lan_requires_basic_auth_before_serving_ui_or_session(self):
        with self.assertRaises(HTTPError) as context:
            self._get("/api/session")
        error = context.exception
        try:
            self.assertEqual(error.code, 401)
            self.assertIn("Basic", error.headers["WWW-Authenticate"])
            self.assertNotIn(self.token, error.read().decode("utf-8"))
        finally:
            error.close()

        with self._get("/api/session", self.auth) as response:
            session = json.loads(response.read().decode("utf-8"))
            self.assertTrue(session["csrf_token"])
            self.assertNotIn("session_token", session)
            self.assertIn("HttpOnly", response.headers["Set-Cookie"])

    def test_malformed_and_non_ascii_basic_auth_fail_closed(self):
        for authorization in ("Basic not-base64", "Basic ", "Basic !!!"):
            with self.assertRaises(HTTPError) as context:
                self._get("/api/health", {"Authorization": authorization})
            self.assertEqual(context.exception.code, 401)
            context.exception.close()

        credentials = base64.b64encode("тест:неверный-пароль".encode("utf-8")).decode("ascii")
        with self.assertRaises(HTTPError) as context:
            self._get("/api/health", {"Authorization": f"Basic {credentials}"})
        self.assertEqual(context.exception.code, 401)
        context.exception.close()

    def test_basic_auth_does_not_bypass_session_csrf_or_origin_checks(self):
        with self.assertRaises(HTTPError) as context:
            self._get("/api/state", self.auth)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

        session_headers = {
            **self.auth,
            "X-Companion-Session": self.server.session_token,
            "X-Companion-CSRF": self.server.csrf_token,
            "Origin": f"http://evil.example:{self.server.server_port}",
        }
        with self.assertRaises(HTTPError) as context:
            self._get("/api/state", session_headers)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

        session_headers["Origin"] = self.base
        with self._get("/api/state", session_headers) as response:
            self.assertEqual(response.status, 200)

    def test_remote_bind_requires_explicit_lan_mode_auth_and_tls(self):
        with self.assertRaisesRegex(ValueError, "explicit LAN mode"):
            create_server(host="0.0.0.0", port=0, gateway=TextGateway())
        with self.assertRaisesRegex(ValueError, "access token"):
            create_server(host="0.0.0.0", port=0, gateway=TextGateway(), lan_mode=True)
        with self.assertRaisesRegex(ValueError, "TLS"):
            create_server(
                host="0.0.0.0",
                port=0,
                gateway=TextGateway(),
                lan_mode=True,
                lan_access_token=self.token,
            )

    def test_ephemeral_https_serves_ui_and_chat_with_exact_origin(self):
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID
        except ImportError:
            self.skipTest("cryptography is not installed in the development environment")

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
            now = datetime.now(timezone.utc)
            certificate = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now)
                .not_valid_after(now + timedelta(days=1))
                .add_extension(
                    x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                    critical=False,
                )
                .sign(key, hashes.SHA256())
            )
            cert_file = temp_path / "test.crt"
            key_file = temp_path / "test.key"
            cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_file.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )
            server = create_server(
                host="127.0.0.1",
                port=0,
                frontend_dir=Path(__file__).parents[1] / "frontend",
                gateway=TextGateway(),
                lan_mode=True,
                lan_access_token=self.token,
                tls_cert_file=cert_file,
                tls_key_file=key_file,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"https://127.0.0.1:{server.server_port}"
            credentials = base64.b64encode(f"tablet:{self.token}".encode("utf-8")).decode("ascii")
            auth = {"Authorization": f"Basic {credentials}"}
            context = ssl.create_default_context(cafile=str(cert_file))
            try:
                with urlopen(Request(base + "/", headers=auth), context=context, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b"JAWL VoiceCompanion", response.read())

                with urlopen(Request(base + "/api/session", headers=auth), context=context, timeout=2) as response:
                    session = json.loads(response.read().decode("utf-8"))
                    self.assertIn("Secure", response.headers["Set-Cookie"])

                session_headers = {
                    **auth,
                    "Content-Type": "application/json",
                    "X-Companion-Session": server.session_token,
                    "X-Companion-CSRF": session["csrf_token"],
                    "Origin": base,
                }
                request = Request(
                    base + "/api/chat",
                    data=json.dumps({"text": "hello"}).encode("utf-8"),
                    headers=session_headers,
                    method="POST",
                )
                with urlopen(request, context=context, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read().decode("utf-8"))["response_id"])

                invalid_origin = {**session_headers, "Origin": "https://evil.example:443"}
                request = Request(
                    base + "/api/chat",
                    data=b'{"text":"blocked"}',
                    headers=invalid_origin,
                    method="POST",
                )
                with self.assertRaises(HTTPError) as error_context:
                    urlopen(request, context=context, timeout=2)
                self.assertEqual(error_context.exception.code, 403)
                error_context.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
