"""Real Windows lifecycle checks for the owned binary-pipe wrapper."""
import ctypes
import json
import os
import subprocess
import sys
import threading
import unittest
from ctypes import wintypes
from unittest.mock import patch

from jawl_voicecompanion import supervisor
from jawl_voicecompanion.owned_pipe import spawn_owned_pipe


@unittest.skipUnless(sys.platform == 'win32', 'owned PIPE containment uses Windows Jobs')
class OwnedPipeTests(unittest.TestCase):
    def _spawn(self, code, *, env=None, bufsize=0):
        process = spawn_owned_pipe([sys.executable, '-B', '-c', code],
                                   env=env, bufsize=bufsize)
        self.addCleanup(self._cleanup_process, process)
        return process

    @staticmethod
    def _cleanup_process(process):
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass
        for name in ('stdin', 'stdout'):
            stream = getattr(process, name, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def _bounded_read(self, process, read, timeout=5):
        result, failure = [], []

        def run():
            try:
                result.append(read())
            except BaseException as exc:
                failure.append(exc)

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        reader.join(timeout)
        if reader.is_alive():
            try:
                process.terminate()
                process.wait(timeout=5)
            finally:
                reader.join(1)
            self.fail(f'pipe read did not finish within {timeout}s')
        if failure:
            raise failure[0]
        return result[0]

    @staticmethod
    def _process_wait_handle(pid):
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return kernel32, handle

    def _assert_signaled(self, process_handle, timeout_ms=5000):
        kernel32, handle = process_handle
        self.assertEqual(kernel32.WaitForSingleObject(handle, timeout_ms), 0,
                         'owned descendant did not exit before the bounded deadline')

    def test_unicode_json_and_environment_roundtrip(self):
        expected_text = 'мята — привет 🫖'
        expected_env = 'окружение: ёжик 🌿'
        env = dict(os.environ, JAWL_OWNED_PIPE_TEXT=expected_env)
        code = (
            'import json,os,sys; '
            'request=json.loads(sys.stdin.buffer.readline().decode("utf-8")); '
            'response={"text":request["text"],"env":os.environ["JAWL_OWNED_PIPE_TEXT"]}; '
            'sys.stdout.buffer.write(json.dumps(response,ensure_ascii=False).encode("utf-8")+b"\\n"); '
            'sys.stdout.buffer.flush()'
        )
        process = self._spawn(code, env=env, bufsize=0)
        process.stdin.write(json.dumps({'text': expected_text}, ensure_ascii=False).encode('utf-8') + b'\n')
        process.stdin.flush()
        response_line = self._bounded_read(process, process.stdout.readline)
        self.assertEqual(json.loads(response_line.decode('utf-8')),
                         {'text': expected_text, 'env': expected_env})
        process.stdin.close()
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertFalse(process.cleanup_pending)

    def test_wait_after_root_exit_kills_descendant_and_reaches_pipe_eof(self):
        code = (
            'import subprocess,sys; '
            'child=subprocess.Popen([sys._base_executable,"-B","-c","import time;time.sleep(60)"]); '
            'print(child.pid,flush=True)'
        )
        process = self._spawn(code, bufsize=0)
        process.stdin.close()
        child_pid = int(self._bounded_read(process, process.stdout.readline).strip())
        retained_handle = self._process_wait_handle(child_pid)
        self.addCleanup(retained_handle[0].CloseHandle, retained_handle[1])

        self.assertEqual(process.wait(timeout=10), 0)
        self._assert_signaled(retained_handle, timeout_ms=0)
        self.assertEqual(self._bounded_read(process, process.stdout.read), b'')
        self.assertFalse(process.cleanup_pending)

    def test_terminate_kills_owned_tree_without_touching_foreign_control(self):
        foreign = subprocess.Popen([sys._base_executable, '-B', '-c', 'import time;time.sleep(60)'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)

        def cleanup_foreign():
            if foreign.poll() is None:
                foreign.terminate()
            foreign.wait(timeout=5)

        self.addCleanup(cleanup_foreign)
        code = (
            'import subprocess,sys,time; '
            'child=subprocess.Popen([sys._base_executable,"-B","-c","import time;time.sleep(60)"]); '
            'print(child.pid,flush=True);time.sleep(60)'
        )
        process = self._spawn(code, bufsize=0)
        child_pid = int(self._bounded_read(process, process.stdout.readline).strip())
        retained_handle = self._process_wait_handle(child_pid)
        self.addCleanup(retained_handle[0].CloseHandle, retained_handle[1])

        process.terminate()
        self.assertIsNotNone(process.wait(timeout=10))
        self._assert_signaled(retained_handle, timeout_ms=0)
        self.assertIsNone(foreign.poll(), 'terminating the owned Job affected a foreign process')

    def test_failed_job_drain_keeps_cleanup_pending_for_retry(self):
        process = self._spawn(
            'import subprocess,sys,time; '
            'p=subprocess.Popen([sys.executable,"-B","-c","import time;time.sleep(60)"]); '
            'print(p.pid,flush=True);time.sleep(60)', bufsize=0)
        child_pid = int(self._bounded_read(process, process.stdout.readline).strip())
        retained_handle = self._process_wait_handle(child_pid)
        self.addCleanup(retained_handle[0].CloseHandle, retained_handle[1])
        process.terminate()
        self.assertTrue(process._wait_handles)
        process.stdin.close()
        real_drain = supervisor._drain_windows_job
        drain_calls = 0

        def fail_once_then_drain(*args, **kwargs):
            nonlocal drain_calls
            drain_calls += 1
            if drain_calls == 1:
                raise OSError('injected drain failure')
            return real_drain(*args, **kwargs)

        with patch.object(supervisor, '_drain_windows_job',
                          side_effect=fail_once_then_drain) as drain:
            with self.assertRaisesRegex(OSError, 'injected drain failure'):
                process.wait(timeout=10)
            self.assertTrue(process.cleanup_pending)
            self.assertTrue(process._wait_handles, 'retry must retain exact descendant wait identities')
            self.assertIsNotNone(process.wait(timeout=5))
            self.assertEqual(drain.call_count, 2)
        self.assertFalse(process.cleanup_pending)
        self.assertEqual(process._wait_handles, [])
        self._assert_signaled(retained_handle, timeout_ms=0)


if __name__ == '__main__':
    unittest.main()
