"""Explicit Windows system-audio loopback capture boundary.

The optional backend is imported lazily because the main companion must remain
usable without audio capture dependencies. Raw PCM exists only in a bounded
in-memory queue and is handed to a caller-provided, non-durable consumer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, RLock, Thread, current_thread
from typing import Any, Callable
import importlib
import math
import time


class SystemAudioUnavailable(RuntimeError):
    """Raised when an optional Windows loopback backend cannot start."""


PcmConsumer = Callable[[bytes, int, int, str], None]


@dataclass(frozen=True)
class _Chunk:
    data: bytes
    sample_rate: int
    channels: int
    captured_monotonic: float


class SystemAudioLoopback:
    """Capture the default or explicitly named Windows output via loopback."""

    def __init__(
        self,
        consumer: PcmConsumer,
        *,
        backend: Any | None = None,
        session_id: str = "ambient-audio",
        output_device_name: str | None = None,
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
        self.output_device_name = str(output_device_name or "").strip()[:160] or None
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
        self._device_index: int | None = None
        self._host_api_index: int | None = None
        self._sample_rate = 0
        self._channels = 0
        self._chunks = 0
        self._last_chunk_monotonic: float | None = None
        self._last_consumer_chunk_monotonic: float | None = None
        self._consumer_chunks = 0
        self._last_chunk_peak_abs: int | None = None
        self._last_chunk_rms: float | None = None
        # Bound scalar telemetry even if a backend delivers callbacks unusually fast.
        # 512 entries cover >1.3 s at the fastest supported 96 kHz stereo /
        # 256-frame callback cadence (~375 chunks/s), while remaining scalar-only.
        self._signal_window: deque[tuple[float, int, int, int, float]] = deque(maxlen=512)
        self._queue_high_water = 0
        self._last_consumer_lag_ms: float | None = None
        self._dropped_chunks = 0
        self._last_drop_monotonic: float | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._stream is not None and self._worker is not None and self._worker.is_alive()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                if self._stop.is_set():
                    raise SystemAudioUnavailable("system-audio consumer is still stopping")
                return self.state()
            backend = self._load_backend()
            try:
                pa = backend.PyAudio()
                device = self._default_loopback(pa, backend, self.output_device_name)
                channels = min(int(device.get("maxInputChannels", 0)), 2)
                if not channels:
                    raise SystemAudioUnavailable("selected loopback has no input channels")
                rate = self.requested_sample_rate or int(float(device.get("defaultSampleRate", 0)))
                if not 8000 <= rate <= 96000:
                    raise SystemAudioUnavailable("loopback sample rate is unsupported")
                queue: Queue[_Chunk] = Queue(maxsize=self.queue_size)
                self._stop.clear()
                self._queue = queue
                self._signal_window.clear()
                self._last_chunk_monotonic = None
                self._last_consumer_chunk_monotonic = None
                self._last_chunk_peak_abs = None
                self._last_chunk_rms = None
                self._last_consumer_lag_ms = None
                self._last_drop_monotonic = None
                self._pa = pa
                self._loaded_backend = backend
                self._device_name = str(device.get("name") or "Windows loopback")[:160]
                device_index = device.get("index")
                self._device_index = int(device_index) if device_index is not None else None
                host_api_index = device.get("hostApi")
                self._host_api_index = int(host_api_index) if host_api_index is not None else None
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
        if worker is not None and worker.is_alive():
            # Keep worker/queue/backend ownership intact. A caller may retry stop;
            # start() must not replace resources underneath this live consumer.
            return self.state()
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
            now = time.monotonic()
            while self._signal_window and now - self._signal_window[0][0] > 1.0:
                self._signal_window.popleft()
            window_squares = sum(item[1] for item in self._signal_window)
            window_sample_count = sum(item[2] for item in self._signal_window)
            window_peak_abs = max((item[3] for item in self._signal_window), default=0)
            window_wall_span_ms = (
                max(0.0, (self._signal_window[-1][0] - self._signal_window[0][0]) * 1000.0
                    + self._signal_window[-1][4] * 1000.0)
                if self._signal_window else 0.0
            )
            window_duration_ms = (
                window_sample_count / max(1, self._sample_rate * self._channels) * 1000.0
                if self._sample_rate and self._channels
                else 0.0
            )
            last_chunk_age_ms = (
                max(0.0, now - self._last_chunk_monotonic) * 1000.0
                if self._last_chunk_monotonic is not None else None
            )
            last_consumer_age_ms = (
                max(0.0, now - self._last_consumer_chunk_monotonic) * 1000.0
                if self._last_consumer_chunk_monotonic is not None else None
            )
            signal_window_valid = (
                window_duration_ms >= 800.0
                and window_wall_span_ms >= 800.0
                and (self._last_drop_monotonic is None or now - self._last_drop_monotonic > 1.0)
                and last_chunk_age_ms is not None and last_chunk_age_ms <= 1000.0
                and last_consumer_age_ms is not None and last_consumer_age_ms <= 1000.0
                and self._last_consumer_lag_ms is not None and self._last_consumer_lag_ms <= 1000.0
            )
            signal_state = (
                "unknown" if not signal_window_valid
                else "digital_silence" if window_peak_abs == 0
                else "nonzero_pcm_unclassified"
            )
            return {
                "configured": self.backend is not None or self._backend_name != "not_loaded",
                "backend": self._backend_name,
                "running": self._stream is not None and self._worker is not None and self._worker.is_alive(),
                "device": self._device_name or None,
                "device_index": self._device_index,
                "host_api_index": self._host_api_index,
                "sample_rate": self._sample_rate or None,
                "channels": self._channels or None,
                "queue_size": self.queue_size,
                "queue_depth": self._queue.qsize() if self._queue is not None else 0,
                "chunks": self._chunks,
                "consumer_chunks": self._consumer_chunks,
                "last_chunk_age_ms": (
                    round(max(0.0, time.monotonic() - self._last_chunk_monotonic) * 1000.0, 1)
                    if self._last_chunk_monotonic is not None
                    else None
                ),
                "last_consumer_chunk_age_ms": (
                    round(max(0.0, time.monotonic() - self._last_consumer_chunk_monotonic) * 1000.0, 1)
                    if self._last_consumer_chunk_monotonic is not None
                    else None
                ),
                "last_chunk_peak_abs": self._last_chunk_peak_abs,
                "last_chunk_rms": round(self._last_chunk_rms, 2) if self._last_chunk_rms is not None else None,
                "signal_window_state": signal_state,
                "signal_window_duration_ms": round(window_duration_ms, 1),
                "signal_window_wall_span_ms": round(window_wall_span_ms, 1),
                "signal_window_peak_abs": window_peak_abs if signal_window_valid else None,
                "signal_window_rms": (
                    round(math.sqrt(window_squares / window_sample_count), 2)
                    if signal_window_valid and window_sample_count else None
                ),
                "last_consumer_lag_ms": (
                    round(self._last_consumer_lag_ms, 1)
                    if self._last_consumer_lag_ms is not None
                    else None
                ),
                "queue_high_water": self._queue_high_water,
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
    def _default_loopback(
        pa: Any, backend: Any, output_device_name: str | None = None
    ) -> dict[str, Any]:
        if output_device_name:
            return SystemAudioLoopback._named_loopback(pa, output_device_name)
        try:
            wasapi = pa.get_host_api_info_by_type(backend.paWASAPI)
            default = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        except Exception as exc:
            raise SystemAudioUnavailable("WASAPI default output is unavailable") from exc
        if default.get("isLoopbackDevice"):
            return default
        default_name = str(default.get("name") or "")
        if not default_name:
            raise SystemAudioUnavailable("WASAPI default output has no device name")
        candidates = [
            item for item in pa.get_loopback_device_info_generator()
            if item.get("isLoopbackDevice")
            and int(item.get("maxInputChannels", 0)) > 0
        ]
        folded_default = " ".join(default_name.casefold().split())
        exact = [
            item for item in candidates
            if " ".join(str(item.get("name") or "").casefold().split())
            == folded_default + " [loopback]"
        ]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise SystemAudioUnavailable("WASAPI default output loopback is ambiguous")
        normalized = [
            item for item in candidates
            if " ".join(str(item.get("name") or "").casefold().split())
            .removesuffix(" [loopback]") == folded_default
        ]
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) > 1:
            raise SystemAudioUnavailable("WASAPI default output loopback is ambiguous")
        partial = [
            item for item in candidates
            if folded_default in " ".join(str(item.get("name") or "").casefold().split())
        ]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise SystemAudioUnavailable("WASAPI default output loopback is ambiguous")
        raise SystemAudioUnavailable("matching WASAPI loopback device was not found")

    @staticmethod
    def _named_loopback(pa: Any, output_device_name: str) -> dict[str, Any]:
        """Resolve a configured render endpoint without falling back to default."""
        requested = " ".join(str(output_device_name).casefold().split())
        candidates = [
            item for item in pa.get_loopback_device_info_generator()
            if item.get("isLoopbackDevice")
            and int(item.get("maxInputChannels", 0)) > 0
        ]
        exact = []
        for item in candidates:
            candidate_name = " ".join(str(item.get("name") or "").casefold().split())
            if candidate_name == requested or candidate_name.removesuffix(" [loopback]") == requested:
                exact.append(item)
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise SystemAudioUnavailable("configured WASAPI loopback device is ambiguous")
        raise SystemAudioUnavailable("configured WASAPI loopback device was not found")

    def _callback(self, in_data: Any, _frame_count: int, _time_info: Any, _status: Any) -> tuple[Any, int]:
        captured_monotonic = time.monotonic()
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
            queue.put_nowait(_Chunk(data, rate, channels, captured_monotonic))
            with self._lock:
                self._chunks += 1
                self._last_chunk_monotonic = captured_monotonic
                self._queue_high_water = max(self._queue_high_water, queue.qsize())
        except Full:
            with self._lock:
                self._dropped_chunks += 1
                self._last_drop_monotonic = captured_monotonic
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
            consumed_monotonic = time.monotonic()
            samples = memoryview(chunk.data).cast("h")
            peak_abs = 0
            sum_squares = 0
            for sample in samples:
                value = int(sample)
                magnitude = abs(value)
                if magnitude > peak_abs:
                    peak_abs = magnitude
                sum_squares += value * value
            rms = math.sqrt(sum_squares / max(1, len(samples)))
            with self._lock:
                self._consumer_chunks += 1
                self._last_consumer_chunk_monotonic = consumed_monotonic
                self._last_consumer_lag_ms = max(0.0, consumed_monotonic - chunk.captured_monotonic) * 1000.0
                self._last_chunk_peak_abs = peak_abs
                self._last_chunk_rms = rms
                chunk_duration_s = len(samples) / max(1, chunk.sample_rate * chunk.channels)
                self._signal_window.append((chunk.captured_monotonic, sum_squares, len(samples), peak_abs, chunk_duration_s))
                cutoff = consumed_monotonic - 1.0
                while self._signal_window and self._signal_window[0][0] < cutoff:
                    self._signal_window.popleft()
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
        self._device_name = ""
        self._device_index = None
        self._host_api_index = None
        self._signal_window.clear()
        self._last_chunk_monotonic = None
        self._last_consumer_chunk_monotonic = None
        self._last_chunk_peak_abs = None
        self._last_chunk_rms = None
        self._last_consumer_lag_ms = None
        self._last_drop_monotonic = None
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {str(exc)[:160]}"[:200]


__all__ = ["PcmConsumer", "SystemAudioLoopback", "SystemAudioUnavailable"]
