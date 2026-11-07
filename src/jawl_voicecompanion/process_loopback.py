"""Windows WASAPI Process-Tree Loopback Python Bridge.

Spawns and manages the native runtime/bin/process-loopback/process-loopback.exe
helper to capture isolated audio from a single application process tree without
capturing system sounds or mixing other applications.
"""

from __future__ import annotations

import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
from typing import Any, Callable


class ProcessLoopbackError(RuntimeError):
    """Raised when process loopback initialization, capture, or termination fails."""


class ProcessLoopbackBridge:
    """Controls native Windows WASAPI Process-Tree Loopback capture."""

    HANDSHAKE = b"JAWLPCM1"

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        default_sample_rate: int = 44100,
        default_channels: int = 2,
        spawn: Callable[..., Any] | None = None,
        affective_engine: Any | None = None,
    ) -> None:
        if executable is not None:
            self.executable = Path(executable)
        else:
            self.executable = self.find_default_executable()

        self.default_sample_rate = int(default_sample_rate)
        self.default_channels = int(default_channels)
        self.sample_rate = self.default_sample_rate
        self.channels = self.default_channels
        self._spawn = spawn
        self._affective_engine = affective_engine

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._process: Any | None = None
        self._reader_thread: threading.Thread | None = None
        self._pid: int | None = None
        self._consumer: Callable[..., None] | None = None
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self._bytes_captured = 0
        self._chunks_captured = 0
        self._last_error: str | None = None

    @staticmethod
    def find_default_executable() -> Path:
        """Locate process-loopback.exe in runtime/bin, cwd, or PATH."""
        src_path = Path(__file__).resolve()
        repo_root = src_path.parents[2]
        candidate = repo_root / "runtime" / "bin" / "process-loopback" / "process-loopback.exe"
        if candidate.is_file():
            return candidate

        cwd_candidate = Path.cwd() / "runtime" / "bin" / "process-loopback" / "process-loopback.exe"
        if cwd_candidate.is_file():
            return cwd_candidate

        which_path = shutil.which("process-loopback.exe") or shutil.which("process-loopback")
        if which_path:
            return Path(which_path)

        return candidate

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(
                self._process is not None
                and self._process.poll() is None
                and not self._stop_event.is_set()
            )

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._pid

    def start(
        self,
        pid: int,
        consumer: Callable[[bytes, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Validate binary, spawn helper for PID, verify handshake, and start reader."""
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError(f"Valid positive pid required, got {pid!r}")

        with self._lock:
            if self.running:
                if self._pid == pid:
                    return self.state()
                raise ProcessLoopbackError(
                    f"Process loopback already running for PID {self._pid}; stop it first."
                )

            # Ensure any lingering stopped instance is cleared
            if self._process is not None:
                self.stop()

            if not self.executable.is_file():
                raise ProcessLoopbackError(
                    f"process-loopback executable not found at '{self.executable}'"
                )

            self._pid = pid
            self._consumer = consumer
            self._stop_event.clear()
            self._bytes_captured = 0
            self._chunks_captured = 0
            self._last_error = None
            self._queue = queue.Queue(maxsize=256)

            spawn_func = self._spawn or subprocess.Popen
            cmd = [str(self.executable), str(pid)]
            try:
                proc = spawn_func(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except Exception as exc:
                self._last_error = f"Spawn error: {exc}"
                raise ProcessLoopbackError(f"Failed to spawn process loopback: {exc}") from exc

            self._process = proc

        # Read and verify 8-byte magic handshake
        handshake = bytearray()
        try:
            while len(handshake) < len(self.HANDSHAKE):
                chunk = proc.stdout.read(len(self.HANDSHAKE) - len(handshake))
                if not chunk:
                    break
                handshake.extend(chunk)
        except Exception as exc:
            with self._lock:
                self._last_error = f"Handshake read error: {exc}"

        if bytes(handshake) != self.HANDSHAKE:
            stderr_detail = ""
            try:
                if proc.poll() is None:
                    proc.wait(timeout=0.5)
            except Exception:
                pass
            try:
                if proc.stderr:
                    raw_err = proc.stderr.read()
                    if raw_err:
                        stderr_detail = raw_err.decode("utf-8", errors="replace").strip()
            except Exception:
                pass

            self._stop_event.set()
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                pass
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            with self._lock:
                self._process = None
                err_msg = (
                    f"Process loopback handshake failed: expected {self.HANDSHAKE!r}, "
                    f"received {bytes(handshake)!r}"
                )
                if stderr_detail:
                    err_msg += f" (stderr: {stderr_detail})"
                self._last_error = err_msg
                raise ProcessLoopbackError(err_msg)

        # Handshake verified, start background reader thread
        with self._lock:
            reader = threading.Thread(
                target=self._reader_loop,
                args=(proc, consumer),
                name=f"process-loopback-reader-{pid}",
                daemon=True,
            )
            self._reader_thread = reader
            reader.start()

        return self.state()

    def _reader_loop(
        self,
        proc: Any,
        consumer: Callable[..., None] | None,
    ) -> None:
        chunk_size = 4096
        bytes_per_frame = self.channels * 2  # 16-bit PCM = 2 bytes per sample
        remainder = b""

        while not self._stop_event.is_set():
            try:
                raw = proc.stdout.read(chunk_size)
            except Exception as exc:
                if not self._stop_event.is_set():
                    with self._lock:
                        self._last_error = f"Read error: {exc}"
                break
            if not raw:
                # EOF reached (target process exited or stream closed)
                break

            data = remainder + raw
            rem_len = len(data) % bytes_per_frame
            if rem_len:
                remainder = data[-rem_len:]
                data = data[:-rem_len]
            else:
                remainder = b""

            if not data:
                continue

            with self._lock:
                self._bytes_captured += len(data)
                self._chunks_captured += 1

            if self._affective_engine is not None:
                try:
                    self._affective_engine.process_pcm_chunk(data, self.sample_rate, self.channels)
                except Exception:
                    pass

            if consumer is not None:
                try:
                    consumer(data, self.sample_rate, self.channels)
                except TypeError:
                    try:
                        consumer(data, self.sample_rate, self.channels, f"process-{self._pid}")
                    except Exception as exc:
                        with self._lock:
                            self._last_error = f"Consumer callback error: {exc}"
                except Exception as exc:
                    with self._lock:
                        self._last_error = f"Consumer callback error: {exc}"
            else:
                try:
                    self._queue.put_nowait(data)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._queue.put_nowait(data)
                    except queue.Full:
                        pass

    def stop(self, timeout: float = 3.0) -> dict[str, Any]:
        """Stop capture gracefully by sending 'q' to stdin, then terminating if needed."""
        with self._lock:
            self._stop_event.set()
            proc = self._process
            reader = self._reader_thread

        if proc is not None:
            # 1. Send 'q' to stdin for graceful shutdown
            if proc.poll() is None and proc.stdin is not None:
                try:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                except (OSError, ValueError):
                    pass
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass

            # 2. Wait up to timeout for process to exit
            try:
                proc.wait(timeout=max(0.1, float(timeout)))
            except (subprocess.TimeoutExpired, Exception):
                # 3. Fall back to terminate() / kill()
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            # Close remaining pipes
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except Exception:
                        pass

        # 4. Join reader thread
        if reader is not None and reader.is_alive() and reader != threading.current_thread():
            reader.join(timeout=1.5)

        with self._lock:
            self._process = None
            self._reader_thread = None

        return self.state()

    def get_chunk(self, timeout: float | None = None) -> bytes | None:
        """Retrieve next captured audio chunk when no consumer is registered."""
        try:
            return self._queue.get(timeout=timeout)
        except (queue.Empty, Exception):
            return None

    @property
    def affective_engine(self) -> Any | None:
        return self._affective_engine

    def state(self) -> dict[str, Any]:
        """Return current status dictionary."""
        with self._lock:
            proc = self._process
            is_running = bool(
                proc is not None
                and proc.poll() is None
                and not self._stop_event.is_set()
            )
            return {
                "running": is_running,
                "pid": self._pid,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "bytes_captured": self._bytes_captured,
                "chunks_captured": self._chunks_captured,
                "last_error": self._last_error,
                "queue_depth": self._queue.qsize() if self._queue is not None else 0,
                "affective": self._affective_engine.get_state() if self._affective_engine is not None else None,
            }

    def __enter__(self) -> ProcessLoopbackBridge:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


__all__ = ["ProcessLoopbackBridge", "ProcessLoopbackError"]
