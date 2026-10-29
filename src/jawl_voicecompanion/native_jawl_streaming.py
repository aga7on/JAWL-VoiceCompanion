"""Owned streaming hook: speak the reply before the JSON envelope closes.

The pinned JAWL provider sends one non-streamed completion and the terminal
gateway only ever sees ``assistant.final``.  That is why the voice lane had to
wait for the whole JSON envelope before the first sound.

This hook wraps the pinned ``OpenAICompatibleProvider``:

1. ``complete`` is called with ``stream=True`` for the local JSON-envelope lane
   inside an active correlated turn;
2. ``_consume_stream`` is teed, so every visible content fragment also feeds a
   :class:`SpeechFirstGate` (loaded from the owned ``speech_first.py``);
3. each complete reply sentence is emitted as one ``assistant.delta`` event with
   ``format="speech"``, which the Companion routes to live TTS.

Only ``delta.content`` is observed.  ``reasoning_content`` and the private
envelope fields are never emitted.  The returned ``LLMResult`` is unchanged:
the pinned parser still receives exactly the same final text.
"""
from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import time
from typing import Any, Callable
from urllib.parse import urlsplit

_INSTALL_ATTR = "__jawl_owned_streaming_installation__"
ROOT = Path(__file__).resolve().parents[2]
_MAX_STREAM_SECONDS = 300.0


def _load_speech_gate() -> type:
    """Load the standalone ``speech_first`` module from the repo."""
    installed = sys.modules.get("_owned_jawl_speech_first")
    if installed is not None:
        return installed.SpeechFirstGate
    path = ROOT / "src" / "jawl_voicecompanion" / "speech_first.py"
    spec = importlib.util.spec_from_file_location("_owned_jawl_speech_first", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("speech_first module is unavailable")
    module = importlib.util.module_from_spec(spec)
    # Register before execution: dataclasses resolves annotations through
    # sys.modules[cls.__module__] while the class body is being created.
    sys.modules["_owned_jawl_speech_first"] = module
    spec.loader.exec_module(module)
    return module.SpeechFirstGate


def _default_emitter(text: str) -> Any:
    """Emit through the owned delivery guard installed by the launcher."""
    delivery = sys.modules.get("_owned_jawl_delivery")
    emit = getattr(delivery, "emit_active_delta", None)
    if not callable(emit):
        async def _noop() -> bool:
            return False
        return _noop()
    return emit(text, event_format="speech")


def _is_local(provider: Any) -> bool:
    client = getattr(provider, "client", None)
    base_url = getattr(client, "base_url", "") or getattr(client, "api_url", "")
    try:
        parsed = urlsplit(str(base_url))
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "127.0.0.1", "localhost", "::1",
        }
    except ValueError:
        return False


def _visible_text(chunk: Any) -> str:
    """Return only user-visible streamed content, never hidden reasoning."""
    parts: list[str] = []
    for choice in getattr(chunk, "choices", None) or []:
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            parts.append(content)
    return "".join(parts)


def _active_turn() -> bool:
    delivery = sys.modules.get("_owned_jawl_delivery")
    cycle = getattr(delivery, "_CYCLE", None) if delivery is not None else None
    state = cycle.get() if cycle is not None else None
    return state is not None and not getattr(state, "closed", True)


@dataclass(frozen=True)
class NativeStreamingInstallation:
    provider_class: type
    original_complete: Callable[..., Any]
    wrapped_complete: Callable[..., Any]
    original_consume: Callable[..., Any]
    wrapped_consume: Callable[..., Any]
    emitter: Callable[[str], Any]


def install_native_streaming(
    provider_class: type | None = None,
    *,
    emitter: Callable[[str], Any] | None = None,
    should_stream: Callable[[Any, Any], bool] | None = None,
    max_stream_seconds: float = _MAX_STREAM_SECONDS,
) -> NativeStreamingInstallation:
    """Install the streaming hook on the pinned provider class (idempotent)."""
    if provider_class is None:
        provider_class = importlib.import_module(
            "src.l3_agent.llm.providers.openai_compatible"
        ).OpenAICompatibleProvider
    existing = vars(provider_class).get(_INSTALL_ATTR)
    if existing is not None:
        if (
            isinstance(existing, NativeStreamingInstallation)
            and provider_class.complete is existing.wrapped_complete
            and provider_class._consume_stream is existing.wrapped_consume
        ):
            return existing
        raise RuntimeError("native streaming hook is already differently installed")

    gate_class = _load_speech_gate()
    emit = emitter or _default_emitter
    budget = max(5.0, min(float(max_stream_seconds), 900.0))

    def default_should_stream(provider: Any, request: Any) -> bool:
        return (
            getattr(request, "tool_transport", "") == "json_envelope"
            and _is_local(provider)
            and _active_turn()
        )

    allow_stream = should_stream or default_should_stream
    original_complete = provider_class.complete
    original_consume = provider_class._consume_stream

    async def wrapped_complete(provider: Any, request: Any) -> Any:
        try:
            if allow_stream(provider, request):
                request = dataclasses.replace(request, stream=True)
        except Exception:
            pass
        return await original_complete(provider, request)

    async def wrapped_consume(provider: Any, stream: Any, request: Any) -> Any:
        gate = gate_class()
        deadline = time.monotonic() + budget

        def drain() -> list[str]:
            out: list[str] = []
            while True:
                piece = gate.feed("")
                if not piece:
                    return out
                out.append(piece)

        async def tee():
            async for chunk in stream:
                try:
                    text = _visible_text(chunk)
                    if text:
                        piece = gate.feed(text)
                        if piece:
                            await emit(piece)
                        for extra in drain():
                            await emit(extra)
                except Exception:
                    pass
                if time.monotonic() > deadline:
                    break
                yield chunk

        try:
            return await original_consume(provider, tee(), request)
        finally:
            try:
                tail = gate.flush()
                if tail:
                    await emit(tail)
            except Exception:
                pass

    wrapped_complete.__name__ = getattr(original_complete, "__name__", "complete")
    wrapped_consume.__name__ = getattr(original_consume, "__name__", "_consume_stream")
    setattr(provider_class, "complete", wrapped_complete)
    setattr(provider_class, "_consume_stream", wrapped_consume)
    installation = NativeStreamingInstallation(
        provider_class=provider_class,
        original_complete=original_complete,
        wrapped_complete=wrapped_complete,
        original_consume=original_consume,
        wrapped_consume=wrapped_consume,
        emitter=emit,
    )
    setattr(provider_class, _INSTALL_ATTR, installation)
    return installation


__all__ = ["NativeStreamingInstallation", "install_native_streaming"]
