"""Explicit file IPC sink compatible with JAWL's framework_api events."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


class JawlEventFileSink:
    """Write bounded proactive events into an explicitly supplied JAWL folder."""

    def __init__(self, event_dir: str | Path):
        self.event_dir = Path(event_dir).expanduser().resolve()

    def publish(self, intent: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(intent, dict) or intent.get("type") != "SPEAK_INTENT":
            raise ValueError("only SPEAK_INTENT events can cross the JAWL IPC sink")
        payload = intent.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("SPEAK_INTENT payload is required")
        event_id = str(intent.get("event_id") or uuid4())[:200]
        summary = str(payload.get("summary") or "").replace("\x00", "").strip()[:600]
        if not summary:
            raise ValueError("SPEAK_INTENT summary is required")
        event = {
            "message": "A bounded screen observation requires attention.",
            "payload": {
                "source": "jawl_voicecompanion",
                "event_type": "SCREEN_DELTA",
                "screen_summary": summary,
                "significance": max(0, min(3, int(payload.get("significance", 0)))),
                "intent_event_id": event_id,
                "observed_event_id": str(payload.get("observed_event_id") or "")[:200],
                "raw_frame_persisted": False,
            },
        }
        return self._write_event(event, event_id)

    def publish_chat(self, chat_event: dict[str, Any]) -> dict[str, Any]:
        """Write a bounded chat observation for JAWL's existing event intake."""
        if not isinstance(chat_event, dict) or chat_event.get("type") != "CHAT_MESSAGE":
            raise ValueError("only CHAT_MESSAGE events can cross the JAWL IPC sink")
        payload = chat_event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("CHAT_MESSAGE payload is required")
        text = str(payload.get("text") or "").replace("\x00", "").strip()[:500]
        if not text:
            raise ValueError("CHAT_MESSAGE text is required")
        event_id = str(chat_event.get("event_id") or uuid4())[:200]
        forwarded: dict[str, Any] = {
            "source": "jawl_voicecompanion",
            "event_type": "CHAT_MESSAGE",
            "chat_text": text,
            "observed_event_id": event_id,
        }
        for source, target, limit in (
            ("platform", "platform", 40),
            ("author", "author", 120),
            ("channel_id", "channel_id", 160),
            ("message_id", "message_id", 160),
        ):
            value = str(payload.get(source) or "").replace("\x00", "").strip()[:limit]
            if value:
                forwarded[target] = value
        return self._write_event(
            {
                "message": "A bounded stream-chat observation is available.",
                "payload": forwarded,
            },
            event_id,
        )

    def _write_event(self, event: dict[str, Any], event_id: str) -> dict[str, Any]:
        self.event_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".companion-", suffix=".tmp", dir=self.event_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(event, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            event_name = re.sub(r"[^A-Za-z0-9_-]", "", event_id)[:80]
            target = self.event_dir / f"{int(time.time())}_{event_name or uuid4().hex}.json"
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return {"status": "delivered", "event_id": event_id}
