"""RuntimeSupervisor tests: real subprocesses, real probes, real teardown.

Workers are actual `python -c` processes, with fault injection at the job API;
health is a real socket/HTTP probe, and a "dead" worker is a process that
exits. This is the ADR-041 stage 2 slice.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec
from jawl_voicecompanion import supervisor as supervisor_module

PYTHON = sys.executable


def worker_command(port: int) -> list[str]:
    """Build the command for a real HTTP worker bound to a fixed port.

    Imports first, handler second, server last: the generated program is
    executed top-to-bottom. allow_reuse_address lets a restarted worker bind
    the same port again.
    """
    program = (
        "import http.server, socketserver\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.send_header('Content-Length','2');\n"
        "        self.end_headers(); self.wfile.write(b'ok')\n"
        "    def log_message(self, *a): pass\n"
        "class S(socketserver.TCPServer):\n"
        "    allow_reuse_address = True\n"
        f"server = S(('127.0.0.1', {port}), H)\n"
        "server.serve_forever()\n"
    )
    return [PYTHON, "-u", "-c", program]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_probe(port: int):
    def probe() -> bool:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status == 200
    return probe


class RuntimeSupervisorTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows worker Job')
    def test_restart_teardown_failure_retains_ownership_and_refuses_spawn(self):
        sup = RuntimeSupervisor([WorkerSpec(name='fixture', command=[PYTHON, '-B', '-c',
                                  'import time;time.sleep(30)'], probe=None, max_restarts=1)])
        try:
            self.assertTrue(sup.start().ok)
            state = sup._states['fixture']
            old_process, old_job = state.process, state.job
            with patch.object(supervisor_module, '_drain_windows_job', side_effect=OSError('fixture')):
                with patch.object(supervisor_module, '_create_job_process') as spawn:
                    report = sup.restart('fixture')
            self.assertFalse(report.ok)
            spawn.assert_not_called()
            self.assertIs(state.process, old_process)
            self.assertEqual(state.job, old_job)
            self.assertEqual(state.restarts_used, 0)
            self.assertFalse(state.healthy)
        finally:
            sup.stop()

    def test_stop_interrupts_startup_retry_wait_without_another_spawn(self):
        probe_entered = threading.Event()

        def not_ready():
            probe_entered.set()
            return False

        supervisor = RuntimeSupervisor([WorkerSpec(
            name="slow-start", command=[PYTHON, "-c", "import time; time.sleep(60)"],
            probe=not_ready, startup_timeout_seconds=30, max_restarts=3,
        )])
        reports = []
        starter = threading.Thread(target=lambda: reports.append(supervisor.start()))
        try:
            starter.start()
            self.assertTrue(probe_entered.wait(2))
            process = supervisor._states["slow-start"].process
            began = time.monotonic()
            stopped = supervisor.stop()
            self.assertLess(time.monotonic() - began, 2.0)
            starter.join(2)
            self.assertFalse(starter.is_alive())
            self.assertTrue(stopped.ok)
            self.assertFalse(reports[0].ok)
            self.assertIsNotNone(process.poll())
            self.assertFalse(supervisor.health().ok)
            self.assertEqual(supervisor._states["slow-start"].restarts_used, 0)
        finally:
            supervisor.stop()
            starter.join(2)

    def test_start_is_idempotent_while_workers_are_running(self):
        spec = WorkerSpec(
            name="worker",
            command=[PYTHON, "-c", "import time; time.sleep(60)"],
            probe=None,
        )
        supervisor = RuntimeSupervisor([spec])
        spawned = []
        spawn_owner = supervisor_module if sys.platform == "win32" else supervisor_module.subprocess
        spawn_name = "_create_job_process" if sys.platform == "win32" else "Popen"
        real_popen = getattr(spawn_owner, spawn_name)

        def track_spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process

        try:
            with patch.object(spawn_owner, spawn_name, side_effect=track_spawn):
                first = supervisor.start()
                first_process = supervisor._states["worker"].process
                second = supervisor.start()
            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertEqual(len(spawned), 1)
            self.assertIs(supervisor._states["worker"].process, first_process)
            self.assertEqual(first.worker_summary("worker")["pid"], second.worker_summary("worker")["pid"])
        finally:
            supervisor.stop()
            for process in spawned:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_concurrent_start_and_stop_leave_no_worker_running(self):
        probe_entered = threading.Event()
        release_probe = threading.Event()

        def gated_probe():
            probe_entered.set()
            return release_probe.wait(timeout=5)

        spec = WorkerSpec(
            name="worker",
            command=[PYTHON, "-c", "import time; time.sleep(60)"],
            probe=gated_probe,
            startup_timeout_seconds=10,
        )
        supervisor = RuntimeSupervisor([spec])
        spawned = []
        spawn_owner = supervisor_module if sys.platform == "win32" else supervisor_module.subprocess
        spawn_name = "_create_job_process" if sys.platform == "win32" else "Popen"
        real_popen = getattr(spawn_owner, spawn_name)
        stop_started = threading.Event()
        stop_finished = threading.Event()
        reports = {}
        errors = []

        def track_spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process

        def run_start():
            try:
                reports["start"] = supervisor.start()
            except Exception as exc:  # surfaced in the test thread
                errors.append(exc)

        def run_stop():
            stop_started.set()
            try:
                reports["stop"] = supervisor.stop()
            except Exception as exc:  # surfaced in the test thread
                errors.append(exc)
            finally:
                stop_finished.set()

        start_thread = threading.Thread(target=run_start)
        stop_thread = threading.Thread(target=run_stop)
        threads = [start_thread, stop_thread]
        try:
            with patch.object(spawn_owner, spawn_name, side_effect=track_spawn):
                start_thread.start()
                self.assertTrue(probe_entered.wait(timeout=5), "start did not reach its health probe")
                stop_thread.start()
                self.assertTrue(stop_started.wait(timeout=5))
                time.sleep(0.05)
                self.assertFalse(stop_finished.is_set(), "stop must wait for the active start")
                release_probe.set()
                for thread in threads:
                    thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertFalse(reports["start"].ok, "Stop must cancel the in-progress startup")
            self.assertTrue(reports["stop"].ok)
            self.assertTrue(all(process.poll() is not None for process in spawned))
            self.assertIsNone(supervisor._states["worker"].process)
        finally:
            release_probe.set()
            supervisor.stop()
            for thread in threads:
                if thread.is_alive():
                    thread.join(timeout=5)
            for process in spawned:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_starts_ordered_workers_and_reports_health(self):
        port = free_port()
        specs = [
            WorkerSpec(
                name="brain",
                command=[PYTHON, "-c", "import time; time.sleep(60)"],
                probe=None,
                order=0,
            ),
            WorkerSpec(
                name="api",
                command=worker_command(port),
                probe=http_probe(port),
                order=1,
            ),
        ]
        supervisor = RuntimeSupervisor(specs)
        try:
            report = supervisor.start()
            self.assertTrue(report.ok, report.workers)
            summary = report.worker_summary("api")
            self.assertTrue(summary["running"])
            self.assertTrue(summary["healthy"])
            self.assertEqual(summary["restarts_used"], 0)
            health = supervisor.health()
            self.assertTrue(health.ok)
        finally:
            supervisor.stop()
        stopped = supervisor.health()
        self.assertFalse(stopped.ok)
        self.assertFalse(stopped.worker_summary("brain")["running"])
        self.assertFalse(stopped.worker_summary("api")["running"])

    def test_failing_worker_is_restarted_within_budget_then_fails_closed(self):
        port = free_port()
        # The probe never succeeds: the worker starts but never becomes healthy,
        # so the supervisor must spend the restart budget and tear everything down.
        specs = [
            WorkerSpec(
                name="broken",
                command=[PYTHON, "-c", "import time; time.sleep(60)"],
                probe=http_probe(port),  # nothing listens on this port
                startup_timeout_seconds=0.4,
                max_restarts=1,
                order=0,
            ),
        ]
        supervisor = RuntimeSupervisor(specs)
        report = supervisor.start()
        self.assertFalse(report.ok)
        summary = report.worker_summary("broken")
        self.assertEqual(summary["restarts_used"], 1)
        self.assertEqual(summary["last_error"], "startup health timeout")
        # Fail-closed: nothing is left running.
        self.assertIsNone(summary["pid"])
        self.assertFalse(summary["running"])

    def test_exiting_worker_is_detected_and_restartable(self):
        spec = WorkerSpec(
            name="crasher",
            command=[PYTHON, "-c", "import sys; sys.exit(3)"],
            probe=http_probe(free_port()),
            startup_timeout_seconds=0.4,
            max_restarts=0,
            order=0,
        )
        supervisor = RuntimeSupervisor([spec])
        report = supervisor.start()
        self.assertFalse(report.ok)
        self.assertIn("exited during startup", report.worker_summary("crasher")["last_error"])

    def test_restart_single_worker(self):
        port = free_port()
        specs = [
            WorkerSpec(
                name="api",
                command=worker_command(port),
                probe=http_probe(port),
                order=0,
            ),
        ]
        supervisor = RuntimeSupervisor(specs)
        report = supervisor.start()
        self.assertTrue(report.ok)
        first_pid = report.worker_summary("api")["pid"]
        try:
            restarted = supervisor.restart("api")
            self.assertTrue(restarted.ok, restarted.workers)
            second_pid = restarted.worker_summary("api")["pid"]
            self.assertNotEqual(first_pid, second_pid)
            self.assertTrue(supervisor.health().ok)
        finally:
            supervisor.stop()
        # Budget: one restart used.
        self.assertEqual(supervisor.health().worker_summary("api")["restarts_used"], 1)

    def test_restart_budget_is_enforced(self):
        port = free_port()
        specs = [
            WorkerSpec(
                name="api",
                command=worker_command(port),
                probe=http_probe(free_port()),  # deliberately dead: a different port
                startup_timeout_seconds=0.3,
                max_restarts=1,
                order=0,
            ),
        ]
        supervisor = RuntimeSupervisor(specs)
        supervisor.start()
        supervisor.stop()
        # restart() with a dead probe burns the budget; the second attempt fails.
        first = supervisor.restart("api")
        self.assertFalse(first.ok)
        second = supervisor.restart("api")
        self.assertFalse(second.ok)
        self.assertIn("budget exhausted", second.worker_summary("api")["error"])

    def test_duplicate_names_are_rejected(self):
        spec = WorkerSpec(name="a", command=[PYTHON, "-c", "pass"], probe=None)
        with self.assertRaises(ValueError):
            RuntimeSupervisor([spec, spec])

    def test_missing_windows_containment_refuses_before_spawn(self):
        spec = WorkerSpec(name="w", command=[PYTHON, "-c", "pass"], probe=None, max_restarts=0)
        with patch.object(supervisor_module, "_windows_job_object", return_value=None), patch.object(
            supervisor_module.sys, "platform", "win32"
        ), patch.object(supervisor_module.subprocess, "Popen") as spawn:
            supervisor = RuntimeSupervisor([spec])
            report = supervisor.start()
        self.assertFalse(report.ok)
        self.assertFalse(report.worker_summary("w")["running"])
        spawn.assert_not_called()

    def test_assignment_failure_reaps_the_just_started_process(self):
        spec = WorkerSpec(name="w", command=[PYTHON, "-c", "import time; time.sleep(5)"], probe=None, max_restarts=0)
        supervisor = RuntimeSupervisor([spec])
        spawned = []
        def fail_assignment(_job, process):
            spawned.append(process)
            raise OSError("fixture failure")
        with patch.object(supervisor_module, "_assign_to_job", side_effect=fail_assignment):
            # A marker also exercises the branch on non-Windows test hosts;
            # no real job API receives it because assignment is fault-injected.
            supervisor._job = supervisor._job or object()
            report = supervisor.start()
        self.assertFalse(report.ok)
        self.assertFalse(report.worker_summary("w")["healthy"])
        self.assertIsNone(supervisor._states["w"].process)
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].poll(), "uncontained child must be reaped")

    def test_restart_assignment_failure_is_not_reported_healthy(self):
        spec = WorkerSpec(name="w", command=[PYTHON, "-c", "import time; time.sleep(5)"], probe=None, max_restarts=1)
        supervisor = RuntimeSupervisor([spec])
        self.addCleanup(supervisor.stop)
        self.assertTrue(supervisor.start().ok)
        spawned = []
        def fail_assignment(_job, process):
            spawned.append(process)
            raise OSError("fixture failure")
        with patch.object(supervisor_module, "_assign_to_job", side_effect=fail_assignment):
            supervisor._job = supervisor._job or object()
            report = supervisor.restart("w")
        self.assertFalse(report.ok)
        self.assertFalse(report.worker_summary("w")["running"])
        self.assertIn("containment failed", report.worker_summary("w")["last_error"])
        self.assertIsNotNone(spawned[0].poll(), "uncontained restart must be reaped")

    def test_stop_closes_containment_and_next_start_can_create_it_again(self):
        spec = WorkerSpec(name="w", command=[PYTHON, "-c", "import time; time.sleep(5)"], probe=None)
        supervisor = RuntimeSupervisor([spec])
        self.addCleanup(supervisor.stop)
        self.assertTrue(supervisor.start().ok)
        supervisor.stop()
        self.assertIsNone(supervisor._job)
        self.assertTrue(supervisor.start().ok)
        self.assertTrue(supervisor.health().ok)

    def test_killing_the_parent_reaps_workers_on_windows(self):
        self._assert_parent_kill_reaps_worker(restart=False)

    def test_killing_the_parent_reaps_restarted_workers_on_windows(self):
        self._assert_parent_kill_reaps_worker(restart=True)

    def _assert_parent_kill_reaps_worker(self, *, restart):
        """Windows contract: TerminateProcess skips the parent's `finally`.

        Without the job object the workers survive as orphans (observed live:
        llama-server and TTS kept their ports after the parent was killed).
        The job with KILL_ON_JOB_CLOSE makes the OS itself reap them.
        """
        import sys as _sys
        if _sys.platform != "win32":
            self.skipTest("windows-only job-object contract")
        # Child program: start a worker via the supervisor, report readiness,
        # then wait forever; the test kills the child (the worker's parent).
        parent_program = (
            "import json, sys, time\n"
            "sys.path.insert(0, r'" + str(Path(__file__).resolve().parents[1] / "src") + "')\n"
            "from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec\n"
            "spec = WorkerSpec(name='w', command=[sys.executable, '-c', 'import time; time.sleep(120)'], probe=None)\n"
            "sup = RuntimeSupervisor([spec])\n"
            "report = sup.start()\n"
            + ("report = sup.restart('w')\n" if restart else "") +
            "print(json.dumps({'pid': report.workers['w']['pid'], 'ok': report.ok}), flush=True)\n"
            "time.sleep(120)\n"
        )
        parent = subprocess.Popen(
            [PYTHON, "-u", "-c", parent_program],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            line = parent.stdout.readline().strip()
            info = json.loads(line)
            self.assertTrue(info["ok"])
            worker_pid = info["pid"]
        finally:
            parent.kill()
            parent.wait(timeout=10)
            parent.stdout.close()
        # The OS must reap the worker shortly after the parent's job handle
        # is gone. Poll for a bounded time instead of asserting instantly.
        deadline = time.time() + 15
        alive = True
        while time.time() < deadline:
            try:
                # os.kill with signal 0 raises if the process is gone.
                os.kill(worker_pid, 0)
            except (ProcessLookupError, PermissionError, OSError):
                alive = False
                break
            time.sleep(0.3)
        self.assertFalse(alive, "worker survived its parent being killed")

    def test_unknown_worker_restart_raises(self):
        supervisor = RuntimeSupervisor([])
        with self.assertRaises(KeyError):
            supervisor.restart("nope")


if __name__ == "__main__":
    unittest.main()
