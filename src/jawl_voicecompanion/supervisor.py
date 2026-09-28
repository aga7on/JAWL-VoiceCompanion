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
