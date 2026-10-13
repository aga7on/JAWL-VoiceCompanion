"""Windows regressions for per-worker descendant cleanup on restart/stop."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from jawl_voicecompanion import supervisor as supervisor_module


_HELPER = r'''
import json, pathlib, sys, time
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec

root = pathlib.Path(sys.argv[1])
base_python = sys.argv[2]
sys.path.insert(0, sys.argv[3])
while not (root / 'start').exists():
    time.sleep(0.01)
worker_program = r"""
import json, pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
name = sys.argv[2]
grandchild = subprocess.Popen(
    [sys.executable, '-B', '-c', 'import time; time.sleep(120)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    close_fds=True)
(root / (name + '-current.json')).write_text(
    json.dumps({'root': __import__('os').getpid(), 'child': grandchild.pid}),
    encoding='utf-8')
while not (root / (name + '-exit-root')).exists():
    time.sleep(0.01)
"""

specs = [WorkerSpec(
    name=name,
    command=[base_python, '-B', '-c', worker_program, str(root), name],
    probe=None, max_restarts=2, stop_timeout_seconds=1,
) for name in ('A', 'B')]
supervisor = RuntimeSupervisor(specs)
started = supervisor.start()
for name in ('A', 'B'):
    deadline = time.monotonic() + 5
    while not (root / (name + '-current.json')).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
pids = {name: json.loads((root / (name + '-current.json')).read_text(encoding='utf-8'))
        for name in ('A', 'B')}
(root / 'started.json').write_text(json.dumps({
    'ok': started.ok,
    'owns_b_root': supervisor.owns_pid(pids['B']['root']),
    'owns_b_child': supervisor.owns_pid(pids['B']['child']),
}), encoding='utf-8')

seen = set()
while not (root / 'finish').exists():
    for operation in ('restart-a', 'exit-root-a', 'start', 'stop'):
        request = root / (operation + '.request')
        if request.exists() and operation not in seen:
            seen.add(operation)
            if operation == 'restart-a':
                result = supervisor.restart('A')
                current_b = json.loads((root / 'B-current.json').read_text(encoding='utf-8'))
                payload = {
                    'ok': result.ok, 'summary': result.worker_summary('A'),
                    'owns_a_root': supervisor.owns_pid(result.worker_summary('A')['pid']),
                    'owns_b_root': supervisor.owns_pid(current_b['root']),
                    'owns_b_child': supervisor.owns_pid(current_b['child']),
                    'b_root': current_b['root'], 'b_child': current_b['child'],
                }
            elif operation == 'exit-root-a':
                (root / 'A-exit-root').write_text('exit', encoding='utf-8')
                deadline = time.monotonic() + 3
                while supervisor._states['A'].process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                (root / 'A-exit-root').unlink(missing_ok=True)
                payload = {'ok': True}
            elif operation == 'start':
                result = supervisor.start()
                current_b = json.loads((root / 'B-current.json').read_text(encoding='utf-8'))
                payload = {
                    'ok': result.ok, 'summary': result.worker_summary('A'),
                    'owns_a_root': supervisor.owns_pid(result.worker_summary('A')['pid']),
                    'owns_b_root': supervisor.owns_pid(current_b['root']),
                    'owns_b_child': supervisor.owns_pid(current_b['child']),
                }
            else:
                result = supervisor.stop()
                payload = {'ok': result.ok}
            (root / (operation + '.json')).write_text(json.dumps(payload), encoding='utf-8')
    time.sleep(0.01)
supervisor.stop()
'''


def _write(path: Path, value: str = "go") -> None:
    path.write_text(value, encoding="utf-8")


def _read_json(path: Path, timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def _attach_helper(directory: Path):
    safety_job = supervisor_module._windows_job_object()
    if safety_job is None:
        raise unittest.SkipTest("could not create test safety Job")
    log = (directory / "helper.log").open("wb")
    helper = subprocess.Popen(
        [getattr(sys, "_base_executable", sys.executable), "-B", "-c", _HELPER,
         str(directory), getattr(sys, "_base_executable", sys.executable),
         str(Path(__file__).resolve().parents[1] / "src")],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True,
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
    _write(directory / "start")
    return helper, safety_job, log


def _process_handle(pid: int):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel, handle


def _signaled(kernel, handle) -> bool:
    import ctypes

    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    return kernel.WaitForSingleObject(handle, 0) == 0


def _wait_signaled(handles, timeout: float = 4) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(_signaled(kernel, handle) for kernel, handle in handles):
            return True
        time.sleep(0.02)
    return all(_signaled(kernel, handle) for kernel, handle in handles)


@unittest.skipUnless(sys.platform == "win32", "requires Windows Job Objects")
class SupervisorWorkerTreeTests(unittest.TestCase):
    def _running_fixture(self):
        temp = tempfile.TemporaryDirectory(prefix="jawl-worker-tree-")
        directory = Path(temp.name)
        helper, safety_job, log = _attach_helper(directory)
        try:
            started = _read_json(directory / "started.json")
            self.assertTrue(started["ok"])
            self.assertTrue(started["owns_b_root"])
            self.assertTrue(started["owns_b_child"])
            pids = {name: _read_json(directory / (name + "-current.json"))
                    for name in ("A", "B")}
            handles = [_process_handle(pid) for record in pids.values()
                       for pid in record.values()]
            return temp, directory, helper, safety_job, log, pids, handles
        except BaseException:
            _write(directory / "finish")
            if helper.poll() is None:
                helper.kill()
                helper.wait(timeout=3)
            supervisor_module._close_windows_job(safety_job)
            log.close()
            temp.cleanup()
            raise

    def _cleanup(self, temp, directory, helper, safety_job, log, handles):
        _write(directory / "finish")
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=3)
        for kernel, handle in handles:
            kernel.CloseHandle(handle)
        supervisor_module._close_windows_job(safety_job)
        log.close()
        temp.cleanup()

    def test_restart_reaps_old_tree_and_preserves_other_worker(self):
        temp, directory, helper, safety_job, log, pids, handles = self._running_fixture()
        try:
            self.assertTrue(supervisor_module._pid_in_windows_job(safety_job, helper.pid))
            _write(directory / "restart-a.request")
            result = _read_json(directory / "restart-a.json")
            self.assertTrue(result["ok"])
            self.assertTrue(_wait_signaled(handles[:2]), "old A root or grandchild survived restart")
            self.assertFalse(_signaled(*handles[2]), "restarting A stopped B's root")
            self.assertFalse(_signaled(*handles[3]), "restarting A stopped B's grandchild")
            self.assertTrue(result["owns_b_root"])
            self.assertTrue(result["owns_b_child"])
            self.assertTrue(result["owns_a_root"])
            replacement_a = _read_json(directory / "A-current.json")
            replacement_handles = [_process_handle(pid) for pid in replacement_a.values()]
            handles.extend(replacement_handles)
            _write(directory / "stop.request")
            self.assertTrue(_read_json(directory / "stop.json")["ok"])
            self.assertTrue(_wait_signaled(handles), "a worker tree survived full stop")
        finally:
            self._cleanup(temp, directory, helper, safety_job, log, handles)

    def test_restart_closes_worker_job_after_root_exits(self):
        temp, directory, helper, safety_job, log, pids, handles = self._running_fixture()
        try:
            _write(directory / "exit-root-a.request")
            self.assertTrue(_read_json(directory / "exit-root-a.json")["ok"])
            self.assertTrue(_wait_signaled(handles[:1]), "A root did not exit")
            self.assertFalse(_signaled(*handles[1]), "A grandchild exited before worker restart")
            self.assertFalse(_signaled(*handles[2]), "A root exit affected B")
            self.assertFalse(_signaled(*handles[3]), "A root exit affected B's grandchild")
            _write(directory / "restart-a.request")
            self.assertTrue(_read_json(directory / "restart-a.json")["ok"])
            self.assertTrue(_wait_signaled(handles[1:2]), "A grandchild survived restart after root exit")
            self.assertFalse(_signaled(*handles[2]), "restarting A stopped B's root")
            self.assertFalse(_signaled(*handles[3]), "restarting A stopped B's grandchild")
            _write(directory / "stop.request")
            self.assertTrue(_read_json(directory / "stop.json")["ok"])
            self.assertTrue(_wait_signaled(handles[2:]), "B tree survived full stop")
        finally:
            self._cleanup(temp, directory, helper, safety_job, log, handles)

    def test_start_reaps_dead_generation_before_replacing_worker(self):
        temp, directory, helper, safety_job, log, pids, handles = self._running_fixture()
        try:
            _write(directory / "exit-root-a.request")
            self.assertTrue(_read_json(directory / "exit-root-a.json")["ok"])
            self.assertTrue(_wait_signaled(handles[:1]), "A root did not exit")
            self.assertFalse(_signaled(*handles[1]), "A grandchild exited before start")
            _write(directory / "start.request")
            result = _read_json(directory / "start.json")
            self.assertTrue(result["ok"])
            self.assertTrue(_wait_signaled(handles[1:2]), "start left the previous A grandchild alive")
            self.assertTrue(result["owns_a_root"])
            self.assertTrue(result["owns_b_root"])
            self.assertTrue(result["owns_b_child"])
            new_a = _read_json(directory / "A-current.json")
            self.assertNotEqual(new_a["root"], pids["A"]["root"])
            self.assertTrue(supervisor_module._pid_in_windows_job(safety_job, helper.pid))
            new_handles = [_process_handle(pid) for pid in new_a.values()]
            handles.extend(new_handles)
            _write(directory / "stop.request")
            self.assertTrue(_read_json(directory / "stop.json")["ok"])
            self.assertTrue(_wait_signaled(handles[2:]), "new A or B tree survived full stop")
        finally:
            self._cleanup(temp, directory, helper, safety_job, log, handles)

    def test_full_stop_reaps_every_worker_tree(self):
        temp, directory, helper, safety_job, log, pids, handles = self._running_fixture()
        try:
            _write(directory / "stop.request")
            self.assertTrue(_read_json(directory / "stop.json")["ok"])
            self.assertTrue(_wait_signaled(handles), "one or more worker descendants survived stop")
        finally:
            self._cleanup(temp, directory, helper, safety_job, log, handles)


if __name__ == "__main__":
    unittest.main()
