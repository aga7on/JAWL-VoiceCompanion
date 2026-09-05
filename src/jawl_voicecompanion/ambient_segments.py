"""Bounded, non-blocking segment rotation for ambient PCM capture."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True)
class AmbientSegment:
    """One transient, correlated PCM segment ready for an ambient worker."""

    segment_id: str
    session_id: str
    generation: str
    sequence: int
    pcm16: bytes
    sample_rate: int
    channels: int
    started_at: float
    ended_at: float


@dataclass(frozen=True)
class _Chunk:
    data: bytes
    sample_rate: int
    channels: int


class AmbientSegmenter:
    """Rotate PCM on a bounded queue without blocking the capture callback."""

    def __init__(
        self,
        on_segment: Callable[[AmbientSegment], None],
        *,
        queue_size: int = 32,
        max_chunk_bytes: int = 48 * 1024,
        max_queue_bytes: int | None = None,
        max_segment_bytes: int = 512 * 1024,
        max_segment_seconds: float = 15.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not callable(on_segment):
            raise TypeError("ambient segment callback must be callable")
        self.on_segment = on_segment
        self.queue_size = max(1, min(int(queue_size), 256))
        self.max_chunk_bytes = max(2, min(int(max_chunk_bytes), 256 * 1024)) & ~1
        configured_queue_bytes = self.max_chunk_bytes * self.queue_size if max_queue_bytes is None else int(max_queue_bytes)
        self.max_queue_bytes = max(self.max_chunk_bytes, min(configured_queue_bytes, 16 * 1024 * 1024)) & ~1
        self.max_segment_bytes = max(4 * 1024, min(int(max_segment_bytes), 4 * 1024 * 1024)) & ~1
        self.max_segment_seconds = max(0.25, min(float(max_segment_seconds), 120.0))
        self._clock = clock
        self._lock = RLock()
        self._stop = Event()
        self._cancel = Event()
        self._queue: Queue[_Chunk] | None = None
        self._worker: Thread | None = None
        self._session_id: str | None = None
        self._generation: str | None = None
        self._queued_bytes = 0
        self._accepted_chunks = 0
        self._dropped_chunks = 0
        self._dropped_bytes = 0
        self._cancelled_chunks = 0
        self._cancelled_bytes = 0
        self._rejected_chunks = 0
        self._rejected_bytes = 0
        self._emitted_segments = 0
        self._callback_errors = 0
        self._last_error: str | None = None

    def start(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            previous = self._worker
            stopping = self._stop.is_set()
        if previous is not None and previous.is_alive():
            if not stopping:
                return self.state()
            previous.join(timeout=0.5)
            if previous.is_alive():
                return self.state()
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return self.state()
            self._queue = Queue(maxsize=self.queue_size)
            self._queued_bytes = 0
            self._stop.clear()
            self._cancel.clear()
            self._session_id = str(session_id or "ambient-audio")[:120]
            self._generation = uuid4().hex
            self._last_error = None
            queue = self._queue
            generation = self._generation
            worker = Thread(
                target=self._run,
                args=(queue, generation),
                name="ambient-segmenter",
                daemon=True,
            )
            self._worker = worker
            worker.start()
            return self.state()

    def submit(self, pcm16: bytes, sample_rate: int, channels: int) -> dict[str, Any]:
        if not isinstance(pcm16, bytes) or not pcm16:
            self._reject(len(pcm16) if isinstance(pcm16, bytes) else 0, "ambient segment input must be non-empty PCM16")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 96000:
            self._reject(len(pcm16), "ambient segment sample rate is unsupported")
        if isinstance(channels, bool) or not isinstance(channels, int) or channels not in (1, 2):
            self._reject(len(pcm16), "ambient segment channels must be 1 or 2")
        frame_bytes = channels * 2
        if len(pcm16) % frame_bytes:
            self._reject(len(pcm16), "ambient segment input is not whole PCM frames")
        if len(pcm16) > self.max_chunk_bytes:
            self._reject(len(pcm16), "ambient segment chunk exceeds byte limit")
        chunk = _Chunk(bytes(pcm16), sample_rate, channels)
        with self._lock:
            queue = self._queue
            if queue is None or self._worker is None or not self._worker.is_alive() or self._stop.is_set():
                return {"status": "inactive", "reason": "segmenter_not_running"}
            if self._queued_bytes + len(chunk.data) > self.max_queue_bytes:
                self._dropped_chunks += 1
                self._dropped_bytes += len(chunk.data)
                return {
                    "status": "dropped",
                    "reason": "ambient_segment_queue_bytes_full",
                    "queue_depth": queue.qsize(),
                    "queue_bytes": self._queued_bytes,
                }
            try:
                queue.put_nowait(chunk)
            except Full:
                self._dropped_chunks += 1
                self._dropped_bytes += len(chunk.data)
                return {
                    "status": "dropped",
                    "reason": "ambient_segment_queue_full",
                    "queue_depth": queue.qsize(),
                }
            self._queued_bytes += len(chunk.data)
            self._accepted_chunks += 1
            return {"status": "accepted", "queue_depth": queue.qsize()}

    def stop(self, *, flush: bool = True, timeout: float = 2.0) -> dict[str, Any]:
        with self._lock:
            queue = self._queue
            worker = self._worker
            self._stop.set()
            if not flush:
                self._cancel.set()
                self._clear_queue(queue)
        if worker is not None and worker is not current_thread():
            worker.join(timeout=max(0.0, min(float(timeout), 10.0)))
        with self._lock:
            running = worker is not None and worker.is_alive()
            if not running and self._queue is queue:
                self._queue = None
                self._worker = None
            return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            queue = self._queue
            worker = self._worker
            return {
                "running": worker is not None and worker.is_alive(),
                "accepting": bool(
                    queue is not None
                    and worker is not None
                    and worker.is_alive()
                    and not self._stop.is_set()
                ),
                "session_id": self._session_id,
                "generation": self._generation,
                "queue_size": self.queue_size,
                "queue_depth": queue.qsize() if queue is not None else 0,
                "queue_bytes": self._queued_bytes,
                "accepted_chunks": self._accepted_chunks,
                "dropped_chunks": self._dropped_chunks,
                "dropped_bytes": self._dropped_bytes,
                "cancelled_chunks": self._cancelled_chunks,
                "cancelled_bytes": self._cancelled_bytes,
                "rejected_chunks": self._rejected_chunks,
                "rejected_bytes": self._rejected_bytes,
                "emitted_segments": self._emitted_segments,
                "callback_errors": self._callback_errors,
                "last_error": self._last_error,
                "max_segment_bytes": self.max_segment_bytes,
                "max_segment_seconds": self.max_segment_seconds,
                "max_chunk_bytes": self.max_chunk_bytes,
                "max_queue_bytes": self.max_queue_bytes,
            }

    def _run(self, queue: Queue[_Chunk], generation: str) -> None:
        buffer = bytearray()
        sample_rate = 0
        channels = 0
        started_at = 0.0
        sequence = 0
        try:
            while True:
                if self._cancel.is_set():
                    break
                try:
                    chunk = queue.get(timeout=0.05)
                except Empty:
                    if buffer and self._clock() - started_at >= self.max_segment_seconds:
                        sequence = self._emit(
                            buffer,
                            sample_rate,
                            channels,
                            generation,
                            sequence,
                            started_at,
                            self._clock(),
                        )
                        buffer.clear()
                    if self._stop.is_set() and queue.empty():
                        break
                    continue
                try:
                    with self._lock:
                        self._queued_bytes = max(0, self._queued_bytes - len(chunk.data))
                    if self._cancel.is_set():
                        self._record_cancelled(len(chunk.data))
                        continue
                    if not buffer:
                        sample_rate, channels = chunk.sample_rate, chunk.channels
                        started_at = self._clock()
                    elif (sample_rate, channels) != (chunk.sample_rate, chunk.channels):
                        sequence = self._emit(
                            buffer,
                            sample_rate,
                            channels,
                            generation,
                            sequence,
                            started_at,
                            self._clock(),
                        )
                        buffer.clear()
                        sample_rate, channels = chunk.sample_rate, chunk.channels
                        started_at = self._clock()
                    offset = 0
                    while offset < len(chunk.data):
                        room = self.max_segment_bytes - len(buffer)
                        take = min(room, len(chunk.data) - offset)
                        take -= take % max(2, channels * 2)
                        if take <= 0:
                            sequence = self._emit(
                                buffer,
                                sample_rate,
                                channels,
                                generation,
                                sequence,
                                started_at,
                                self._clock(),
                            )
                            buffer.clear()
                            started_at = self._clock()
                            continue
                        buffer.extend(chunk.data[offset : offset + take])
                        offset += take
                        now = self._clock()
                        audio_seconds = len(buffer) / max(1, sample_rate * channels * 2)
                        if (
                            len(buffer) >= self.max_segment_bytes
                            or now - started_at >= self.max_segment_seconds
                            or audio_seconds >= self.max_segment_seconds
                        ):
                            sequence = self._emit(
                                buffer,
                                sample_rate,
                                channels,
                                generation,
                                sequence,
                                started_at,
                                now,
                            )
                            buffer.clear()
                            started_at = now
                finally:
                    queue.task_done()
                if self._stop.is_set() and queue.empty():
                    break
            if buffer:
                if self._cancel.is_set():
                    self._record_cancelled(len(buffer))
                else:
                    self._emit(
                        buffer,
                        sample_rate,
                        channels,
                        generation,
                        sequence,
                        started_at,
                        self._clock(),
                    )
        except Exception as exc:
            with self._lock:
                self._last_error = self._safe_error(exc)
        finally:
            with self._lock:
                if self._worker is current_thread():
                    self._worker = None

    def _emit(
        self,
        buffer: bytearray,
        sample_rate: int,
        channels: int,
        generation: str,
        sequence: int,
        started_at: float,
        ended_at: float,
    ) -> int:
        if not buffer:
            return sequence
        segment = AmbientSegment(
            segment_id=f"ambient-segment:{uuid4().hex}",
            session_id=self._session_id or "ambient-audio",
            generation=generation,
            sequence=sequence,
            pcm16=bytes(buffer),
            sample_rate=sample_rate,
            channels=channels,
            started_at=started_at,
            ended_at=ended_at,
        )
        with self._lock:
            self._emitted_segments += 1
        try:
            self.on_segment(segment)
        except Exception as exc:
            with self._lock:
                self._callback_errors += 1
                self._last_error = self._safe_error(exc)
        return sequence + 1

    def _clear_queue(self, queue: Queue[_Chunk] | None) -> None:
        if queue is None:
            return
        while True:
            try:
                chunk = queue.get_nowait()
                with self._lock:
                    self._queued_bytes = max(0, self._queued_bytes - len(chunk.data))
                    self._record_cancelled(len(chunk.data))
                queue.task_done()
            except Empty:
                return

    def _record_cancelled(self, size: int) -> None:
        with self._lock:
            self._cancelled_chunks += 1
            self._cancelled_bytes += max(0, int(size))

    def _reject(self, size: int, reason: str) -> None:
        with self._lock:
            self._rejected_chunks += 1
            self._rejected_bytes += max(0, int(size))
        raise ValueError(reason)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {str(exc)[:160]}"[:200]


__all__ = ["AmbientSegment", "AmbientSegmenter"]
