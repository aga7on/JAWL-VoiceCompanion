"""Binary PIPE worker with atomic Windows containment and handle-only teardown."""
from __future__ import annotations

import subprocess
import sys
import threading
import time

from .windows_process import create_job_process


class OwnedPipeProcess:
    def __init__(self, process, job):
        self._lock = threading.Lock()
        self._process, self._job = process, job
        self._wait_handles = []

    def __getattr__(self, name):
        return getattr(self._process, name)

    @property
    def cleanup_pending(self):
        return self._job is not None

    def terminate(self):
        import ctypes
        from ctypes import wintypes as w
        from .supervisor import _capture_windows_job_processes
        with self._lock:
            if self._job is None:
                return
            _capture_windows_job_processes(self._job, self._wait_handles)
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
            api.TerminateJobObject.restype = w.BOOL
            if not api.TerminateJobObject(self._job, 1):
                raise ctypes.WinError(ctypes.get_last_error())

    kill = terminate

    def wait(self, timeout=None):
        from .supervisor import _drain_windows_job
        started = time.monotonic()
        code = self._process.wait(timeout)
        with self._lock:
            if self._job is not None:
                # Root exit is not tree exit: close descendants holding inherited pipes.
                remaining = 2.0 if timeout is None else max(0, timeout - (time.monotonic() - started))
                _drain_windows_job(self._job, remaining, process_handles=self._wait_handles)
                self._job = None
        return code

    def __del__(self):
        try:
            from .supervisor import _close_windows_job, _close_process_wait_handles
            if self._job is not None:
                _close_windows_job(self._job)
            _close_process_wait_handles(self._wait_handles)
        except Exception:
            pass


def spawn_owned_pipe(command, *, env=None, bufsize=-1):
    return _spawn_owned(command, env=env, bufsize=bufsize, pipe_stdio=True)


def spawn_owned_worker(command, *, env=None):
    """DEVNULL variant for file-protocol workers; same tree ownership."""
    return _spawn_owned(command, env=env, bufsize=0, pipe_stdio=False)


def _spawn_owned(command, *, env, bufsize, pipe_stdio):
    if sys.platform != 'win32':
        return subprocess.Popen(command, stdin=subprocess.PIPE if pipe_stdio else subprocess.DEVNULL,
                                stdout=subprocess.PIPE if pipe_stdio else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=env, bufsize=bufsize)
    from .supervisor import _windows_job_object, _close_windows_job
    job = _windows_job_object()
    if job is None:
        raise OSError('PIPE worker containment unavailable')
    try:
        process = create_job_process(command, job, env=env, pipe_stdio=pipe_stdio, bufsize=bufsize)
        return OwnedPipeProcess(process, job)
    except BaseException:
        _close_windows_job(job)
        raise
