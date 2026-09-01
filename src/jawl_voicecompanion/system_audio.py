"""Explicit Windows system-audio loopback capture boundary.

The optional backend is imported lazily because the main companion must remain
usable without audio capture dependencies. Raw PCM exists only in a bounded
in-memory queue and is handed to a caller-provided, non-durable consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, RLock, Thread, current_thread
from typing import Any, Callable
import importlib


class SystemAudioUnavailable(RuntimeError):
    """Raised when an optional Windows loopback backend cannot start."""


PcmConsumer = Callable[[bytes, int, int, str], None]


@dataclass(frozen=True)
class _Chunk:
    data: bytes
    sample_rate: int
    channels: int


class SystemAudioLoopback:
    """Capture the default Windows output through an injected loopback backend."""

    def __init__(
        self,
        consumer: PcmConsumer,
        *,
        backend: Any | None = None,
        session_id: str = "ambient-audio",
        sample_rate: int | None = None,
        frames_per_buffer: int = 1024,
        queue_size: int = 32,
        max_chunk_bytes: int = 256 * 1024,
    ) -> None:
        if not callable(consumer):
            raise TypeError("system audio consumer must be callable")
        self.consumer = consumer
        self.backend = backend
        self.session_id = str(session_id or "ambient-audio")[:120]
        self.requested_sample_rate = sample_rate
        self.frames_per_buffer = max(256, min(int(frames_per_buffer), 8192))
        self.queue_size = max(1, min(int(queue_size), 256))
        self.max_chunk_bytes = max(2048, min(int(max_chunk_bytes), 1024 * 1024))
        self._lock = RLock()
        self._stop = Event()
        self._queue: Queue[_Chunk] | None = None
        self._worker: Thread | None = None
        self._pa: Any | None = None
        self._loaded_backend: Any | None = None
        self._stream: Any | None = None
        self._backend_name = "not_loaded"
        self._device_name = ""
        self._sample_rate = 0
        self._channels = 0
        self._chunks = 0
        self._dropped_chunks = 0
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._stream is not None and self._worker is not None and self._worker.is_alive()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.running:
                return self.state()
            backend = self._load_backend()
            try:
                pa = backend.PyAudio()
                device = self._default_loopback(pa, backend)
                channels = max(1, min(int(device.get("maxInputChannels", 0)), 2))
                if not channels:
                    raise SystemAudioUnavailable("default loopback has no input channels")
                rate = self.requested_sample_rate or int(float(device.get("defaultSampleRate", 0)))
                if not 8000 <= rate <= 96000:
                    raise SystemAudioUnavailable("loopback sample rate is unsupported")
                queue: Queue[_Chunk] = Queue(maxsize=self.queue_size)
                self._stop.clear()
                self._queue = queue
                self._pa = pa
                self._loaded_backend = backend
                self._device_name = str(device.get("name") or "Windows loopback")[:160]
                self._sample_rate = rate
                self._channels = channels
                self._stream = pa.open(
                    format=backend.paInt16,
                    channels=channels,
                    rate=rate,
                    frames_per_buffer=self.frames_per_buffer,
                    input=True,
                    input_device_index=int(device["index"]),
                    stream_callback=self._callback,
                )
                self._worker = Thread(target=self._consume, name="system-audio-consumer", daemon=True)
                self._worker.start()
                self._stream.start_stream()
                self._last_error = None
                return self.state()
            except SystemAudioUnavailable:
                self._cleanup_backend()
                raise
            except Exception as exc:
                self._last_error = self._safe_error(exc)
                self._cleanup_backend()
                raise SystemAudioUnavailable("Windows system-audio loopback could not start") from exc

    def stop(self, timeout: float = 2.0) -> dict[str, Any]:
        with self._lock:
            stream = self._stream
            worker = self._worker
            self._stop.set()
        if stream is not None:
            for method in ("stop_stream", "close"):
                try:
                    getattr(stream, method)()
                except Exception:
                    pass
        if worker is not None and worker is not current_thread():
            worker.join(timeout=max(0.0, min(float(timeout), 10.0)))
        with self._lock:
            if self._queue is not None:
                while True:
                    try:
                        self._queue.get_nowait()
                    except Exception:
                        break
            self._cleanup_backend()
        return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": self.backend is not None or self._backend_name != "not_loaded",
                "backend": self._backend_name,
                "running": self._stream is not None and self._worker is not None and self._worker.is_alive(),
                "device": self._device_name or None,
                "sample_rate": self._sample_rate or None,
                "channels": self._channels or None,
                "queue_size": self.queue_size,
                "queue_depth": self._queue.qsize() if self._queue is not None else 0,
                "chunks": self._chunks,
                "dropped_chunks": self._dropped_chunks,
                "last_error": self._last_error,
                "raw_persisted": False,
            }

    def _load_backend(self) -> Any:
        if self.backend is not None:
            self._backend_name = "injected"
            return self.backend
        try:
            backend = importlib.import_module("pyaudiowpatch")
        except ImportError as exc:
            self._last_error = "pyaudiowpatch_not_installed"
            raise SystemAudioUnavailable(
                "install the optional pyaudiowpatch backend for Windows loopback"
            ) from exc
        self._backend_name = "pyaudiowpatch"
        return backend

    @staticmethod
    def _default_loopback(pa: Any, backend: Any) -> dict[str, Any]:
        try:
            wasapi = pa.get_host_api_info_by_type(backend.paWASAPI)
            default = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        except Exception as exc:
            raise SystemAudioUnavailable("WASAPI default output is unavailable") from exc
        if default.get("isLoopbackDevice"):
            return default
        default_name = str(default.get("name") or "")
        for loopback in pa.get_loopback_device_info_generator():
            if default_name and default_name in str(loopback.get("name") or ""):
                return loopback
        raise SystemAudioUnavailable("matching WASAPI loopback device was not found")

    def _callback(self, in_data: Any, _frame_count: int, _time_info: Any, _status: Any) -> tuple[Any, int]:
        data = bytes(in_data or b"")
        with self._lock:
            queue = self._queue
            channels = self._channels
            rate = self._sample_rate
        if not data or queue is None or self._stop.is_set():
            return (None, self._continue_flag())
        width = max(2, channels * 2)
        data = data[: self.max_chunk_bytes - (self.max_chunk_bytes % width)]
        if not data:
            return (None, self._continue_flag())
        try:
            queue.put_nowait(_Chunk(data, rate, channels))
            with self._lock:
                self._chunks += 1
        except Full:
            with self._lock:
                self._dropped_chunks += 1
        return (None, self._continue_flag())

    def _consume(self) -> None:
        while not self._stop.is_set():
            queue = self._queue
            if queue is None:
                return
            try:
                chunk = queue.get(timeout=0.1)
            except Exception:
                continue
            try:
                self.consumer(chunk.data, chunk.sample_rate, chunk.channels, self.session_id)
            except Exception as exc:
                with self._lock:
                    self._last_error = self._safe_error(exc)

    def _continue_flag(self) -> int:
        backend = self._loaded_backend or self.backend
        return int(getattr(backend, "paContinue", 0))

    def _cleanup_backend(self) -> None:
        self._stop.set()
        pa = self._pa
        self._stream = None
        self._worker = None
        self._queue = None
        self._pa = None
        self._loaded_backend = None
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {str(exc)[:160]}"[:200]


__all__ = ["PcmConsumer", "SystemAudioLoopback", "SystemAudioUnavailable"]
