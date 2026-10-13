"""Read-only containment proof; real cheap Windows venv redirector, no model."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from jawl_voicecompanion import supervisor as module
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec


class SupervisorOwnershipTests(unittest.TestCase):
    def test_invalid_pid_and_closed_job_fail_closed(self):
        supervisor = RuntimeSupervisor([])
        try:
            for value in (True, None, 0, -1, "123", 2**32):
                self.assertFalse(supervisor.owns_pid(value))
        finally:
            supervisor.stop()
        self.assertFalse(supervisor.owns_pid(os.getpid()))

    @unittest.skipUnless(sys.platform == "win32", "Windows Job query")
    def test_query_failure_cannot_prove_ownership(self):
        supervisor = RuntimeSupervisor([])
        try:
            with patch.object(module, "_pid_in_windows_job", side_effect=OSError("fixture")):
                self.assertFalse(supervisor.owns_pid(os.getpid()))
        finally:
            supervisor.stop()

    @unittest.skipUnless(sys.platform == "win32", "Windows venv redirector + Job")
    def test_real_venv_descendant_is_owned_but_foreign_process_is_not(self):
        interpreter = Path(r"G:\AI\tts_env\Scripts\python.exe")
        if not interpreter.is_file():
            self.skipTest("local venv interpreter is not installed")
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        program = (
            "import http.server, os\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n"
            "  b=str(os.getpid()).encode(); self.send_response(200); "
            "self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)\n"
            " def log_message(self,*a): pass\n"
            f"http.server.HTTPServer(('127.0.0.1',{port}),H).serve_forever()\n"
        )
        opener = build_opener(ProxyHandler({})).open
        observed = []
        def health():
            with opener(f"http://127.0.0.1:{port}/", timeout=0.3) as response:
                observed.append(int(response.read(32)))
            return True
        supervisor = RuntimeSupervisor([WorkerSpec(
            "venv", [str(interpreter), "-B", "-c", program], health,
            startup_timeout_seconds=5, max_restarts=0, stop_timeout_seconds=1,
        )])
        foreign = subprocess.Popen([sys.executable, "-B", "-c", "import time;time.sleep(10)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            startup = supervisor.start()
            self.assertTrue(startup.ok)
            root_pid = startup.worker_summary("venv")["pid"]
            child_pid = observed[-1]
            self.assertTrue(supervisor.owns_pid(root_pid))
            self.assertTrue(supervisor.owns_pid(child_pid))
            self.assertFalse(supervisor.owns_pid(foreign.pid))
            self.assertFalse(supervisor.owns_pid(os.getpid()))
            supervisor.stop()
            self.assertFalse(supervisor.owns_pid(child_pid))
            # Windows Job termination is asynchronous. Prove actual listener
            # release within a bound, not by the now-closed Job handle alone.
            deadline = time.monotonic() + 1
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        pass
                except OSError:
                    break
                self.assertLess(time.monotonic(), deadline, "owned descendant listener survived Stop")
                time.sleep(0.02)
            self.assertIsNone(foreign.poll(), "owned Stop must not affect a foreign process")
        finally:
            supervisor.stop()
            foreign.terminate()
            foreign.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
