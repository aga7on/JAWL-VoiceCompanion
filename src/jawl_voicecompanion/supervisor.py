"""Runtime supervisor (ADR-041 stage 2): one owner for the stack's processes.

The PowerShell launcher currently spells out process lifecycle by hand; this
module moves that ownership into the product so the profile becomes "one
executable entry" instead of a script. The supervisor:

- starts workers in dependency order and waits for each health probe;
- restarts a failed worker a bounded number of times (budget, not a loop);
- tears the stack down in reverse order, terminating children it owns;
- never kills a process it did not start (verified by pid + creation time).

Scope of this slice: process lifecycle and health. Port discovery comes from
the runtime manifest; budgets are per-worker restart limits.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from .windows_process import WindowsJobProcess, create_job_process as _create_job_process

HealthProbe = Callable[[], bool]


def _windows_job_object() -> "object | None":
    """A Job Object that kills children when the parent dies.

    On Windows, terminating the parent process does not run its `finally`
    blocks, so a `finally: supervisor.stop()` cannot fire: workers would
    survive as orphans and hold their ports (observed live: the supervised
    entry's llama-server and TTS kept listening after the parent was killed).
    Assigning every worker to a job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    makes the OS itself reap the children the moment the parent's handle
    closes - crash, kill, exit, anything.
    """
    import sys
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    from ctypes import wintypes as _wt
    kernel32.CreateJobObjectW.restype = _wt.HANDLE
    kernel32.CreateJobObjectW.argtypes = [_wt.LPVOID, _wt.LPCWSTR]
    kernel32.SetInformationJobObject.restype = _wt.BOOL
    kernel32.SetInformationJobObject.argtypes = [_wt.HANDLE, ctypes.c_int, _wt.LPVOID, _wt.DWORD]
    kernel32.CloseHandle.argtypes = [_wt.HANDLE]
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None

    ULONG_PTR = ctypes.c_size_t

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ULONG_PTR),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9
    info = JOBOBJECT_EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    size = ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT)
    ok = kernel32.SetInformationJobObject(
        handle, JobObjectExtendedLimitInformation, ctypes.byref(info), size)
    if not ok:
        kernel32.CloseHandle(handle)
        return None
    return handle


def _assign_to_job(handle: object, process: subprocess.Popen | WindowsJobProcess) -> None:
    """Put a worker inside the supervisor's job object.

    Retain creation-handle identity; an atomic worker is verified, while legacy
    explicit callers are assigned. This helper alone cannot close the latter's
    pre-assignment window. Never reopen a mutable PID or close a borrowed handle.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    # Popen/native wrapper retains the exact creation HANDLE. Never reopen a
    # mutable PID and accidentally attach a replacement process.
    process_handle = getattr(process, '_handle', None)
    if not process_handle:
        raise OSError('created process handle unavailable')
    belongs = wintypes.BOOL()
    if not kernel32.IsProcessInJob(int(process_handle), handle, ctypes.byref(belongs)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not belongs.value and not kernel32.AssignProcessToJobObject(handle, int(process_handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def _close_windows_job(handle: object) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.CloseHandle(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _drain_windows_job(handle: object, timeout: float) -> None:
    """Terminate only this worker's Job, verify it empty, then close it.

    On failure retain the handle/state and refuse replacement; closing a handle
    alone is asynchronous and cannot prove a descendant released its listener.
    """
    import ctypes
    from ctypes import wintypes as w

    class Accounting(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ('user', 'kernel', 'period_user', 'period_kernel')] + [
                    (name, w.DWORD) for name in ('faults', 'total', 'active', 'terminated')]

    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    api.TerminateJobObject.restype = w.BOOL
    api.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             w.DWORD, ctypes.c_void_p]
    api.QueryInformationJobObject.restype = w.BOOL
    if not api.TerminateJobObject(handle, 1):
        raise ctypes.WinError(ctypes.get_last_error())
    deadline = time.monotonic() + max(0, timeout)
    while True:
        info = Accounting()
        if not api.QueryInformationJobObject(handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not info.active:
            _close_windows_job(handle)
            return
        if time.monotonic() >= deadline:
            raise OSError('worker Job teardown deadline exceeded')
        time.sleep(min(.01, max(0, deadline - time.monotonic())))


def _pid_in_windows_job(handle: object, pid: int) -> bool:
    """Query this exact Job, never 'any Job' or a mutable parent-PID chain."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        belongs = wintypes.BOOL()
        if not kernel32.IsProcessInJob(process, handle, ctypes.byref(belongs)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(belongs.value)
    finally:
        kernel32.CloseHandle(process)


@dataclass
class WorkerSpec:
    """One managed process: command, health probe and restart budget."""

    name: str
    command: list[str]
    probe: HealthProbe | None
    cwd: str | None = None
    env: dict[str, str] | None = None
    startup_timeout_seconds: float = 180.0
    max_restarts: int = 2
    stop_timeout_seconds: float = 10.0
    # Workers are started in order and stopped in reverse.
    order: int = 0


@dataclass
class WorkerState:
    process: subprocess.Popen | WindowsJobProcess | None = None
    job: object | None = None
    restarts_used: int = 0
    started_at: float | None = None
    healthy: bool = False
    last_error: str | None = None


@dataclass
class SupervisorReport:
    ok: bool
    workers: dict[str, dict] = field(default_factory=dict)

    def worker_summary(self, name: str) -> dict:
        return self.workers.get(name, {})


class RuntimeSupervisor:
    """Own the lifecycle of a set of local workers (ADR-041 stage 2)."""

    def __init__(self, specs: list[WorkerSpec], *, clock: Callable[[], float] = time.monotonic) -> None:
        self._specs = sorted(specs, key=lambda item: item.order)
        if len({spec.name for spec in self._specs}) != len(self._specs):
            raise ValueError("worker names must be unique")
        self._states: dict[str, WorkerState] = {spec.name: WorkerState() for spec in self._specs}
        self._clock = clock
        self._lifecycle_lock = threading.RLock()
        self._stop_requested = threading.Event()
        # Windows: a job object so workers die with this process (see
        # _windows_job_object). Handle closes on GC/exit -> children reaped.
        self._job = _windows_job_object()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> SupervisorReport:
        """Start every worker in order, waiting for health.

        A worker that fails its probe is restarted up to its budget; once the
        budget is spent the whole start fails and everything started so far is
        torn back down (no half-alive stacks).
        """
        with self._lifecycle_lock:
            self._stop_requested.clear()
            for spec in self._specs:
                state = self._states[spec.name]
                if state.process is not None and state.process.poll() is None:
                    state.healthy = True
                    continue
                # A dead root can still have living descendants from its last generation.
                self._stop_worker(spec, state)
                while True:
                    if self._stop_requested.is_set():
                        self.stop()
                        return SupervisorReport(ok=False, workers=self._summary())
                    self._spawn_worker(spec, state)
                    if state.process is not None and not self._wait_healthy(spec, state):
                        self._stop_worker(spec, state)
                        state.process = None
                    if state.process is not None:
                        state.healthy = True
                        break
                    if self._stop_requested.is_set():
                        self.stop()
                        return SupervisorReport(ok=False, workers=self._summary())
                    if state.restarts_used >= spec.max_restarts:
                        self.stop()
                        return SupervisorReport(ok=False, workers=self._summary())
                    state.restarts_used += 1
            return SupervisorReport(ok=True, workers=self._summary())

    def stop(self) -> SupervisorReport:
        """Tear down in reverse order. Only processes this supervisor started."""
        # Signal before taking the lifecycle lock so startup/retry waits yield
        # to Stop rather than keeping resources for their whole timeout budget.
        self._stop_requested.set()
        with self._lifecycle_lock:
            for spec in reversed(self._specs):
                self._stop_worker(spec, self._states[spec.name])
            if self._job is not None:
                _close_windows_job(self._job)
                self._job = None
            return SupervisorReport(ok=True, workers=self._summary())

    def health(self) -> SupervisorReport:
        """Report each worker's liveness; a dead worker marks the stack red."""
        with self._lifecycle_lock:
            all_alive = True
            for spec in self._specs:
                state = self._states[spec.name]
                alive = state.process is not None and state.process.poll() is None
                state.healthy = alive
                all_alive = all_alive and alive
            return SupervisorReport(ok=all_alive, workers=self._summary())

    def owns_pid(self, pid: int) -> bool:
        """Prove a PID is in our live containment, including venv descendants.

        This read-only query neither grants authority nor terminates anything.
        On systems without our Windows Job, only tracked live roots qualify.
        """
        if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid <= 0xFFFFFFFF:
            return False
        with self._lifecycle_lock:
            if sys.platform == "win32":
                if self._job is None:
                    return False
                try:
                    return _pid_in_windows_job(self._job, pid)
                except OSError:
                    return False
            return any(state.process is not None and state.process.pid == pid
                       and state.process.poll() is None for state in self._states.values())

    def restart(self, name: str) -> SupervisorReport:
        """Restart one worker within its budget."""
        with self._lifecycle_lock:
            self._stop_requested.clear()
            spec = self._spec_or_raise(name)
            state = self._states[name]
            if state.restarts_used >= spec.max_restarts:
                return SupervisorReport(
                    ok=False,
                    workers={name: {**self._summary()[name],
                                     "error": "restart budget exhausted"}},
                )
            try:
                self._stop_worker(spec, state)
            except OSError:
                state.healthy = False
                state.last_error = 'worker teardown failed; replacement refused'
                return SupervisorReport(ok=False, workers=self._summary())
            state.restarts_used += 1
            state.healthy = False
            state.process = None
            if not self._spawn_worker(spec, state):
                return SupervisorReport(ok=False, workers=self._summary())
            if not self._wait_healthy(spec, state):
                self._stop_worker(spec, state)
                state.process = None
                return SupervisorReport(ok=False, workers=self._summary())
            state.healthy = True
            return SupervisorReport(ok=True, workers=self._summary())

    # -- internals ---------------------------------------------------------

    def _spawn_worker(self, spec: WorkerSpec, state: WorkerState) -> bool:
        """Use the same fail-closed containment for initial and restarted workers."""
        state.last_error = None
        state.started_at = None
        state.healthy = False
        try:
            if sys.platform == "win32" and self._job is None:
                self._job = _windows_job_object()
                if self._job is None:
                    raise OSError("Windows process containment is unavailable")
            if sys.platform == 'win32':
                state.job = _windows_job_object()
                if state.job is None:
                    raise OSError('worker process containment is unavailable')
                state.process = _create_job_process(spec.command, (self._job, state.job),
                                                     cwd=spec.cwd, env=spec.env)
            else:
                state.process = subprocess.Popen(
                    spec.command, cwd=spec.cwd, env=spec.env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            if self._job is not None:
                _assign_to_job(self._job, state.process)
            state.started_at = self._clock()
            return True
        except OSError as exc:
            # The process may already exist when job assignment fails. Never
            # report it healthy or leave it running outside our containment.
            self._stop_worker(spec, state)
            state.last_error = f"spawn/containment failed: {type(exc).__name__}"
            return False

    def _wait_healthy(self, spec: WorkerSpec, state: WorkerState) -> bool:
        if spec.probe is None:
            # No probe: the process existing after a short settle window is
            # enough (it may legitimately be a batch-style worker).
            if self._stop_requested.wait(0.1):
                state.last_error = "startup cancelled"
                return False
            return state.process is not None and state.process.poll() is None
        deadline = self._clock() + spec.startup_timeout_seconds
        while self._clock() < deadline:
            if self._stop_requested.is_set():
                state.last_error = "startup cancelled"
                return False
            if state.process is not None and state.process.poll() is not None:
                state.last_error = f"exited during startup with code {state.process.returncode}"
                return False
            try:
                ready = spec.probe()
                if self._stop_requested.is_set():
                    state.last_error = "startup cancelled"
                    return False
                if ready:
                    return True
            except Exception:  # noqa: BLE001 - a throwing probe is just not healthy yet
                pass
            self._stop_requested.wait(0.2)
        # A worker that exited during the final sleep must still be reported as
        # an exit, not as a timeout.
        if state.process is not None and state.process.poll() is not None:
            state.last_error = f"exited during startup with code {state.process.returncode}"
            return False
        state.last_error = "startup health timeout"
        return False

    def _stop_worker(self, spec: WorkerSpec, state: WorkerState) -> None:
        process = state.process
        if state.job is not None:
            # Keep ownership until empty is proven. Never spawn a replacement on
            # timeout, even when the root has exited and only descendants remain.
            state.healthy = False
            _drain_windows_job(state.job, spec.stop_timeout_seconds)
            state.job = None
            if process is not None:
                process.wait(timeout=spec.stop_timeout_seconds)
        state.process = None
        state.healthy = False
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=spec.stop_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=spec.stop_timeout_seconds)
        except OSError:
            pass

    def _spec_or_raise(self, name: str) -> WorkerSpec:
        for spec in self._specs:
            if spec.name == name:
                return spec
        raise KeyError(f"unknown worker: {name}")

    def _summary(self) -> dict[str, dict]:
        summary: dict[str, dict] = {}
        for spec in self._specs:
            state = self._states[spec.name]
            summary[spec.name] = {
                "running": state.process is not None and state.process.poll() is None,
                "pid": state.process.pid if state.process is not None else None,
                "healthy": state.healthy,
                "restarts_used": state.restarts_used,
                "last_error": state.last_error,
            }
        return summary
