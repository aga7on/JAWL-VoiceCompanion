"""Bounded conversation history persistence for the local control plane."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class ConversationHistory:
    """Append dialog turns as bounded JSONL and recover the last ones.

    Unlike the in-memory ``gateway._turns``, this survives companion restarts
    and page reloads, so the panel can render the conversation log like the
    original JAWL console does.
    """

    _MAX_BYTES = 4_000_000
    _MAX_TURNS = 400

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self._lock = Lock()

    def append(self, turn: dict[str, Any]) -> None:
        if not isinstance(turn, dict):
            return
        safe = {
            "created_at": str(turn.get("created_at", ""))[:80],
            "session_id": str(turn.get("session_id", ""))[:200],
            "correlation_id": str(turn.get("correlation_id", ""))[:128],
            "user": str(turn.get("user", ""))[:12_000],
            "response": turn.get("response"),
        }
        line = (json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
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

    def turns(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), self._MAX_TURNS))
        try:
            raw = self.path.read_bytes()[-self._MAX_BYTES:]
        except OSError:
            return []
        result: list[dict[str, Any]] = []
        for line in raw.splitlines()[-bounded:]:
            try:
                turn = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(turn, dict) and isinstance(turn.get("response"), dict):
                result.append(turn)
        return result[-bounded:]