"""Extra admission boundaries: scheduling, active retention, JSON, total read deadline."""
import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.native_jawl_admission import NativeAdmission, install_native_admission, _Rejected


class _Bridge:
    def __init__(self):
        self.refs = 0
        self.sent = []
        self.cancelled = []
        self.before_dispatch = None

    @property
    def connected(self):
        if self.before_dispatch:
            callback, self.before_dispatch = self.before_dispatch, None
            asyncio.get_running_loop().call_soon(callback)
        return True

    async def acquire(self):
        self.refs += 1

    async def release(self):
        self.refs -= 1

    async def send(self, text, turn_id):
        self.sent.append(turn_id)
        return {"ok": True}

    async def cancel(self, turn_id, reason):
        self.cancelled.append(turn_id)
        return {"ok": True, "turn_id": turn_id}


class NativeAdmissionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = _Bridge()
        app = web.Application()

        async def original(_request):
            self.fail("guarded native route reached original unsafe admission")

        app.router.add_post("/api/companion/turn", original)
        self.guard = install_native_admission(app, lambda: self.bridge)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_cancel_scheduled_between_readiness_and_dispatch_task_prevents_write(self):
        self.bridge.before_dispatch = lambda: self.guard._cancel("schedule-race")
        original_wait = asyncio.wait_for

        async def scheduled_wait(awaitable, timeout):
            # Pinned Python3.11 schedules wait_for's coroutine in a task;
            # newer Python can run it inline. Exercise the real3.11 interleave
            # deterministically on both test interpreters.
            if getattr(awaitable, "__name__", None) == "dispatch":
                awaitable = asyncio.create_task(awaitable)
            return await original_wait(awaitable, timeout)

        with patch("jawl_voicecompanion.native_jawl_admission.asyncio.wait_for", scheduled_wait):
            response = await self.client.post("/api/companion/turn", json={"turn_id": "schedule-race", "text": "never"})
        self.assertEqual(response.status, 409)
        self.assertEqual(self.bridge.sent, [])
        self.assertEqual(self.bridge.refs, 0)

    async def test_duplicate_json_fields_are_rejected_before_admission(self):
        response = await self.client.post("/api/companion/turn", data=b'{"turn_id":"first","turn_id":"second","text":"never"}')
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"], "duplicate_json_field")
        self.assertEqual(self.guard._entries, {})
        self.assertEqual(self.bridge.sent, [])

    async def test_trickled_body_has_absolute_deadline_not_per_read_timeout(self):
        url = self.client.server.make_url("/")
        reader, writer = await asyncio.open_connection(url.host, url.port)
        try:
            writer.write(b'POST /api/companion/turn HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\n{')
            await writer.drain()
            # Continue supplying bytes often enough to defeat an inactivity-only timeout.
            async def trickle():
                for _ in range(8):
                    await asyncio.sleep(.2)
                    writer.write(b' ')
                    await writer.drain()
            task = asyncio.create_task(trickle())
            try:
                status = await asyncio.wait_for(reader.readline(), 1.8)
                self.assertIn(b'408', status)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(self.guard._entries, {})
            self.assertEqual(self.bridge.sent, [])
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_active_entry_cannot_expire_or_be_evicted_at_capacity(self):
        guard = NativeAdmission(lambda: self.bridge, max_entries=1, ttl_seconds=1)
        now = [0.0]
        guard.clock = lambda: now[0]
        active = guard._reserve("active")
        now[0] = 10
        with self.assertRaises(_Rejected) as caught:
            guard._reserve("replacement")
        self.assertEqual(caught.exception.status, 503)
        self.assertIs(guard._entries["active"], active)
        guard._cancel("active")
        self.assertTrue(active.pending)
        guard._prune()
        self.assertIs(guard._entries["active"], active)
        active.pending = False
        guard._prune()
        self.assertEqual(guard._entries, {})

    async def test_expired_dispatch_history_still_forwards_cancel_to_native_owner(self):
        old = self.guard._reserve("long-native-turn")
        old.pending, old.dispatched = False, True
        old.expires = self.guard.clock() - 1
        response = await self.client.post("/api/companion/cancel", json={"turn_id": "long-native-turn"})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.bridge.cancelled, ["long-native-turn"])
        self.assertTrue((await response.json())["forwarded"])
        blocked = await self.client.post("/api/companion/turn", json={"turn_id": "long-native-turn", "text": "never replay"})
        self.assertEqual(blocked.status, 409)
        self.assertEqual(self.bridge.sent, [])


if __name__ == "__main__":
    unittest.main()
