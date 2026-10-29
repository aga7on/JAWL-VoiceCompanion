"""Loopback contract tests for the process-local native JAWL HTTP admission sidecar."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime/jawl-sources/jawl-20260906-daily-v2"))


class FakeBridge:
    def __init__(self, *, connected: bool = True):
        self.connected = connected
        self.references = 0
        self.acquires = 0
        self.releases = 0
        self.wait_calls = 0
        self.send_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.changed = asyncio.Event()
        self.waiting = asyncio.Event()
        self.send_started = asyncio.Event()
        self.send_gate: asyncio.Event | None = None

    async def acquire(self):
        self.references += 1
        self.acquires += 1
        return self

    async def release(self):
        self.references -= 1
        self.releases += 1

    async def wait_for_change(self, timeout):
        self.wait_calls += 1
        self.waiting.set()
        try:
            await asyncio.wait_for(self.changed.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        self.changed.clear()

    async def send(self, text, turn_id):
        # This append intentionally occurs before the first await, matching the
        # native bridge's point of no return for admission/cancellation races.
        self.send_calls.append((text, turn_id))
        self.send_started.set()
        if self.send_gate is not None:
            await self.send_gate.wait()
        return {"ok": True, "turn_id": turn_id}

    async def cancel(self, turn_id, reason):
        self.cancel_calls.append((turn_id, reason))
        if not self.connected:
            return {"ok": False, "offline": True}
        return {"ok": True, "turn_id": turn_id}

    def set_connected(self, value: bool = True):
        self.connected = value
        self.changed.set()


class NativeJawlAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from src.web.admission import install_native_admission

        self.install_native_admission = install_native_admission
        self.bridge = FakeBridge()
        self.auth_calls = 0
        self.app = self._make_app(self.bridge)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    def _make_app(self, bridge: FakeBridge, **options):
        @web.middleware
        async def native_auth(request, handler):
            self.auth_calls += 1
            if request.headers.get("X-Native-Auth") != "fixture-secret":
                return web.json_response({"error": "unauthorized"}, status=401)
            return await handler(request)

        async def pass_through(request):
            return web.json_response({"passed": True, "path": request.path})

        app = web.Application(middlewares=[native_auth])
        app.router.add_route("*", "/{tail:.*}", pass_through)
        self.controller = self.install_native_admission(app, lambda: bridge, **options)
        return app

    async def _wait_for_acquire(self, bridge=None):
        bridge = bridge or self.bridge
        for _ in range(20):
            if bridge.references > 0:
                return
            await asyncio.sleep(0.01)
        self.fail("request did not acquire its bridge lease within 200 ms")

    @staticmethod
    def _auth(**extra):
        return {"X-Native-Auth": "fixture-secret", **extra}

    async def _post_turn(self, turn_id="turn-1", text="hello", *, client=None, **kwargs):
        client = client or self.client
        return await client.post(
            "/api/companion/turn",
            json={"turn_id": turn_id, "text": text},
            headers=self._auth(**kwargs),
        )

    async def _post_cancel(self, turn_id="turn-1", *, client=None):
        client = client or self.client
        return await client.post(
            "/api/companion/cancel",
            json={"turn_id": turn_id},
            headers=self._auth(),
        )

    async def test_capabilities_report_only_process_local_best_effort_admission(self):
        response = await self.client.get(
            "/api/companion/admission-capabilities", headers=self._auth()
        )
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body.get("feature"), "http-turn-admission-v1")
        self.assertIs(body.get("durable"), False)
        self.assertIs(body.get("exactly_once"), False)

    async def test_unrelated_original_route_passes_through(self):
        response = await self.client.get("/api/companion/status", headers=self._auth())
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {
            "passed": True, "path": "/api/companion/status",
        })
        self.assertEqual(self.bridge.send_calls, [])

    async def test_native_auth_denies_before_turn_id_is_reserved(self):
        denied = await self.client.post(
            "/api/companion/turn",
            json={"turn_id": "same-id", "text": "hello"},
        )
        self.assertEqual(denied.status, 401)
        accepted = await self._post_turn("same-id")
        self.assertLess(accepted.status, 300)
        self.assertEqual(self.bridge.send_calls, [("hello", "same-id")])

    async def test_turn_validation_is_strict_and_has_no_bridge_effects(self):
        invalid_ids = (
            "", "a" * 129, "has space", "unicode-л", "bad/id", "nul\x00id",
            True, 7, ["id"],
        )
        for value in invalid_ids:
            with self.subTest(turn_id=value):
                response = await self.client.post(
                    "/api/companion/turn",
                    json={"turn_id": value, "text": "hello"},
                    headers=self._auth(),
                )
                self.assertGreaterEqual(response.status, 400)
        for body in (
            {"turn_id": "valid-id", "text": 3},
            {"turn_id": "valid-id", "text": "x" * 8001},
        ):
            with self.subTest(body_keys=tuple(body)):
                response = await self.client.post(
                    "/api/companion/turn", json=body, headers=self._auth()
                )
                self.assertGreaterEqual(response.status, 400)
        self.assertEqual(self.bridge.send_calls, [])
        self.assertEqual(self.bridge.acquires, 0)

        boundary = await self._post_turn("max-text", "x" * 8000)
        self.assertLess(boundary.status, 300)
        self.assertEqual(self.bridge.send_calls, [("x" * 8000, "max-text")])
        self.assertEqual(self.bridge.acquires, self.bridge.releases)

    async def test_cancel_during_readiness_prevents_the_first_native_send(self):
        self.bridge.set_connected(False)
        turn = asyncio.create_task(self._post_turn("waiting-turn"))
        await self._wait_for_acquire()

        response = await self._post_cancel("waiting-turn")
        result = await response.json()
        self.assertEqual(response.status, 200)
        self.assertIs(result.get("ok"), True)
        self.assertEqual(result.get("turn_id"), "waiting-turn")
        self.assertIs(result.get("local_dispatch_prevented"), True)
        self.assertIs(result.get("forwarded"), False)

        self.bridge.set_connected(True)
        turn_response = await asyncio.wait_for(turn, 1)
        await turn_response.read()
        self.assertEqual(self.bridge.send_calls, [])
        self.assertEqual(self.bridge.references, 0)
        self.assertEqual(self.bridge.acquires, self.bridge.releases)

    async def test_cancel_before_turn_reserves_tombstone_and_never_dispatches(self):
        cancelled = await self._post_cancel("early-cancel")
        self.assertEqual(cancelled.status, 200)
        self.assertEqual(await cancelled.json(), {
            "ok": True,
            "turn_id": "early-cancel",
            "local_dispatch_prevented": True,
            "forwarded": True,
        })
        turn = await self._post_turn("early-cancel")
        await turn.read()
        self.assertEqual(self.bridge.send_calls, [])

    async def test_concurrent_retry_after_lost_ack_cannot_send_twice(self):
        self.bridge.send_gate = asyncio.Event()
        first = asyncio.create_task(self._post_turn("lost-ack"))
        await asyncio.wait_for(self.bridge.send_started.wait(), 1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first

        retry = await self._post_turn("lost-ack")
        self.assertEqual(retry.status, 409)
        self.assertEqual(self.bridge.send_calls, [("hello", "lost-ack")])
        self.bridge.send_gate.set()
        await asyncio.sleep(0)

    async def test_capacity_fails_closed_without_evicting_existing_tombstone(self):
        await self.client.close()
        self.bridge = FakeBridge()
        self.app = self._make_app(self.bridge, max_entries=1)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

        first = await self._post_cancel("retained")
        self.assertEqual(first.status, 200)
        full = await self._post_turn("new-entry")
        self.assertEqual(full.status, 503)
        duplicate_cancel = await self._post_cancel("retained")
        self.assertEqual(duplicate_cancel.status, 200)
        self.assertEqual(self.bridge.send_calls, [])

    async def test_expired_tombstone_can_be_reused(self):
        await self.client.close()
        self.bridge = FakeBridge()
        self.app = self._make_app(self.bridge, ttl_seconds=0.03)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

        now = [100.0]
        self.controller.clock = lambda: now[0]
        await self._post_cancel("reusable")
        now[0] += 0.031
        response = await self._post_turn("reusable")
        self.assertLess(response.status, 300)
        self.assertEqual(self.bridge.send_calls, [("hello", "reusable")])

    async def test_disconnected_readiness_waiter_is_not_dispatched_after_reconnect(self):
        await self.client.close()
        self.bridge = FakeBridge(connected=False)
        self.app = self._make_app(self.bridge)
        server = TestServer(self.app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        address = urlsplit(str(server.make_url("/api/companion/turn")))
        reader, writer = await asyncio.open_connection(address.hostname, address.port)
        body = json.dumps({"turn_id": "gone-client", "text": "hello"}).encode()
        writer.write(
            b"POST /api/companion/turn HTTP/1.1\r\n"
            + f"Host: {address.hostname}:{address.port}\r\n".encode()
            + b"X-Native-Auth: fixture-secret\r\n"
            + b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        await self._wait_for_acquire()
        writer.close()
        await writer.wait_closed()
        self.bridge.set_connected(True)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.bridge.send_started.wait(), 0.08)
        self.assertEqual(self.bridge.references, 0)
        self.assertEqual(self.bridge.acquires, self.bridge.releases)
        del reader

    async def test_ready_timeout_releases_bridge_reference(self):
        await self.client.close()
        self.bridge = FakeBridge(connected=False)
        self.app = self._make_app(self.bridge, ready_timeout_seconds=0.03)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

        response = await self._post_turn("readiness-timeout")
        await response.read()
        self.assertGreaterEqual(response.status, 400)
        self.assertEqual(self.bridge.references, 0)
        self.assertEqual(self.bridge.acquires, self.bridge.releases)
        self.assertEqual(self.bridge.send_calls, [])

    async def test_send_timeout_releases_bridge_reference(self):
        await self.client.close()
        self.bridge = FakeBridge()
        self.bridge.send_gate = asyncio.Event()
        self.app = self._make_app(self.bridge, send_timeout_seconds=0.03)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

        response = await self._post_turn("send-timeout")
        await response.read()
        self.assertGreaterEqual(response.status, 400)
        self.assertEqual(self.bridge.send_calls, [("hello", "send-timeout")])
        self.assertEqual(self.bridge.references, 0)
        self.assertEqual(self.bridge.acquires, self.bridge.releases)

    async def test_cancel_after_dispatch_forwards_exact_id_best_effort(self):
        self.bridge.send_gate = asyncio.Event()
        turn = asyncio.create_task(self._post_turn("already-sent"))
        await asyncio.wait_for(self.bridge.send_started.wait(), 1)
        cancelled = await self._post_cancel("already-sent")
        body = await cancelled.json()
        self.assertEqual(cancelled.status, 200)
        self.assertEqual(self.bridge.cancel_calls[0][0], "already-sent")
        self.assertNotIn("exactly_once", body)
        self.bridge.send_gate.set()
        response = await asyncio.wait_for(turn, 1)
        await response.read()
        self.assertEqual(self.bridge.references, 0)
        self.assertEqual(self.bridge.acquires, self.bridge.releases)

    async def test_payload_over_http_limit_is_rejected_before_bridge_effects(self):
        body = json.dumps({
            "turn_id": "oversize", "text": "hello", "padding": "x" * (128 * 1024),
        }).encode()
        response = await self.client.post(
            "/api/companion/turn",
            data=body,
            headers=self._auth(**{"Content-Type": "application/json"}),
        )
        await response.read()
        self.assertGreaterEqual(response.status, 400)
        self.assertEqual(self.bridge.send_calls, [])
        self.assertEqual(self.bridge.acquires, 0)


if __name__ == "__main__":
    unittest.main()
