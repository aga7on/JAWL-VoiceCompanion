"""Windows regression tests for atomic worker creation inside a Job Object.

These tests use only short-lived Python children. A test-owned outer Job is
attached to each helper before it is allowed to create its supervisor, so a
failed assertion still has an OS-enforced cleanup boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from jawl_voicecompanion import supervisor as supervisor_module
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec


_HELPER_PROGRAM = r'''
import json, os, pathlib, subprocess, sys, time

root = pathlib.Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
from jawl_voicecompanion import supervisor as module
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec

# The external test attaches this process to its safety Job before releasing
# the marker. No supervisor or worker exists before that point.
while not (root / "start").exists():
    time.sleep(0.01)

if sys.argv[3] == 'legacy':
    # Safe negative control: descendants still inherit the test outer Job.
    # Production never falls back to this racy path.
    module._create_job_process = lambda command, job, **kwargs: subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)

child_program = r"""import json, os, pathlib, subprocess, sys, time
grandchild = subprocess.Popen(
    [sys.executable, '-B', '-c', 'import time; time.sleep(120)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    close_fds=True)
pathlib.Path(sys.argv[1]).write_text(
    json.dumps({'worker_pid': os.getpid(), 'grandchild_pid': grandchild.pid}),
    encoding='utf-8')
time.sleep(120)
"""

sup = RuntimeSupervisor([WorkerSpec(
    name="atomic-worker",
    command=[sys.argv[4], "-B", "-c", child_program, str(root / "pids.json")],
    probe=None,
    max_restarts=0,
)])
real_assign = module._assign_to_job

def paused_verification(job, process):
    deadline = time.monotonic() + 5
    pid_file = root / "pids.json"
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    descendants = json.loads(pid_file.read_text(encoding="utf-8")) if pid_file.exists() else None
    record = {
        "pid": process.pid,
        "contained": module._pid_in_windows_job(job, process.pid),
        "descendants": descendants,
        "worker_contained": (
            module._pid_in_windows_job(job, descendants["worker_pid"])
            if descendants is not None else False
        ),
        "grandchild_contained": (
            module._pid_in_windows_job(job, descendants["grandchild_pid"])
            if descendants is not None else False
        ),
    }
    (root / "hook.json").write_text(json.dumps(record), encoding="utf-8")
    deadline = time.monotonic() + 30
    while not (root / "release").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    # Keep the existing post-create verification behavior after the test has
    # observed the atomic ownership state.
    return real_assign(job, process)

module._assign_to_job = paused_verification
try:
    report = sup.start()
    (root / "started.json").write_text(json.dumps({"ok": report.ok}), encoding="utf-8")
    while not (root / "finish").exists():
        time.sleep(0.01)
finally:
    module._assign_to_job = real_assign
    sup.stop()
    (root / "done").write_text("done", encoding="utf-8")
'''


def _write_marker(directory: Path, name: str) -> None:
    (directory / name).write_text("ready", encoding="utf-8")


def _read_json_until(path: Path, *, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def _attach_helper_to_safety_job(directory: Path, *, legacy=False):
    safety_job = supervisor_module._windows_job_object()
    if safety_job is None:
        raise unittest.SkipTest("could not create the test safety Job Object")
    log_path = directory / "helper.log"
    log = log_path.open("wb")
    helper = subprocess.Popen(
        [
            getattr(sys, '_base_executable', sys.executable),
            "-B",
            "-c",
            _HELPER_PROGRAM,
            str(directory),
            str(Path(__file__).resolve().parents[1] / "src"),
            'legacy' if legacy else 'atomic',
            sys.executable,
        ],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )
    try:
        supervisor_module._assign_to_job(safety_job, helper)
    except BaseException:
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=3)
        supervisor_module._close_windows_job(safety_job)
        log.close()
        raise
    _write_marker(directory, "start")
    return helper, safety_job, log


def _open_process_wait_handle(pid: int):
    """Open a stable process handle so PID reuse cannot affect liveness checks."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel32, handle


def _process_handle_signaled(kernel32, handle) -> bool:
    import ctypes

    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    return kernel32.WaitForSingleObject(handle, 0) == 0  # WAIT_OBJECT_0


def _active_job_processes(job):
    import ctypes
    from ctypes import wintypes
    class Accounting(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in ('user', 'kernel', 'period_user', 'period_kernel')]
        _fields_ += [(name, wintypes.DWORD) for name in ('faults', 'total', 'active', 'terminated')]
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             wintypes.DWORD, ctypes.c_void_p]
    api.QueryInformationJobObject.restype = wintypes.BOOL
    state = Accounting()
    if not api.QueryInformationJobObject(job, 1, ctypes.byref(state), ctypes.sizeof(state), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return state.active


@unittest.skipUnless(sys.platform == "win32", "requires Windows Job Objects")
class SupervisorAtomicJobTests(unittest.TestCase):
    def test_legacy_late_assignment_negative_control_is_detected(self):
        with tempfile.TemporaryDirectory(prefix='jawl-legacy-create-') as temp_dir:
            directory = Path(temp_dir)
            helper, safety_job, log = _attach_helper_to_safety_job(directory, legacy=True)
            try:
                observed = _read_json_until(directory / 'hook.json', timeout=5)
                self.assertIsNotNone(observed['descendants'])
                self.assertFalse(observed['contained'], 'negative control unexpectedly had atomic containment')
                self.assertFalse(observed['grandchild_contained'])
            finally:
                helper.kill()
                helper.wait(timeout=3)
                supervisor_module._close_windows_job(safety_job)
                log.close()

    def test_worker_and_early_grandchild_are_in_exact_supervisor_job_at_verification(self):
        with tempfile.TemporaryDirectory(prefix="jawl-atomic-job-") as temp_dir:
            directory = Path(temp_dir)
            helper, safety_job, log = _attach_helper_to_safety_job(directory)
            try:
                observed = _read_json_until(directory / "hook.json", timeout=5)
                self.assertTrue(observed["contained"], "worker was not in its exact Job before verification")
                self.assertIsNotNone(observed["descendants"], "worker did not report its early grandchild")
                self.assertTrue(
                    observed["grandchild_contained"],
                    "early grandchild was not in the exact supervisor Job before verification",
                )
                pids = observed["descendants"]
                self.assertTrue(observed['worker_contained'])
                self.assertTrue(supervisor_module._pid_in_windows_job(safety_job, helper.pid))
                # The test safety Job contains the helper and its descendants;
                _write_marker(directory, "release")
                started = _read_json_until(directory / "started.json", timeout=5)
                self.assertTrue(started["ok"])
                _write_marker(directory, "finish")
                deadline = time.monotonic() + 5
                while not (directory / "done").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((directory / "done").exists(), "helper did not finish supervisor cleanup")
            finally:
                _write_marker(directory, "release")
                _write_marker(directory, "finish")
                if helper.poll() is None:
                    helper.kill()
                    helper.wait(timeout=3)
                supervisor_module._close_windows_job(safety_job)
                log.close()

    def test_hard_killing_paused_supervisor_reaps_worker_and_grandchild_only(self):
        with tempfile.TemporaryDirectory(prefix="jawl-atomic-kill-") as temp_dir:
            directory = Path(temp_dir)
            helper, safety_job, log = _attach_helper_to_safety_job(directory)
            foreign = subprocess.Popen(
                [getattr(sys, '_base_executable', sys.executable), "-B", "-c", "import time; time.sleep(120)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            handles = []
            try:
                observed = _read_json_until(directory / "hook.json", timeout=5)
                self.assertTrue(observed["contained"], "worker was not atomically contained before hook pause")
                self.assertIsNotNone(observed["descendants"], "worker did not report its early grandchild")
                pids = observed["descendants"]
                self.assertTrue(observed['worker_contained'])
                for pid in {observed['pid'], pids["worker_pid"], pids["grandchild_pid"]}:
                    handles.append(_open_process_wait_handle(pid))

                helper.kill()
                helper.wait(timeout=3)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not all(
                    _process_handle_signaled(kernel32, handle) for kernel32, handle in handles
                ):
                    time.sleep(0.02)
                self.assertTrue(
                    all(_process_handle_signaled(kernel32, handle) for kernel32, handle in handles),
                    "a worker or grandchild survived hard termination of its supervisor",
                )
                # Covers unlisted venv redirector descendants too, before the
                # outer safety Job is closed (it cannot cause a false PASS).
                self.assertEqual(_active_job_processes(safety_job), 0)
                self.assertIsNone(foreign.poll(), "supervisor Job cleanup affected the foreign control child")
            finally:
                _write_marker(directory, "release")
                _write_marker(directory, "finish")
                if helper.poll() is None:
                    helper.kill()
                    helper.wait(timeout=3)
                for kernel32, handle in handles:
                    kernel32.CloseHandle(handle)
                if foreign.poll() is None:
                    foreign.terminate()
                foreign.wait(timeout=3)
                supervisor_module._close_windows_job(safety_job)
                log.close()


if __name__ == "__main__":
    unittest.main()
