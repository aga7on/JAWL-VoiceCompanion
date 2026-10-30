"""One owned loopback HTTP operation: absolute deadline, scoped socket abort.

Default transport disables redirects/proxies and owns sockets before connect.
Injected openers keep their compatibility contract; opaque/non-cooperative
implementations cannot be forcibly reaped and must not be treated as such.
"""
from __future__ import annotations

import http.client
import socket
import time
from threading import Event, Lock, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen


class HttpCallCancelled(Exception):
    pass


class HttpCallDeadline(TimeoutError):
    pass


class _Scope:
    def __init__(self, timeout, cancel):
        self.deadline = time.monotonic() + timeout
        self.cancel = cancel
        self.done, self.lock = Event(), Lock()
        self.sock = None
        self.reason = None
        self.thread = None

    def check(self):
        if (self.cancel is not None and self.cancel.is_set()) or self.reason == "cancel":
            raise HttpCallCancelled("HTTP operation cancelled")
        if self.reason == "deadline" or time.monotonic() >= self.deadline:
            raise HttpCallDeadline("HTTP absolute deadline exceeded")

    @staticmethod
    def close_socket(sock):
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            # urllib closes the socket wrapper after headers, retaining its
            # fd via makefile. Real close interrupts that owned buffered read.
            sock._real_close()
        except (AttributeError, OSError):
            try:
                sock.close()
            except OSError:
                pass

    def bind(self, sock):
        with self.lock:
            self.sock = sock
            stopped = self.reason is not None
        if stopped:
            self.close_socket(sock)
        self.check()

    def abort(self, reason):
        with self.lock:
            if self.reason is None:
                self.reason = reason
            sock = self.sock
        self.close_socket(sock)

    def watch(self):
        while not self.done.wait(.025):
            if self.cancel is not None and self.cancel.is_set():
                self.abort("cancel")
                return
            if time.monotonic() >= self.deadline:
                self.abort("deadline")
                return

    def start(self):
        self.check()
        self.thread = Thread(target=self.watch, name="jawl-http-deadline", daemon=True)
        self.thread.start()

    def finish(self):
        self.done.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(.5)
            if self.thread.is_alive():
                raise URLError("HTTP watchdog did not exit")

    def connect(self, address, timeout=None, source_address=None):
        host, port = address
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise URLError("HTTP transport is loopback-only")
        # Numeric loopback targets avoid an uninterruptible resolver call.
        targets = [(socket.AF_INET6, "::1")] if host == "::1" else [(socket.AF_INET, "127.0.0.1")]
        if host == "localhost":
            targets.append((socket.AF_INET6, "::1"))
        last_error = None
        for family, target in targets:
            self.check()
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                self.bind(sock)
                sock.settimeout(max(.001, min(.25, self.deadline - time.monotonic())))
                if source_address is not None:
                    sock.bind(source_address)
                sock.connect((target, port))
                self.check()
                sock.settimeout(max(.001, self.deadline - time.monotonic()))
                return sock
            except BaseException as exc:
                sock.close()
                if not isinstance(exc, OSError):
                    raise
                last_error = exc
        self.check()
        raise last_error


def _owned_opener(scope):
    class Connection(http.client.HTTPConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = scope.connect

    class SecureConnection(http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = scope.connect

        def connect(self):
            http.client.HTTPConnection.connect(self)
            # Preserve the standard context/SNI/certificate checks, but own the
            # SSLSocket before the blocking handshake rather than afterwards.
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self._tunnel_host or self.host,
                                                  do_handshake_on_connect=False)
            scope.bind(self.sock)
            self.sock.do_handshake()
            scope.check()

    class Plain(HTTPHandler):
        def http_open(self, request):
            return self.do_open(Connection, request)

    class Secure(HTTPSHandler):
        def https_open(self, request):
            return self.do_open(SecureConnection, request, context=self._context)

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    return build_opener(ProxyHandler({}), Plain(), Secure(), NoRedirect()).open


def read_scoped(request: Request, *, opener=urlopen, cancel_event=None,
                timeout_seconds: float = 2, max_bytes: int = 128 * 1024) -> bytes:
    if not 0 < timeout_seconds <= 30 or not isinstance(max_bytes, int) or not 0 < max_bytes <= 128 * 1024:
        raise ValueError("invalid scoped HTTP bounds")
    parsed = urlsplit(request.full_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("scoped HTTP request must be loopback HTTP(S)")
    if parsed.username or parsed.password:
        raise ValueError("scoped HTTP URL cannot contain credentials")
    scope = _Scope(timeout_seconds, cancel_event)
    open_request = _owned_opener(scope) if opener is urlopen else opener
    try:
        scope.start()
        try:
            with open_request(request, timeout=timeout_seconds) as response:
                if opener is not urlopen:
                    try:
                        scope.bind(response.fp.raw._sock)
                    except AttributeError:
                        pass
                scope.check()
                raw = response.read(max_bytes + 1)
                scope.check()
                if not isinstance(raw, bytes):
                    raise URLError("HTTP response body must be bytes")
                return raw
        except Exception as exc:
            if isinstance(exc, HTTPError):
                exc.close()
            scope.check()
            if isinstance(exc, http.client.HTTPException):
                raise URLError("invalid HTTP response") from exc
            raise
    finally:
        scope.finish()
