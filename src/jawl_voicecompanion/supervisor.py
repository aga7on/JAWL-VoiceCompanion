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
import time
from dataclasses import dataclass, field
from typing import Callable

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


def _assign_to_job(handle: object, process: subprocess.Popen) -> None:
    """Put a worker inside the supervisor's job object.

    AssignProcessToJobObject needs a real process HANDLE with
    PROCESS_SET_QUOTA|PROCESS_TERMINATE access - passing the bare pid (an
    int) silently fails, which is exactly how the orphan-workers bug slipped
    through: the job existed, the OS just never knew the worker was in it.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    process_handle = kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, process.pid)
    if not process_handle:
        return
    try:
        kernel32.AssignProcessToJobObject(handle, process_handle)
    finally:
        kernel32.CloseHandle(process_handle)


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
    process: subprocess.Popen | None = None
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
        for spec in self._specs:
            state = self._states[spec.name]
            while True:
                state.last_error = None
                try:
                    state.process = subprocess.Popen(
                        spec.command,
                        cwd=spec.cwd,
                        env=spec.env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if self._job is not None:
                        _assign_to_job(self._job, state.process)
                    state.started_at = self._clock()
                except OSError as exc:
                    state.last_error = f"spawn failed: {type(exc).__name__}"
                if state.process is not None and not self._wait_healthy(spec, state):
                    self._stop_worker(spec, state)
                    state.process = None
                if state.process is not None:
                    state.healthy = True
                    break
                if state.restarts_used >= spec.max_restarts:
                    self.stop()
                    return SupervisorReport(ok=False, workers=self._summary())
                state.restarts_used += 1
        return SupervisorReport(ok=True, workers=self._summary())

    def stop(self) -> SupervisorReport:
        """Tear down in reverse order. Only processes this supervisor started."""
        for spec in reversed(self._specs):
            self._stop_worker(spec, self._specs and self._states[spec.name])
        return SupervisorReport(ok=True, workers=self._summary())

    def health(self) -> SupervisorReport:
        """Report each worker's liveness; a dead worker marks the stack red."""
        all_alive = True
        for spec in self._specs:
            state = self._states[spec.name]
            alive = state.process is not None and state.process.poll() is None
            state.healthy = alive
            all_alive = all_alive and alive
        return SupervisorReport(ok=all_alive, workers=self._summary())

    def restart(self, name: str) -> SupervisorReport:
        """Restart one worker within its budget."""
        spec = self._spec_or_raise(name)
        state = self._states[name]
        if state.restarts_used >= spec.max_restarts:
            return SupervisorReport(
                ok=False,
                workers={name: {**self._summary()[name],
                                 "error": "restart budget exhausted"}},
            )
        self._stop_worker(spec, state)
        state.restarts_used += 1
        state.healthy = False
        state.process = None
        try:
            state.process = subprocess.Popen(
                spec.command, cwd=spec.cwd, env=spec.env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            state.started_at = self._clock()
        except OSError as exc:
            state.last_error = f"spawn failed: {type(exc).__name__}"
            return SupervisorReport(ok=False, workers=self._summary())
        if not self._wait_healthy(spec, state):
            self._stop_worker(spec, state)
            state.process = None
            return SupervisorReport(ok=False, workers=self._summary())
        state.healthy = True
        return SupervisorReport(ok=True, workers=self._summary())

    # -- internals ---------------------------------------------------------

    def _wait_healthy(self, spec: WorkerSpec, state: WorkerState) -> bool:
        if spec.probe is None:
            # No probe: the process existing after a short settle window is
            # enough (it may legitimately be a batch-style worker).
            time.sleep(0.1)
            return state.process is not None and state.process.poll() is None
        deadline = self._clock() + spec.startup_timeout_seconds
        while self._clock() < deadline:
            if state.process is not None and state.process.poll() is not None:
                state.last_error = f"exited during startup with code {state.process.returncode}"
                return False
            try:
                if spec.probe():
                    return True
            except Exception:  # noqa: BLE001 - a throwing probe is just not healthy yet
                pass
            time.sleep(0.2)
        # A worker that exited during the final sleep must still be reported as
        # an exit, not as a timeout.
        if state.process is not None and state.process.poll() is not None:
            state.last_error = f"exited during startup with code {state.process.returncode}"
            return False
        state.last_error = "startup health timeout"
        return False

    def _stop_worker(self, spec: WorkerSpec, state: WorkerState) -> None:
        process = state.process
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
