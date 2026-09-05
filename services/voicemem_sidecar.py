"""Small JSON-lines runner for the optional VoiceMem environment."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4


MAX_LINE_BYTES = 64 * 1024
MAX_TEXT_CHARS = 12_000
MAX_CONTEXT_CHARS = 6_000
MAX_SESSIONS = 32
MAX_AUDIO_BYTES = 48 * 1024
END_AUDIO_SILENCE_SECONDS = 0.8
END_AUDIO_FRAME_SECONDS = 0.032


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    return str(value or "").strip()[:limit]


class VoiceMemSidecar:
    """Translate bounded requests into VoiceMem calls."""

    def __init__(self, stream_factory: Callable[[str], Any], audio_sample_rate: int = 16000):
        self._stream_factory = stream_factory
        self._streams: dict[str, Any] = {}
        self._last_partial: dict[str, str] = {}
        self._audio_sample_rate = int(audio_sample_rate)
        self._status = "ready"
        self._last_error = ""
        self._audio_models_loaded = False

    async def handle(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        request_id = _text(request.get("request_id"), 100) or str(uuid4())
        if request.get("type") == "health":
            return [{"type": "health", "request_id": request_id, **self.health()}]
        request_type = request.get("type")
        if request_type not in {"warmup", "feed_partial", "feed_audio", "end_audio"}:
            return [self._error(request_id, "unsupported_request")]

        if request_type == "warmup":
            kind = request.get("kind", "text")
            if kind not in {"text", "audio"}:
                return [self._error(request_id, "warmup_kind_must_be_text_or_audio")]
            warmup = getattr(self._stream_factory, "warmup", None)
            if not callable(warmup):
                return [self._error(request_id, "warmup_not_supported")]
            try:
                await asyncio.to_thread(warmup, kind == "audio")
                self._status, self._last_error = "ready", ""
                if kind == "audio":
                    self._audio_models_loaded = True
            except Exception:
                self._status, self._last_error = "degraded", "voicemem_warmup_failed"
                return [self._error(request_id, self._last_error)]
            return [self._event(request_id, "local", "VOICE_READY", {
                "mode": kind,
                "audio_models_loaded": kind == "audio",
            })]

        session_id = _text(request.get("session_id"), 200) or "local"
        text = ""
        ended = False
        audio = b""
        if request_type == "feed_partial":
            text = _text(request.get("text"))
            ended = request.get("ended", False)
            if not isinstance(ended, bool):
                return [self._error(request_id, "ended_must_be_boolean", session_id)]
        elif request_type == "feed_audio":
            try:
                audio = self._decode_audio(request)
            except ValueError as exc:
                return [self._error(request_id, str(exc), session_id)]
        try:
            stream = self._streams.get(session_id)
            if stream is None:
                if request_type == "end_audio":
                    # Do not initialize VoiceMem merely to flush a session
                    # that never received audio.
                    self._status, self._last_error = "ready", ""
                    return []
                if len(self._streams) >= MAX_SESSIONS:
                    return [self._error(request_id, "session_limit_reached", session_id)]
                stream = self._stream_factory(session_id)
                self._streams[session_id] = stream
            if request_type == "feed_partial":
                state = await stream.feed_partial(text, ended=ended)
            elif request_type == "end_audio":
                # VoiceMem's VAD is frame-oriented. Feeding one large silence
                # block can be classified as a single ambiguous frame and
                # leave the stream without its required turn-over transition.
                # Flush bounded 32 ms frames and stop as soon as VoiceMem
                # confirms the turn; this keeps end latency low and works for
                # both the bundled sherpa and injected test streams.
                frame_bytes = max(
                    2,
                    int(self._audio_sample_rate * END_AUDIO_FRAME_SECONDS * 2) & ~1,
                )
                state = None
                for _ in range(max(1, int(END_AUDIO_SILENCE_SECONDS / END_AUDIO_FRAME_SECONDS))):
                    state = await stream.feed(b"\0" * frame_bytes)
                    if getattr(state, "turn", None) is not None:
                        break
                if state is None:
                    raise RuntimeError("VoiceMem silence flush produced no state")
            else:
                state = await stream.feed(audio)
                self._audio_models_loaded = True
            self._status, self._last_error = "ready", ""
        except Exception:
            self._status, self._last_error = "degraded", "voicemem_stream_failed"
            self._streams.pop(session_id, None)
            self._last_partial.pop(session_id, None)
            return [self._error(request_id, self._last_error, session_id)]

        events: list[dict[str, Any]] = []
        state_text = _text(getattr(state, "text", ""))
        should_emit_partial = bool(state_text) and (
            request_type == "feed_partial" or self._last_partial.get(session_id) != state_text
        )
        if should_emit_partial:
            self._last_partial[session_id] = state_text
            events.append(self._event(request_id, session_id, "USER_PARTIAL", {
                "text": state_text,
                "is_final": False,
            }))
        turn = getattr(state, "turn", None)
        if turn is not None:
            events.append(self._event(request_id, session_id, "VOICE_TURN", {
                "text": _text(getattr(turn, "text", state_text)),
                "is_final": True,
                "memory_context": _text(getattr(state, "memory_context", ""), MAX_CONTEXT_CHARS),
                "affect": self._affect(state),
                "speaker_id": _text(getattr(state, "speaker_id", ""), 200),
            }))
        return events

    def health(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "streams": len(self._streams),
            "last_error": self._last_error,
            "audio_models_loaded": self._audio_models_loaded,
            "audio_input": "pcm16",
            "audio_sample_rate": self._audio_sample_rate,
        }

    def _decode_audio(self, request: dict[str, Any]) -> bytes:
        encoded = request.get("pcm16_base64")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("pcm16_base64 must be a non-empty string")
        sample_rate = request.get("sample_rate", self._audio_sample_rate)
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int):
            raise ValueError("sample_rate must be an integer")
        if sample_rate != self._audio_sample_rate:
            raise ValueError("sample_rate does not match the sidecar input rate")
        channels = request.get("channels", 1)
        if channels != 1:
            raise ValueError("only mono audio is supported")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("pcm16_base64 is invalid") from exc
        if not audio or len(audio) > MAX_AUDIO_BYTES or len(audio) % 2:
            raise ValueError("audio chunk is empty, too large or not PCM16")
        return audio

    async def run_stdio(self) -> None:
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not raw:
                return
            request_id = ""
            if len(raw) > MAX_LINE_BYTES:
                responses = [self._error(request_id, "request_too_large")]
            else:
                try:
                    request = json.loads(raw.decode("utf-8"))
                    if not isinstance(request, dict):
                        raise ValueError("request_must_be_object")
                    request_id = _text(request.get("request_id"), 100)
                    responses = await self.handle(request)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    responses = [self._error(request_id, "invalid_json_request")]
            for response in responses:
                self._write(response)
            self._write({
                "type": "request_complete",
                "request_id": request_id,
                "events": len(responses),
            })

    @staticmethod
    def _affect(state: Any) -> dict[str, Any]:
        try:
            emotion = _text(getattr(state, "emotion", ""), 120)
        except Exception:
            emotion = ""
        return {"label": emotion} if emotion else {}

    @staticmethod
    def _event(request_id: str, session_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "request_id": request_id,
            "session_id": session_id,
            "created_at": _now(),
            "source": "voicemem_sidecar",
            "type": kind,
            "priority": 0,
            "payload": payload,
        }

    @staticmethod
    def _error(request_id: str, reason: str, session_id: str = "local") -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "request_id": request_id,
            "session_id": session_id,
            "created_at": _now(),
            "source": "voicemem_sidecar",
            "type": "VOICE_DEGRADED",
            "priority": 4,
            "payload": {"reason": _text(reason, 200)},
        }

    @staticmethod
    def _write(payload: dict[str, Any]) -> None:
        # ``VoiceMem`` prints speculative-search diagnostics to stdout. The
        # sidecar's stdout is a machine-readable JSON-lines channel, so the
        # protocol must use the original stream explicitly after ``main``
        # redirects ordinary model diagnostics to stderr.
        stream = getattr(sys, "__stdout__", sys.stdout)
        buffer = getattr(stream, "buffer", stream)
        buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        buffer.flush()


def _voice_mem_factory(args: argparse.Namespace) -> Callable[[str], Any]:
    vm = None

    def ensure_vm() -> Any:
        nonlocal vm
        if vm is not None:
            return vm
        from voicemem import VoiceMem

        overrides: dict[str, Any] = {}
        if args.local_memory:
            # VoiceMem's convenience constructor leaves the default
            # QuerySlotClassifier on its network-backed path. In a
            # Companion sidecar that would make a local audio turn fail
            # late during VAD confirmation when no OpenAI key exists.
            # Inject both local pieces explicitly so speculation/search
            # stays offline and uses the same E5 weights.
            from voicemem.leftbrain.cognitive_graph.local_query_classifier import LocalQueryClassifier
            from voicemem.leftbrain.local_e5_embedder import LocalE5Embedder

            overrides = {
                "schema": lambda: LocalQueryClassifier(),
                "embedding": lambda: LocalE5Embedder(),
            }
        # The local VoiceMem cognitive components still construct an
        # OpenAI-compatible client even when the actual classifier
        # and embedder are injected locally. A non-secret sentinel
        # keeps that construction valid; local-memory mode never
        # sends it to a provider.
        vm = VoiceMem(
            mode=args.mode,
            memory_root=args.memory_root,
            user_id=args.user_id,
            base_url=args.base_url,
            api_key=(
                os.environ.get(args.api_key_env, "")
                or ("local_dummy_key" if args.local_memory else "")
                or None
            ),
            **overrides,
        )
        return vm

    def make_stream(_session_id: str) -> Any:
        return ensure_vm().stream(src_rate=args.audio_sample_rate)

    def warmup(audio: bool = False) -> None:
        ensure_vm().warmup(audio=bool(audio), verbose=False)

    # Keep the runner small while exposing one explicit lifecycle hook to the
    # sidecar; it is intentionally not a second public model interface.
    make_stream.warmup = warmup  # type: ignore[attr-defined]

    return make_stream


def _stub_factory(_session_id: str) -> Any:
    class StubStream:
        async def feed_partial(self, text: str, ended: bool = False) -> Any:
            return SimpleNamespace(
                text=text,
                turn=SimpleNamespace(text=text) if ended and text else None,
                memory_context="",
                emotion="",
                speaker_id="",
            )

        async def feed(self, pcm_bytes: bytes) -> Any:
            ended = pcm_bytes == b"final!" or not any(pcm_bytes)
            text = "аудио e2e" if pcm_bytes == b"final!" else "аудио"
            return SimpleNamespace(
                text=text,
                turn=SimpleNamespace(text=text) if ended else None,
                memory_context="",
                emotion="",
                speaker_id="",
            )

    return StubStream()


def main() -> None:
    parser = argparse.ArgumentParser(description="VoiceMem JSON-lines sidecar")
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--audio-sample-rate", type=int, default=16000)
    parser.add_argument("--memory-root", default=None)
    parser.add_argument("--user-id", default="voice_user")
    parser.add_argument("--base-url", default=None)
    parser.add_argument(
        "--local-memory",
        action="store_true",
        help="use VoiceMem's local E5 classifier/embedder without an LLM request",
    )
    parser.add_argument("--api-key-env", default="VOICEMEM_API_KEY")
    parser.add_argument("--test-stub", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    factory = _stub_factory if args.test_stub else _voice_mem_factory(args)
    try:
        # Keep third-party/model prints out of the JSON-lines protocol. The
        # protocol writer above retains the original stdout pipe.
        sys.stdout = sys.stderr
        asyncio.run(VoiceMemSidecar(factory, audio_sample_rate=args.audio_sample_rate).run_stdio())
    except Exception as exc:
        print(f"VoiceMem sidecar failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
