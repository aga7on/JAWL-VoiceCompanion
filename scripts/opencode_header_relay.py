"""Disposable loopback relay for providers with client-specific routing.

This is a test harness, not a second model or a production gateway. It
forwards the OpenAI-compatible path to one HTTPS upstream, replaces the
authorization header from an environment variable, and adds a bounded
provider User-Agent. It binds to loopback only.
"""

from __future__ import annotations

import argparse
from http.client import HTTPConnection, HTTPSConnection
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
from urllib.parse import urlsplit


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_MAX_BODY = 8 * 1024 * 1024


def _parse_upstream(value: str) -> tuple[str, str, int | None, str]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--upstream must be an http(s) URL")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("--upstream must not contain credentials, query or fragment")
    return parsed.scheme, parsed.hostname, parsed.port, parsed.path.rstrip("/")


class _RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VoiceCompanionRelay/1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._forward()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._forward()

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _forward(self) -> None:
        config = self.server.relay_config  # type: ignore[attr-defined]
        length = self.headers.get("Content-Length")
        try:
            body_length = int(length) if length is not None else 0
        except ValueError:
            self.send_error(400, "invalid Content-Length")
            return
        if body_length < 0 or body_length > _MAX_BODY:
            self.send_error(413, "request body is too large")
            return
        body = self.rfile.read(body_length) if body_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.casefold() not in _HOP_BY_HOP
            and key.casefold() not in {"host", "authorization", "content-length"}
        }
        headers.update(
            {
                "Host": config["host"],
                "Authorization": f"Bearer {config['key']}",
                "User-Agent": config["user_agent"],
                "Accept-Encoding": "identity",
            }
        )
        connection_type, host, port, prefix = config["upstream"]
        connection_class = HTTPSConnection if connection_type == "https" else HTTPConnection
        connection = connection_class(
            host,
            port=port,
            timeout=config["timeout"],
            context=ssl.create_default_context() if connection_type == "https" else None,
        ) if connection_type == "https" else connection_class(host, port=port, timeout=config["timeout"])
        try:
            connection.request(self.command, prefix + self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.casefold() not in _HOP_BY_HOP:
                    self.send_header(key, value)
            self.end_headers()
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ConnectionError, OSError, TimeoutError) as exc:
            if not self.wfile.closed:
                try:
                    self.send_error(502, f"upstream unavailable: {type(exc).__name__}")
                except (BrokenPipeError, ConnectionResetError):
                    pass
        finally:
            connection.close()

    def log_message(self, format: str, *args: object) -> None:
        print("[relay] " + format % args, flush=True)


class _RelayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8891)
    parser.add_argument("--upstream", default="https://opencode.ai/zen")
    parser.add_argument("--key-env", default="OPENCODE_RELAY_KEY")
    parser.add_argument("--user-agent", default="OpenCode/1.18.11")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 1 <= len(args.user_agent) <= 200 or any(c in args.user_agent for c in "\r\n"):
        parser.error("--user-agent must be a bounded single line")
    key = os.environ.get(args.key_env, "").strip()
    if not key:
        parser.error(f"missing credential in ${args.key_env}")
    upstream = _parse_upstream(args.upstream)
    server = _RelayServer(("127.0.0.1", args.port), _RelayHandler)
    server.relay_config = {
        "upstream": upstream,
        "host": upstream[1],
        "key": key,
        "user_agent": args.user_agent,
        "timeout": max(1.0, min(args.timeout, 600.0)),
    }
    print(f"OpenCode relay listening on http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
