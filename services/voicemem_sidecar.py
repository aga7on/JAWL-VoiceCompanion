"""Small JSON-lines runner for the optional VoiceMem environment."""

from __future__ import annotations

import argparse
import asyncio
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    return str(value or "").strip()[:limit]


class VoiceMemSidecar:
    """Translate bounded requests into VoiceMem ``feed_partial`` calls."""

    def __init__(self, stream_factory: Callable[[str], Any]):
        self._stream_factory = stream_factory
        self._streams: dict[str, Any] = {}
        self._status = "ready"
        self._last_error = ""

    async def handle(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        request_id = _text(request.get("request_id"), 100) or str(uuid4())
        if request.get("type") == "health":
            return [{"type": "health", "request_id": request_id, **self.health()}]
        if request.get("type") != "feed_partial":
            return [self._error(request_id, "unsupported_request")]

        session_id = _text(request.get("session_id"), 200) or "local"
        text = _text(request.get("text"))
        ended = request.get("ended", False)
        if not isinstance(ended, bool):
            return [self._error(request_id, "ended_must_be_boolean")]
        try:
            stream = self._streams.get(session_id)
            if stream is None:
                if len(self._streams) >= MAX_SESSIONS:
                    return [self._error(request_id, "session_limit_reached", session_id)]
                stream = self._stream_factory(session_id)
                self._streams[session_id] = stream
            state = await stream.feed_partial(text, ended=ended)
            self._status, self._last_error = "ready", ""
        except Exception:
            self._status, self._last_error = "degraded", "voicemem_stream_failed"
            return [self._error(request_id, self._last_error, session_id)]

        events: list[dict[str, Any]] = []
        if text:
            events.append(self._event(request_id, session_id, "USER_PARTIAL", {
                "text": _text(getattr(state, "text", text)),
                "is_final": False,
            }))
        turn = getattr(state, "turn", None)
        if ended and turn is not None:
            events.append(self._event(request_id, session_id, "VOICE_TURN", {
                "text": _text(getattr(turn, "text", text)),
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
            "audio_models_loaded": False,
        }

    async def run_stdio(self) -> None:
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not raw:
                return
            if len(raw) > MAX_LINE_BYTES:
                self._write(self._error("", "request_too_large"))
                continue
            try:
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request_must_be_object")
                responses = await self.handle(request)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                responses = [self._error("", "invalid_json_request")]
            for response in responses:
                self._write(response)
            self._write({
                "type": "request_complete",
                "request_id": _text(request.get("request_id"), 100),
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
        sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


def _voice_mem_factory(args: argparse.Namespace) -> Callable[[str], Any]:
    vm = None

    def make_stream(_session_id: str) -> Any:
        nonlocal vm
        if vm is None:
            from voicemem import VoiceMem

            vm = VoiceMem(
                mode=args.mode,
                memory_root=args.memory_root,
                user_id=args.user_id,
                base_url=args.base_url,
                api_key=os.environ.get(args.api_key_env, "") or None,
            )
        return vm.stream()

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

    return StubStream()


def main() -> None:
    parser = argparse.ArgumentParser(description="VoiceMem JSON-lines sidecar")
    parser.add_argument("--mode", default="text_mode")
    parser.add_argument("--memory-root", default=None)
    parser.add_argument("--user-id", default="voice_user")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default="VOICEMEM_API_KEY")
    parser.add_argument("--test-stub", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    factory = _stub_factory if args.test_stub else _voice_mem_factory(args)
    try:
        asyncio.run(VoiceMemSidecar(factory).run_stdio())
    except Exception as exc:
        print(f"VoiceMem sidecar failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
