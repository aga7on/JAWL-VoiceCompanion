from __future__ import annotations

import json
import os
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from jawl_voicecompanion.affective_engine import TokenBucketRateLimiter
from jawl_voicecompanion.gateway import TextGateway
from jawl_voicecompanion.web import (
    ENABLE_FAST_LANE,
    CompanionServer,
    create_server,
)


def _stop_test_server(server: CompanionServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    if thread.is_alive():
        server.server_close()
        thread.join(timeout=1)


class _FakeStreamingAsr:
    def __init__(self, text: str = "", active: bool = True, silence_ms: float = 800.0) -> None:
        self.text = text
        self.active = active
        self.silence_ms = silence_ms

    def snapshot(self, *, scope_id=None, session_id=None):
        return {"active": self.active, "text": self.text, "silence_ms": self.silence_ms}


class _FakeFusion:
    def __init__(self, line: str = "") -> None:
        self.line = line

    def compose(self) -> str:
        return self.line


class TokenBucketLimiterUnitTests(unittest.TestCase):
    def test_default_initialization(self):
        limiter = TokenBucketRateLimiter()
        self.assertEqual(limiter.capacity, 1.0)
        self.assertAlmostEqual(limiter.refill_rate, 1.0 / 6.0)
        self.assertEqual(limiter.min_spacing, 6.0)
        self.assertEqual(limiter.tokens, 1.0)

    def test_allow_and_exhaustion(self):
        limiter = TokenBucketRateLimiter(capacity=1.0, refill_rate=1.0 / 6.0, min_spacing=6.0)
        t0 = 1000.0
        self.assertTrue(limiter.allow(text="Хм, понятно", now=t0))
        self.assertEqual(limiter.tokens, 0.0)

        # Immediate re-query is rejected
        self.assertFalse(limiter.can_allow(text="Другая фраза", now=t0 + 1.0))
        self.assertFalse(limiter.allow(text="Другая фраза", now=t0 + 1.0))

    def test_refill_after_spacing(self):
        limiter = TokenBucketRateLimiter(capacity=1.0, refill_rate=1.0 / 6.0, min_spacing=6.0)
        t0 = 1000.0
        self.assertTrue(limiter.allow(text="Первая фраза", now=t0))

        # At t0 + 6.0, 1 token refilled and min_spacing satisfied
        t1 = t0 + 6.1
        self.assertTrue(limiter.can_allow(text="Вторая фраза", now=t1))
        self.assertTrue(limiter.allow(text="Вторая фраза", now=t1))

    def test_duplicate_phrase_suppressed(self):
        limiter = TokenBucketRateLimiter(capacity=1.0, refill_rate=1.0 / 6.0, min_spacing=6.0)
        t0 = 1000.0
        self.assertTrue(limiter.allow(text="Одинаковая фраза", now=t0))

        # Even after spacing, identical phrase is suppressed
        t1 = t0 + 10.0
        self.assertFalse(limiter.can_allow(text="Одинаковая фраза", now=t1))
        self.assertFalse(limiter.allow(text="одинаковая фраза", now=t1))  # Case-insensitive

    def test_suppressed_when_user_speaking(self):
        limiter = TokenBucketRateLimiter()
        self.assertFalse(limiter.can_allow(text="Фраза", user_speaking=True))
        self.assertFalse(limiter.allow(text="Фраза", user_speaking=True))

    def test_suppressed_when_muted(self):
        limiter = TokenBucketRateLimiter()
        self.assertFalse(limiter.can_allow(text="Фраза", muted=True))
        self.assertFalse(limiter.allow(text="Фраза", muted=True))

    def test_reset_restores_tokens_and_clears_text(self):
        limiter = TokenBucketRateLimiter()
        t0 = 1000.0
        limiter.allow(text="Фраза", now=t0)
        self.assertFalse(limiter.allow(text="Фраза", now=t0 + 1.0))

        limiter.reset()
        self.assertEqual(limiter.tokens, limiter.capacity)
        self.assertEqual(limiter.last_text, "")
        self.assertEqual(limiter.last_consumed, 0.0)

        # Now can immediately allow the same phrase
        self.assertTrue(limiter.allow(text="Фраза", now=t0 + 1.0))


class PrefaceEndpointPolicyTests(unittest.TestCase):
    def setUp(self):
        self._old_fast_lane_env = os.environ.get("ENABLE_FAST_LANE")
        os.environ.pop("ENABLE_FAST_LANE", None)

    def tearDown(self):
        if self._old_fast_lane_env is not None:
            os.environ["ENABLE_FAST_LANE"] = self._old_fast_lane_env
        else:
            os.environ.pop("ENABLE_FAST_LANE", None)

    def _start_server(
        self,
        *,
        partial: str = "Компаньон, что на экране?",
        fusion: _FakeFusion | None = None,
        enable_fast_lane: bool | None = None,
        silence_ms: float = 800.0,
    ) -> CompanionServer:
        if fusion is None:
            fusion = _FakeFusion("Экран: активное окно с графиком. Звук: тишина")
        server = create_server(
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=TextGateway(),
            streaming_asr=_FakeStreamingAsr(partial, silence_ms=silence_ms),
            perception_fusion=fusion,
            enable_fast_lane=enable_fast_lane,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(_stop_test_server, server, thread)
        self.base = f"http://127.0.0.1:{server.server_port}"
        self.session_headers = {
            "X-Companion-Session": server.session_token,
            "X-Companion-CSRF": server.csrf_token,
        }
        return server

    def _post(self, path: str, payload: dict, headers: dict | None = None):
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **(self.session_headers if headers is None else headers),
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_fast_lane_disabled_by_default(self):
        """When enable_fast_lane is omitted (default), preface is disabled."""
        self._start_server()
        status, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "disabled")
        self.assertEqual(data.get("text"), "")

    def test_fast_lane_explicitly_disabled(self):
        """When enable_fast_lane is explicitly False, preface is disabled."""
        self._start_server(enable_fast_lane=False)
        status, data = self._post("/api/voice/preface", {"session_id": "s1"})
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "disabled")
        self.assertEqual(data.get("text"), "")

    def test_stale_epoch_rejected(self):
        """When client requests preface with older generation_epoch, it is rejected."""
        server = self._start_server(enable_fast_lane=True)
        server.duplex_arbiter.generation_epoch = 3

        status, data = self._post(
            "/api/voice/preface",
            {"session_id": "s1", "generation_epoch": 2},
        )
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "stale_epoch")
        self.assertEqual(data.get("text"), "")

    def test_matching_epoch_accepted(self):
        """When client requests preface with matching generation_epoch, it succeeds."""
        server = self._start_server(enable_fast_lane=True)
        server.duplex_arbiter.generation_epoch = 3

        status, data = self._post(
            "/api/voice/preface",
            {"session_id": "s1", "generation_epoch": 3},
        )
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("text"), "Смотрю: активное окно с графиком.")
        self.assertNotIn("status", data)  # Successful response has text and ok

    def test_rate_limited_subsequent_preface(self):
        """Rapid subsequent preface requests hit the token-bucket rate limiter."""
        server = self._start_server(enable_fast_lane=True)
        server.duplex_arbiter.generation_epoch = 1

        # First request succeeds
        status1, data1 = self._post(
            "/api/voice/preface",
            {"session_id": "s1", "generation_epoch": 1},
        )
        self.assertEqual(status1, 200)
        self.assertEqual(data1.get("text"), "Смотрю: активное окно с графиком.")

        # Immediate second request should be rate-limited
        status2, data2 = self._post(
            "/api/voice/preface",
            {"session_id": "s1", "generation_epoch": 1},
        )
        self.assertEqual(status2, 200)
        self.assertTrue(data2.get("ok"))
        self.assertEqual(data2.get("status"), "rate_limited")
        self.assertEqual(data2.get("text"), "")
