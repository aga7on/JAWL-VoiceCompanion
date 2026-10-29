"""Tests for the owned brain streaming hook (speech-first deltas)."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.native_jawl_streaming import install_native_streaming  # noqa: E402

REPLY = "Привет! Как у тебя дела? Я рядом."
ENVELOPE = json.dumps(
    {
        "observation": "секретное наблюдение",
        "reasoning": "скрытая мысль",
        "actions": [
            {
                "tool_name": "HostTerminalMessages.send_message_to_terminal",
                "parameters": {"text": REPLY},
            }
        ],
    },
    ensure_ascii=False,
)


@dataclasses.dataclass
class _Request:
    stream: bool = False
    tool_transport: str = "json_envelope"


def _chunk(content: str = "", reasoning: str = ""):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning or None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class _FakeProvider:
    def __init__(self, pieces: list[str], reasoning: str = "") -> None:
        self.pieces = pieces
        self.reasoning = reasoning
        self.stream_flags: list[bool] = []

    async def complete(self, request):
        self.stream_flags.append(bool(request.stream))
        if request.stream:
            return await self._consume_stream(self._stream(), request)
        return "non-streamed"

    async def _stream(self):
        for piece in self.pieces:
            yield _chunk(piece, self.reasoning)

    async def _consume_stream(self, stream, request):
        parts: list[str] = []
        async for chunk in stream:
            parts.append(chunk.choices[0].delta.content or "")
        return "".join(parts)


class NativeStreamingTests(unittest.TestCase):
    @staticmethod
    def _install(provider_cls, emitter):
        return install_native_streaming(
            provider_cls,
            emitter=emitter,
            should_stream=lambda provider, request: True,
        )

    def test_streams_and_emits_sentences_before_the_envelope_closes(self):
        emitted: list[str] = []

        async def emitter(text: str) -> bool:
            emitted.append(text)
            return True

        class Provider(_FakeProvider):
            pass

        installation = self._install(Provider, emitter)
        provider = Provider([ENVELOPE[index : index + 7] for index in range(0, len(ENVELOPE), 7)])
        result = asyncio.run(provider.complete(_Request()))
        self.assertEqual(result, ENVELOPE)
        self.assertTrue(installation is not None)
        self.assertEqual(provider.stream_flags, [True])
        self.assertTrue(emitted)
        self.assertEqual(emitted[0], "Привет!")
        self.assertIn("Я рядом.", "".join(emitted))

    def test_private_fields_and_reasoning_are_never_emitted(self):
        emitted: list[str] = []

        async def emitter(text: str) -> bool:
            emitted.append(text)
            return True

        class Provider(_FakeProvider):
            pass

        self._install(Provider, emitter)
        provider = Provider([ENVELOPE], reasoning="скрытая мысль полностью")
        asyncio.run(provider.complete(_Request()))
        joined = "".join(emitted)
        self.assertNotIn("секретное наблюдение", joined)
        self.assertNotIn("скрытая мысль", joined)
        self.assertNotIn("скрытая мысль полностью", joined)
        self.assertEqual([piece.strip() for piece in emitted], ["Привет!", "Как у тебя дела?", "Я рядом."])

    def test_tail_without_a_final_boundary_is_flushed(self):
        emitted: list[str] = []

        async def emitter(text: str) -> bool:
            emitted.append(text)
            return True

        envelope = json.dumps(
            {
                "actions": [
                    {
                        "tool_name": "HostTerminalMessages.send_message_to_terminal",
                        "parameters": {"text": "Готов начать"},
                    }
                ]
            },
            ensure_ascii=False,
        )

        class Provider(_FakeProvider):
            pass

        self._install(Provider, emitter)
        provider = Provider([envelope])
        asyncio.run(provider.complete(_Request()))
        self.assertEqual("".join(emitted), "Готов начать")

    def test_installation_is_idempotent(self):
        class Provider(_FakeProvider):
            pass

        async def emitter(text: str) -> bool:
            return True

        first = self._install(Provider, emitter)
        second = self._install(Provider, emitter)
        self.assertIs(first, second)

    def test_non_streaming_path_is_preserved(self):
        emitted: list[str] = []

        async def emitter(text: str) -> bool:
            emitted.append(text)
            return True

        class Provider(_FakeProvider):
            pass

        install_native_streaming(
            Provider,
            emitter=emitter,
            should_stream=lambda provider, request: False,
        )
        provider = Provider([ENVELOPE])
        result = asyncio.run(provider.complete(_Request()))
        self.assertEqual(result, "non-streamed")
        self.assertEqual(emitted, [])


if __name__ == "__main__":
    unittest.main()
