"""RuntimeSupervisor tests: real subprocesses, real probes, real teardown.

No mocks of process lifecycle: workers are actual `python -c` processes,
health is a real socket/HTTP probe, and a "dead" worker is a process that
exits. This is the ADR-041 stage 2 slice.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec

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

    def test_killing_the_parent_reaps_workers_on_windows(self):
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