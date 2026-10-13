"""Atomic Windows worker creation, error cleanup and handle-only lifecycle."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from jawl_voicecompanion import windows_process as module
from jawl_voicecompanion.supervisor import _windows_job_object, _close_windows_job


class WindowsProcessContracts(unittest.TestCase):
    def test_identical_case_aliases_are_deduplicated_for_native_launchers(self):
        block = module._environment({'NO_PROXY': '*', 'no_proxy': '*'})
        self.assertEqual(block[:], 'NO_PROXY=*\0\0\0')

    def test_unavailable_platform_or_job_never_falls_back_to_popen(self):
        with patch.object(module.sys, 'platform', 'linux'), patch.object(module, '_kernel') as kernel:
            with self.assertRaises(OSError):
                module.create_job_process(['fixture'], 1)
            kernel.assert_not_called()
        with self.assertRaises(OSError):
            module.create_job_process(['fixture'], None)

    def test_environment_is_unicode_sorted_and_redacts_invalid_values(self):
        self.assertIsNone(module._environment(None))
        self.assertEqual(module._environment({'Z': 'мята', 'a': 'one'})[:], 'a=one\0Z=мята\0\0\0')
        for env in ({'X\0': 'fixture-secret'}, {'PATH': 'one', 'Path': 'two'}):
            with self.subTest(env=list(env)), self.assertRaises(OSError) as caught:
                module._environment(env)
            self.assertNotIn('fixture-secret', str(caught.exception))

    def test_real_exit259_is_not_misreported_as_still_active(self):
        api = Mock()
        api.WaitForSingleObject.return_value = 0
        def exit_code(_handle, pointer):
            pointer._obj.value = 259
            return True
        api.GetExitCodeProcess.side_effect = exit_code
        process = module.WindowsJobProcess(api, 123, 456, ['fixture'])
        self.assertEqual(process.poll(), 259)
        self.assertEqual(process.wait(.01), 259)
        process.kill()
        api.TerminateProcess.assert_not_called()

    def test_wait_timeout_does_not_terminate_a_running_process(self):
        api = Mock()
        api.WaitForSingleObject.return_value = 258
        process = module.WindowsJobProcess(api, 123, 456, ['fixture'])
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(.01)
        api.TerminateProcess.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'documented Windows Job API')
class WindowsProcessNativeTests(unittest.TestCase):
    def _job(self):
        job = _windows_job_object()
        self.assertIsNotNone(job)
        self.addCleanup(_close_windows_job, job)
        return job

    def test_unicode_cwd_and_environment_roundtrip_without_a_console(self):
        job = self._job()
        with tempfile.TemporaryDirectory(prefix='jawl-job-') as temp:
            cwd = Path(temp) / 'мятная папка'
            cwd.mkdir()
            env = dict(os.environ, JAWL_TEST_UNICODE='привет')
            command = [sys.executable, '-B', '-c',
                       "import os;from pathlib import Path;Path('result.txt').write_text(os.environ['JAWL_TEST_UNICODE'],encoding='utf-8')"]
            process = module.create_job_process(command, job, cwd=cwd, env=env)
            self.assertEqual(process.wait(5), 0)
            self.assertEqual((cwd / 'result.txt').read_text(encoding='utf-8'), 'привет')

    def test_job_attribute_failure_closes_temporary_handles_without_launch(self):
        job = self._job()
        api = Mock(wraps=module._kernel())
        real_update = api.UpdateProcThreadAttribute._mock_wraps
        def update(*args):
            if args[2] == 0x2000D:
                raise OSError('fixture unsupported JOB_LIST')
            return real_update(*args)
        api.UpdateProcThreadAttribute.side_effect = update
        with patch.object(module, '_kernel', return_value=api), self.assertRaises(OSError):
            module.create_job_process([sys.executable, '-c', 'pass'], job)
        api.CreateProcessW.assert_not_called()
        api.DeleteProcThreadAttributeList.assert_called_once()
        api.CloseHandle.assert_called_once()

    def test_create_failure_does_not_retry_or_leak_attribute_handles(self):
        job = self._job()
        api = Mock(wraps=module._kernel())
        def failed_create(*_args):
            ctypes.set_last_error(5)
            return False
        api.CreateProcessW.side_effect = failed_create
        with patch.object(module, '_kernel', return_value=api), self.assertRaises(OSError):
            module.create_job_process([sys.executable, '-c', 'pass'], job)
        api.CreateProcessW.assert_called_once()
        api.DeleteProcThreadAttributeList.assert_called_once()
        api.CloseHandle.assert_called_once()

    def test_wrapper_failure_reaps_created_handle_before_returning_error(self):
        job = self._job()
        api = Mock(wraps=module._kernel())
        with (patch.object(module, '_kernel', return_value=api),
              patch.object(module, 'WindowsJobProcess', side_effect=OSError('fixture constructor failure')),
              self.assertRaises(OSError)):
            module.create_job_process([sys.executable, '-B', '-c', 'import time;time.sleep(10)'], job)
        api.TerminateProcess.assert_called_once()
        api.WaitForSingleObject.assert_called_once()
        api.DeleteProcThreadAttributeList.assert_called_once()
        self.assertEqual(api.CloseHandle.call_count, 3)  # primary thread, process, own NUL


if __name__ == '__main__':
    unittest.main()
