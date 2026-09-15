"""Bounded NDJSON tailer: sensory worker events -> ambient memory.

The sensory worker (``scripts/sensory_worker.py``) writes typed observations
(screen frames, music state, gated speech transcripts) into an NDJSON file.
This ingestor tails that file with a persistent byte offset, maps the events
into the existing ambient-memory contract (visual/audio observations) and
never retains raw media. Music state is deduplicated so a steady track does
not flood the bounded buffer. Privacy filters stay in ``AmbientMemoryBuffer``
itself; this layer only bounds volume and cadence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event, RLock, Thread, current_thread
from typing import Any
from uuid import uuid4

from .event_log import log_event

_MUSIC_DEDUPE_S = 300.0
_MAX_CHUNK_BYTES = 4 * 1024 * 1024


class SensoryIngestor:
    """Tail one sensory NDJSON file and feed bounded ambient observations."""

    def __init__(
        self,
        memory: Any,
        path: str | Path,
        *,
        poll_interval_s: float = 2.0,
        max_events_per_poll: int = 50,
        music_dedupe_s: float = _MUSIC_DEDUPE_S,
        governor: Any | None = None,
        fusion: Any | None = None,
    ) -> None:
        self.memory = memory
        self.fusion = fusion
        self.path = Path(path).expanduser()
        self.poll_interval_s = max(0.5, min(float(poll_interval_s), 60.0))
        self.max_events_per_poll = max(1, min(int(max_events_per_poll), 500))
        self.music_dedupe_s = max(0.0, float(music_dedupe_s))
        self.governor = governor
        self._offset = 0
        self._counters: dict[str, int] = {
            "lines": 0, "visual": 0, "music": 0, "speech": 0,
            "ignored": 0, "errors": 0,
        }
        self._last_error = ""
        self._last_music: tuple[str, float] | None = None
        self._last_music_at = 0.0
        self._stop = Event()
        self._lock = RLock()
        self._thread: Thread | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = Thread(target=self._run, name="sensory-ingest", daemon=True)
                self._thread.start()
        return self.state()

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(0.0, min(float(timeout), 10.0)))
        with self._lock:
            if thread is None or not thread.is_alive():
                self._thread = None
        return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "enabled": True,
                "running": running,
                "path": str(self.path),
                "poll_interval_s": self.poll_interval_s,
                "offset": self._offset,
                "counters": dict(self._counters),
                "last_error": self._last_error[:240],
            }

    def poll_once(self, now: float | None = None) -> dict[str, Any]:
        """Read new complete lines once; safe to call from tests."""
        now = time.time() if now is None else float(now)
        try:
            size = self.path.stat().st_size
        except OSError:
            return {"status": "missing", "processed": 0}
        if size < self._offset:
            self._offset = 0
        if size == self._offset:
            return {"status": "idle", "processed": 0}
        with self.path.open("rb") as stream:
            stream.seek(self._offset)
            chunk = stream.read(_MAX_CHUNK_BYTES)
        lines = chunk.split(b"\n")
        if chunk.endswith(b"\n"):
            lines = lines[:-1]
            consumed = len(chunk)
        else:
            partial = lines.pop() if lines else b""
            consumed = len(chunk) - len(partial)
        self._offset += consumed
        processed = 0
        results: dict[str, int] = {}
        for raw in lines[: self.max_events_per_poll]:
            processed += 1
            try:
                event = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                self._counters["errors"] += 1
                continue
            if not isinstance(event, dict):
                self._counters["ignored"] += 1
                continue
            outcome = self._handle(event, now)
            results[outcome] = results.get(outcome, 0) + 1
        self._counters["lines"] += processed
        return {"status": "ok", "processed": processed, "results": results}

    def _handle(self, event: dict[str, Any], now: float) -> str:
        event_type = str(event.get("type") or "")
        try:
            if event_type == "screen_frame":
                return self._screen(event)
            if event_type == "music_state":
                return self._music(event, now)
            if event_type == "speech":
                return self._speech(event)
        except Exception as exc:  # noqa: BLE001 - one bad event must not stop the tail
            self._counters["errors"] += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:240]
            return "error"
        self._counters["ignored"] += 1
        return "ignored"

    def _screen(self, event: dict[str, Any]) -> str:
        if event.get("changed") is not True:
            self._counters["ignored"] += 1
            return "ignored"
        window = str(event.get("window") or "").strip()[:200]
        if not window:
            self._counters["ignored"] += 1
            return "ignored"
        result = self.memory.ingest_visual(
            f"Смена сцены в окне: {window}",
            confidence=0.5,
            source_app=window[:80],
            session_id="sensory-worker",
        )
        status = str(result.get("status") or "")
        if status == "retained":
            self._counters["visual"] += 1
            log_event("screen_change", window=window)
            if self.fusion is not None:
                self.fusion.note("window", window)
            return "visual"
        if status == "duplicate":
            return "duplicate"
        self._counters["ignored"] += 1
        return "ignored"

    def _music(self, event: dict[str, Any], now: float) -> str:
        key = str(event.get("key") or "").strip()[:40]
        try:
            bpm = round(float(event.get("bpm") or 0.0), 1)
        except (TypeError, ValueError):
            bpm = 0.0
        signature = (key, bpm)
        if self._last_music == signature and now - self._last_music_at < self.music_dedupe_s:
            self._counters["ignored"] += 1
            return "ignored"
        parts = [part for part in (key, f"{bpm:g} BPM" if bpm else "") if part]
        text = "Музыка: " + ", ".join(parts) if parts else "Музыка играет"
        tags = [part for part in (key, f"{bpm:g} bpm" if bpm else "") if part][:8]
        confidence = 0.5
        try:
            confidence = float(event.get("key_confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        result = self.memory.ingest({
            "schema_version": 1,
            "event_id": str(uuid4()),
            "session_id": "sensory-worker",
            "type": "AMBIENT_AUDIO_OBSERVATION",
            "payload": {
                "text": text, "confidence": confidence,
                "audio_kind": "music", "tags": tags,
            },
        }, now=now)
        if str(result.get("status")) == "retained":
            self._last_music = signature
            self._last_music_at = now
            self._counters["music"] += 1
            log_event("system_music", detail=text)
            if self.fusion is not None:
                self.fusion.note("music", text)
            return "music"
        if str(result.get("status")) == "duplicate":
            return "duplicate"
        self._counters["ignored"] += 1
        return "ignored"

    def _speech(self, event: dict[str, Any]) -> str:
        text = str(event.get("text") or "").strip()[:1200]
        if not text:
            self._counters["ignored"] += 1
            return "ignored"
        result = self.memory.ingest_system_audio(
            text, confidence=0.6, session_id="sensory-worker",
        )
        if str(result.get("status")) == "retained":
            self._counters["speech"] += 1
            log_event("system_speech", text=text)
            if self.fusion is not None:
                self.fusion.note("speech", text)
            return "speech"
        if str(result.get("status")) == "duplicate":
            return "duplicate"
        self._counters["ignored"] += 1
        return "ignored"

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval_s):
            if self.governor is not None and not self.governor.try_acquire(
                "ambient", background=True
            ):
                continue
            try:
                self.poll_once()
            except Exception as exc:  # keep the tail thread alive
                self._last_error = f"{type(exc).__name__}: {exc}"[:240]
                self._counters["errors"] += 1
            finally:
                if self.governor is not None:
                    self.governor.release("ambient")


__all__ = ["SensoryIngestor"]
