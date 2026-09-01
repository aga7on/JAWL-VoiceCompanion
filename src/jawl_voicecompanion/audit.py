"""Bounded metadata-only audit persistence for the local control plane."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class AuditLog:
    """Append policy metadata as bounded JSONL and recover its last events."""

    _MAX_BYTES = 1_000_000
    _MAX_EVENTS = 500
    _SAFE_PAYLOAD_FIELDS = frozenset({
        "from", "to", "actor", "enabled", "tools", "risks", "request_id",
        "tool", "risk", "status", "effective_level", "approval_id",
    })

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self._lock = Lock()

    def append(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        safe_event = {
            "created_at": str(event.get("created_at", ""))[:80],
            "type": str(event.get("type", "unknown"))[:80],
            "payload": {key: payload[key] for key in self._SAFE_PAYLOAD_FIELDS if key in payload},
        }
        line = (json.dumps(safe_event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > self._MAX_BYTES:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size + len(line) > self._MAX_BYTES:
                existing = self.path.read_bytes()[-(self._MAX_BYTES - len(line)):]
                existing = existing[existing.find(b"\n") + 1:] if b"\n" in existing else b""
                self.path.write_bytes(existing + line)
            else:
                with self.path.open("ab") as stream:
                    stream.write(line)

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), self._MAX_EVENTS))
        try:
            raw = self.path.read_bytes()[-self._MAX_BYTES:]
        except OSError:
            return []
        result = []
        for line in raw.splitlines()[-bounded:]:
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                result.append(event)
        return result[-bounded:]
