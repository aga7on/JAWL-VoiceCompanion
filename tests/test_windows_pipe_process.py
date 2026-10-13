"""Real Windows checks for atomic binary stdio pipes."""
import ctypes
import json
import sys
import unittest
from unittest.mock import Mock, patch

from jawl_voicecompanion import windows_process as module
from jawl_voicecompanion.supervisor import _close_windows_job, _windows_job_object


@unittest.skipUnless(sys.platform == 'win32', 'documented Windows Job and pipe APIs')
class WindowsPipeProcessTests(unittest.TestCase):
    def _job(self):
        job = _windows_job_object()
        self.assertIsNotNone(job)
        tracked = [job]

        def cleanup():
            if tracked[0]:
                _close_windows_job(tracked[0])

        self.addCleanup(cleanup)
        return job, tracked

    def test_unicode_json_line_and_pcm_roundtrip(self):
        job, _ = self._job()
        pcm = bytes((0, 255, 10, 13, 128, 1, 254, 0, 42))
        code = (
            'import json,sys; '
            'header=sys.stdin.buffer.readline(); '
            'request=json.loads(header.decode("utf-8")); '
            'payload=sys.stdin.buffer.read(request["pcm_bytes"]); '
            'sys.stdout.buffer.write(json.dumps({"text":request["text"],"pcm_bytes":len(payload)},'
            'ensure_ascii=False).encode("utf-8")+b"\\n"); '
            'sys.stdout.buffer.write(payload); sys.stdout.buffer.flush()'
        )
        process = module.create_job_process([sys.executable, '-B', '-c', code], job,
                                            pipe_stdio=True, bufsize=0)
        self.assertIsNone(process.stderr)
        self.assertFalse(process.stdin.closed)
        self.assertFalse(process.stdout.closed)
        request = json.dumps({'text': 'мята — привет 🫖', 'pcm_bytes': len(pcm)},
                             ensure_ascii=False).encode('utf-8') + b'\n'
        process.stdin.write(request)
        process.stdin.write(pcm)
        process.stdin.flush()
        response = json.loads(process.stdout.readline().decode('utf-8'))
        self.assertEqual(response, {'text': 'мята — привет 🫖', 'pcm_bytes': len(pcm)})
        self.assertEqual(process.stdout.read(len(pcm)), pcm)
        process.stdin.close()
        self.assertEqual(process.wait(5), 0)

    def test_job_cancel_closes_inherited_descendant_pipe_writer(self):
        job, tracked = self._job()
        code = (
            'import subprocess,sys,time; '
            'subprocess.Popen([sys.executable,"-B","-c","import time;time.sleep(60)"]); '
            'sys.stdout.write("ready\\n");sys.stdout.flush();time.sleep(60)'
        )
        process = module.create_job_process([sys.executable, '-B', '-c', code], job,
                                            pipe_stdio=True, bufsize=-1)
        self.assertEqual(process.stdout.readline().rstrip(), b'ready')
        _close_windows_job(tracked[0])
        tracked[0] = None
        self.assertEqual(process.stdout.read(), b'')  # descendant's inherited writer is gone too
        self.assertIsNotNone(process.wait(5))

    def test_wrapper_failure_terminates_pipe_child_and_closes_pipe_handles(self):
        job, _ = self._job()
        api = Mock(wraps=module._kernel())
        real_create = api.CreateProcessW._mock_wraps
        created = {}

        def create(*args):
            result = real_create(*args)
            if result:
                created['pid'] = int(args[-1]._obj.pid)
            return result

        api.CreateProcessW.side_effect = create
        with (patch.object(module, '_kernel', return_value=api),
              patch.object(module, 'WindowsJobProcess', side_effect=OSError('fixture wrapper failure')),
              self.assertRaisesRegex(OSError, 'fixture wrapper failure')):
            module.create_job_process(
                [sys.executable, '-B', '-c', 'import time;time.sleep(60)'], job,
                pipe_stdio=True, bufsize=0)

        api.CreateProcessW.assert_called_once()
        api.TerminateProcess.assert_called_once()
        api.WaitForSingleObject.assert_called_once()
        api.DeleteProcThreadAttributeList.assert_called_once()
        # Thread, process, NUL, and child endpoints use CloseHandle; CRT closes
        # the two parent endpoints after ownership has transferred to streams.
        self.assertEqual(api.CloseHandle.call_count, 5)
        self.assertIn('pid', created)


if __name__ == '__main__':
    unittest.main()
