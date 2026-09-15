"""Bounded NDJSON event log for live ASR / sensory / screen visibility.

JAWL deliberately never logs inbound message text, so this companion-side log
is the operator's window into what actually arrives: final microphone
transcripts, sensory worker observations (screen changes, music, system
speech) and screen-delta intents sent to JAWL. The file is truncated once it
grows past a small bound and never blocks any pipeline.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "runtime" / "voice-events.ndjson"
_MAX_BYTES = 2_000_000


class _EventLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def append(self, kind: str, **fields: Any) -> None:
        record: dict[str, Any] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": str(kind)[:60]}
        for key, value in fields.items():
            if isinstance(value, str):
                record[str(key)[:40]] = value[:600]
            elif isinstance(value, (int, float, bool)) or value is None:
                record[str(key)[:40]] = value
            else:
                record[str(key)[:40]] = str(value)[:600]
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > _MAX_BYTES:
                    self.path.write_text("", encoding="utf-8")
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError:
                pass


_log = _EventLog(os.environ.get("JAWL_VOICE_EVENT_LOG") or _DEFAULT_PATH)


def log_event(kind: str, **fields: Any) -> None:
    _log.append(kind, **fields)


def event_log_path() -> str:
    return str(_log.path)
