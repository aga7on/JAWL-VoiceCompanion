"""Millisecond trace of one full turn: button press to audible answer.

Purpose
-------
The owner's voice turns take 32-77 s to first audio while the first model token
arrives in ~1.6 s. The gap is not inference. This module produces the evidence
needed to attribute it: one append-only JSONL trace per turn, written by the
browser client and by the server, sharing one correlation id.

Design constraints
------------------
* Observation only. Nothing here changes routing or timing; a trace that
  perturbed the measurement would be worthless.
* Append-only and crash-safe: each mark is a complete JSON line, flushed as it
  is written, so a stalled turn still leaves everything recorded up to the stall.
* Bounded: a trace directory keeps a fixed number of recent files.

Where marks come from
---------------------
Browser side (authoritative for user-perceived latency) emits into
``/api/trace``. Server side writes the same file directly. Both use a monotonic
``performance.now()``-style clock plus a wall-clock anchor, so cross-process
ordering is possible without trusting clocks to be identical.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

_MAX_TRACES = 40
STAGE_USER_SPEECH_END = "t_user_speech_end"
STAGE_VAD_ENDPOINT = "t_vad_endpoint"
STAGE_ASR_FINAL = "t_asr_final"
STAGE_LLM_REQUEST = "t_llm_request"
STAGE_LLM_FIRST_TOKEN = "t_llm_first_token"
STAGE_LLM_FIRST_SENTENCE = "t_llm_first_sentence"
STAGE_TTS_REQUEST = "t_tts_request"
STAGE_TTS_FIRST_PCM = "t_tts_first_pcm"
STAGE_AUDIO_ENQUEUED = "t_audio_enqueued"
STAGE_AUDIO_PLAYBACK_START = "t_audio_playback_start"
STAGE_AUDIO_PLAYBACK_END = "t_audio_playback_end"
STAGE_BARGE_IN_DETECTED = "t_barge_in_detected"
STAGE_AUDIO_STOPPED = "t_audio_stopped"

ALL_STAGES = (
    STAGE_USER_SPEECH_END,
    STAGE_VAD_ENDPOINT,
    STAGE_ASR_FINAL,
    STAGE_LLM_REQUEST,
    STAGE_LLM_FIRST_TOKEN,
    STAGE_LLM_FIRST_SENTENCE,
    STAGE_TTS_REQUEST,
    STAGE_TTS_FIRST_PCM,
    STAGE_AUDIO_ENQUEUED,
    STAGE_AUDIO_PLAYBACK_START,
    STAGE_AUDIO_PLAYBACK_END,
    STAGE_BARGE_IN_DETECTED,
    STAGE_AUDIO_STOPPED,
)


def compute_turn_kpis(records: list[dict[str, Any]]) -> dict[str, float | None]:
    """Calculate key latency KPIs from recorded trace marks."""
    if not records:
        return {
            "audible_latency_s": None,
            "meaningful_latency_s": None,
            "barge_in_stop_duration_s": None,
            "first_sentence_latency_s": None,
        }

    start_ts: float | None = None
    for r in records:
        if r.get("stage") == STAGE_USER_SPEECH_END:
            start_ts = r.get("wall_ts")
            break
        if start_ts is None and r.get("stage") == STAGE_VAD_ENDPOINT:
            start_ts = r.get("wall_ts")

    audible_latency_s: float | None = None
    meaningful_latency_s: float | None = None
    first_sentence_latency_s: float | None = None

    if start_ts is not None:
        for r in records:
            if r.get("stage") == STAGE_LLM_FIRST_SENTENCE and first_sentence_latency_s is None:
                first_sentence_latency_s = round(r["wall_ts"] - start_ts, 4)
            if r.get("stage") == STAGE_AUDIO_PLAYBACK_START:
                if audible_latency_s is None:
                    audible_latency_s = round(r["wall_ts"] - start_ts, 4)
                detail = r.get("detail")
                is_fast_lane = isinstance(detail, dict) and (
                    detail.get("lane") == "fast" or detail.get("is_preface") is True
                )
                if not is_fast_lane and meaningful_latency_s is None:
                    meaningful_latency_s = round(r["wall_ts"] - start_ts, 4)

    barge_in_stop_duration_s: float | None = None
    barge_in_ts: float | None = None
    for r in records:
        if r.get("stage") == STAGE_BARGE_IN_DETECTED:
            barge_in_ts = r.get("wall_ts")
            break
    if barge_in_ts is not None:
        for r in records:
            if r.get("stage") == STAGE_AUDIO_STOPPED and r.get("wall_ts", 0.0) >= barge_in_ts:
                barge_in_stop_duration_s = round(r["wall_ts"] - barge_in_ts, 4)
                break

    return {
        "audible_latency_s": audible_latency_s,
        "meaningful_latency_s": meaningful_latency_s,
        "barge_in_stop_duration_s": barge_in_stop_duration_s,
        "first_sentence_latency_s": first_sentence_latency_s,
    }
class TurnTracer:
    """Thread-safe append-only trace writer for one trace id at a time."""

    def __init__(self, directory: Path, *, max_traces: int = _MAX_TRACES) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._max_traces = max(4, int(max_traces))
        self._order: deque[str] = deque()
        self._starts: dict[str, float] = {}
        self._handles: dict[str, Any] = {}

    # ---------------------------------------------------------------- writing

    def _handle(self, trace_id: str):
        handle = self._handles.get(trace_id)
        if handle is not None:
            return handle
        path = self.directory / f"{trace_id}.jsonl"
        handle = path.open("a", encoding="utf-8")
        self._handles[trace_id] = handle
        self._order.append(trace_id)
        while len(self._order) > self._max_traces:
            stale = self._order.popleft()
            self._close_locked(stale)
            try:
                (self.directory / f"{stale}.jsonl").unlink()
            except OSError:
                pass
        return handle

    def _close_locked(self, trace_id: str) -> None:
        handle = self._handles.pop(trace_id, None)
        self._starts.pop(trace_id, None)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def mark(
        self,
        trace_id: str,
        stage: str,
        *,
        detail: Any = None,
        wall_ts: float | None = None,
    ) -> dict[str, Any]:
        """Append one stage mark. Returns the record that was written."""
        clean_id = str(trace_id or "").strip()[:80]
        if not clean_id:
            raise ValueError("trace_id is required")
        now = time.time()
        with self._lock:
            started = self._starts.get(clean_id)
            if started is None:
                started = self._starts[clean_id] = now
            record = {
                "trace_id": clean_id,
                "stage": str(stage)[:80],
                "wall_ts": round(wall_ts if wall_ts is not None else now, 6),
                "server_ts": round(now, 6),
                "since_start_s": round(now - started, 4),
                "detail": detail,
            }
            handle = self._handle(clean_id)
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            return record

    # ---------------------------------------------------------------- reading

    def read(self, trace_id: str) -> list[dict[str, Any]]:
        path = self.directory / f"{str(trace_id)[:80]}.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def summary(self, trace_id: str) -> dict[str, Any]:
        records = self.read(trace_id)
        if not records:
            return {"trace_id": trace_id, "marks": 0}
        base = min(r["wall_ts"] for r in records)
        gaps = []
        ordered = sorted(records, key=lambda r: r["wall_ts"])
        for previous, current in zip(ordered, ordered[1:]):
            gaps.append(
                {
                    "from": previous["stage"],
                    "to": current["stage"],
                    "gap_ms": round((current["wall_ts"] - previous["wall_ts"]) * 1000.0, 1),
                }
            )
        biggest = max(gaps, key=lambda g: g["gap_ms"]) if gaps else None
        return {
            "trace_id": trace_id,
            "marks": len(records),
            "duration_s": round(ordered[-1]["wall_ts"] - base, 3),
            "stages": [
                {
                    "stage": r["stage"],
                    "at_s": round(r["wall_ts"] - base, 4),
                    "detail": r["detail"],
                }
                for r in ordered
            ],
            "gaps": gaps,
            "largest_gap": biggest,
        }

    def audible_latency(self, trace_id: str) -> float | None:
        return compute_turn_kpis(self.read(trace_id))["audible_latency_s"]

    def meaningful_latency(self, trace_id: str) -> float | None:
        return compute_turn_kpis(self.read(trace_id))["meaningful_latency_s"]

    def barge_in_stop_duration(self, trace_id: str) -> float | None:
        return compute_turn_kpis(self.read(trace_id))["barge_in_stop_duration_s"]
    def close(self) -> None:
        with self._lock:
            for trace_id in list(self._handles):
                self._close_locked(trace_id)
            self._order.clear()


_TRACER: TurnTracer | None = None
_TRACER_LOCK = threading.Lock()


def configure(directory: Path) -> TurnTracer:
    """Install the process-wide tracer (idempotent)."""
    global _TRACER
    with _TRACER_LOCK:
        if _TRACER is None:
            _TRACER = TurnTracer(directory)
        return _TRACER


def current() -> TurnTracer | None:
    return _TRACER


def mark(trace_id: str, stage: str, *, detail: Any = None, wall_ts: float | None = None) -> None:
    """Mark a stage when tracing is configured; a no-op otherwise."""
    tracer = _TRACER
    if tracer is None:
        return
    try:
        tracer.mark(trace_id, stage, detail=detail, wall_ts=wall_ts)
    except Exception:  # noqa: BLE001 - tracing must never break a live turn
        pass
def audible_latency(trace_id: str) -> float | None:
    return _TRACER.audible_latency(trace_id) if _TRACER is not None else None


def meaningful_latency(trace_id: str) -> float | None:
    return _TRACER.meaningful_latency(trace_id) if _TRACER is not None else None


def barge_in_stop_duration(trace_id: str) -> float | None:
    return _TRACER.barge_in_stop_duration(trace_id) if _TRACER is not None else None