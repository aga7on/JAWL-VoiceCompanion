"""Kernel speech-first streaming: speak the reply before the envelope closes.

Spec lineage: the retired product extension ``native_jawl_streaming``
(ADR-049 slice 2). Only ``delta.content`` is observed; reasoning and private
envelope fields are never emitted; the consumer stream is unchanged.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "runtime"
    / "jawl-sources"
    / "jawl-20260906-daily-v2"
)
os.environ.setdefault(
    "JAWL_LOG_DIR", tempfile.mkdtemp(prefix="jawl-test-logs-stream-")
)
sys.path.insert(0, str(_SNAPSHOT))

from src.l2_interfaces.host.terminal.events import HostTerminalEvents  # noqa: E402
from src.l3_agent.companion_gateway import (  # noqa: E402
    SpeechDeltaSink,
    bind_speech_sink,
    reset_speech_sink,
)
from src.l3_agent.llm.providers import openai_compatible  # noqa: E402

REPLY = "Привет! Как у тебя дела? Я рядом."
ENVELOPE = (
    '{"observation": "секретное наблюдение", "reasoning": "скрытая мысль", '
    '"actions": [{"tool_name": "HostTerminalMessages.send_message_to_terminal", '
    f'"parameters": {{"text": "{REPLY}"}}}}]}}'
)


@dataclass
class _Request:
    stream: bool = False
    tool_transport: str = "json_envelope"


def _chunk(content: str = "", reasoning: str = ""):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning or None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


async def _collect(stream):
    parts = []
    async for chunk in stream:
        parts.append(chunk)
    return parts


class _Bus:
    def __init__(self):
        self.published = []

    async def publish(self, event, **payload):
        self.published.append((event, payload))


class KernelStreamingTests(unittest.IsolatedAsyncioTestCase):
    def _bound_sink(self, bus):
        sink = SpeechDeltaSink(bus, "stream-turn")
        token = bind_speech_sink(sink)
        self.addCleanup(reset_speech_sink, token)
        self.addCleanup(sink.close)
        return sink

    @staticmethod
    def _spoken(bus):
        return [p.get("speech_text", "") for _, p in bus.published]

    async def test_sentences_are_emitted_before_the_envelope_closes(self):
        bus = _Bus()
        self._bound_sink(bus)
        pieces = [ENVELOPE[i : i + 7] for i in range(0, len(ENVELOPE), 7)]

        async def stream():
            for piece in pieces:
                yield _chunk(piece)

        collected = await _collect(openai_compatible._tee_speech(stream()))
        self.assertEqual("".join(c.choices[0].delta.content for c in collected), ENVELOPE)
        spoken = self._spoken(bus)
        self.assertTrue(spoken)
        self.assertEqual(spoken[0], "Привет!")
        self.assertIn("Я рядом.", " ".join(spoken))

    async def test_private_fields_and_reasoning_are_never_emitted(self):
        bus = _Bus()
        self._bound_sink(bus)

        async def stream():
            yield _chunk(ENVELOPE, reasoning="скрытая мысль полностью")

        await _collect(openai_compatible._tee_speech(stream()))
        joined = " ".join(self._spoken(bus))
        self.assertNotIn("секретное наблюдение", joined)
        self.assertNotIn("скрытая мысль", joined)
        self.assertEqual(
            self._spoken(bus), ["Привет!", "Как у тебя дела?", "Я рядом."]
        )

    async def test_tail_without_a_final_boundary_is_flushed(self):
        bus = _Bus()
        self._bound_sink(bus)
        envelope = (
            '{"actions": [{"tool_name": "HostTerminalMessages.send_message_to_terminal", '
            '"parameters": {"text": "Готов начать"}}]}'
        )

        async def stream():
            yield _chunk(envelope)

        await _collect(openai_compatible._tee_speech(stream()))
        self.assertEqual("".join(self._spoken(bus)), "Готов начать")

    async def test_sink_dedups_repeated_sentences(self):
        bus = _Bus()
        sink = self._bound_sink(bus)
        self.assertTrue(await sink.emit("Один раз."))
        self.assertTrue(await sink.emit("Дважды."))
        self.assertFalse(await sink.emit("Один раз."))
        self.assertEqual(self._spoken(bus), ["Один раз.", "Дважды."])

    async def test_sink_close_stops_emission(self):
        bus = _Bus()
        sink = SpeechDeltaSink(bus, "closed-turn")
        sink.close()
        self.assertFalse(await sink.emit("Не должно прозвучать."))
        self.assertEqual(self._spoken(bus), [])

    async def test_no_sink_leaves_the_stream_untouched(self):
        bus = _Bus()

        async def stream():
            yield _chunk(ENVELOPE)

        original = stream()
        teed = openai_compatible._tee_speech(original)
        self.assertIs(teed, original)
        self.assertEqual(bus.published, [])

    def test_stream_first_request_streams_only_local_json_envelope_turns(self):
        bus = _Bus()
        sink = SpeechDeltaSink(bus, "decision-turn")
        token = bind_speech_sink(sink)
        try:
            local = SimpleNamespace(
                client=SimpleNamespace(base_url="http://127.0.0.1:8001/v1")
            )
            remote = SimpleNamespace(client=SimpleNamespace(base_url="https://api.example"))
            request = _Request()
            self.assertTrue(
                openai_compatible._stream_first_request(local, request).stream
            )
            self.assertFalse(
                openai_compatible._stream_first_request(remote, request).stream
            )
            plain = _Request(tool_transport="native")
            self.assertFalse(
                openai_compatible._stream_first_request(local, plain).stream
            )
        finally:
            reset_speech_sink(token)

        self.assertFalse(openai_compatible._stream_first_request(local, _Request()).stream)

    def test_kernel_wiring_tees_the_stream_and_bridges_the_delta(self):
        provider_src = (
            _SNAPSHOT / "src" / "l3_agent" / "llm" / "providers" / "openai_compatible.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_stream_first_request(self, request)", provider_src)
        self.assertIn("_tee_speech(stream)", provider_src)

        events_src = (
            _SNAPSHOT / "src" / "l2_interfaces" / "host" / "terminal" / "events.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Events.COMPANION_SPEECH_DELTA", events_src)
        self.assertIn('"assistant.delta"', events_src)

        loop_src = (_SNAPSHOT / "src" / "l3_agent" / "react" / "loop.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("SpeechDeltaSink(", loop_src)
        self.assertIn("bind_speech_sink", loop_src)
        self.assertIn("reset_speech_sink", loop_src)

    async def test_speech_delta_bridges_to_assistant_delta(self):
        emitted = []

        class _Client:
            async def emit_gateway_event(self, turn_id, event_type, payload):
                emitted.append((turn_id, event_type, payload))

        class _BusWithSubscribe(_Bus):
            def subscribe(self, event, handler):
                return None

        events = HostTerminalEvents(_Client(), _BusWithSubscribe())
        await events._handle_speech_delta(
            companion_turn_id="bridge-turn",
            speech_text="  " + "А" * 2100,
            event_format="speech",
        )
        await events._handle_speech_delta(companion_turn_id="", speech_text="x")
        self.assertEqual(len(emitted), 1)
        turn_id, event_type, payload = emitted[0]
        self.assertEqual(turn_id, "bridge-turn")
        self.assertEqual(event_type, "assistant.delta")
        self.assertEqual(payload["format"], "speech")
        self.assertLessEqual(len(payload["text"]), 2000)


if __name__ == "__main__":
    unittest.main()
