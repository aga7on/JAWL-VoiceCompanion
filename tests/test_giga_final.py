import subprocess
import sys
import threading
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.giga_final import (  # noqa: E402
    CrispASRFileTranscriber,
    GigaAMBatchError,
    GigaAMBatchCancelled,
)
from jawl_voicecompanion import giga_final as giga_final_module  # noqa: E402
from jawl_voicecompanion.asr import UtteranceBuffer  # noqa: E402
from jawl_voicecompanion.owned_pipe import spawn_owned_worker  # noqa: E402


class CrispASRFileTranscriberTests(unittest.TestCase):
    class IsSetOnlyEvent(threading.Event):
        def wait(self, timeout=None):
            raise AssertionError("transcribe must poll is_set(), not call wait()")

    def _python_child_launcher(self, records, started=None):
        # Replace only the executable under test. The real factory still creates
        # the owned Job/process wrapper, so these fixtures exercise containment.
        real_spawn = spawn_owned_worker
        lock = threading.Lock()

        def launch(command):
            wav_path = Path(command[-1])
            marker = wav_path.read_bytes()
            if marker.startswith(b"RIFF"):
                marker = b"cancel"
            out_base = command[command.index("-of") + 1]
            delay, exit_code, write_json = {
                b"cancel": (30, 0, False),
                b"timeout": (30, 0, False),
                b"failure": (0, 7, True),
                b"large-json": (0, 0, 2),
                b"bad-shape": (0, 0, 3),
                b"slow-a": (30, 0, False),
                b"fast-b": (0.2, 0, True),
            }[marker]
            child_code = (
                "import json,sys,time; "
                "out,delay,code,write=sys.argv[1:]; time.sleep(float(delay)); "
                "body={'transcription':[{'text':'x'*300000 if write=='2' else "
                "(2 if write=='3' else 'child transcript')} ]}; "
                "open(out+'.json','w',encoding='utf-8').write(json.dumps(body)) if write!='0' else None; "
                "sys.exit(int(code))"
            )
            process = real_spawn(
                [sys.executable, "-c", child_code, out_base, str(delay), str(exit_code), str(int(write_json))]
            )
            with lock:
                records[marker] = (process, Path(out_base))
            if started is not None and marker in started:
                started[marker].set()
            return process

        return launch

    @staticmethod
    def _windows_process_is_running(pid):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: process has exited
                return False
            raise ctypes.WinError(error)
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)

    def test_prefetch_reads_the_whole_model_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.gguf"
            model.write_bytes(b"x" * 300_000)
            transcriber = CrispASRFileTranscriber("crispasr.exe", str(model))
            self.assertEqual(transcriber.prefetch(chunk_bytes=65_536), 300_000)
            missing = CrispASRFileTranscriber("crispasr.exe", str(Path(tmp) / "missing.gguf"))
            self.assertEqual(missing.prefetch(), 0)

    def test_missing_executable_raises_batch_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.gguf"
            model.write_bytes(b"x")
            transcriber = CrispASRFileTranscriber(str(Path(tmp) / "no-such-crispasr.exe"), str(model))
            with self.assertRaises(GigaAMBatchError):
                transcriber.transcribe(b"RIFF....WAVE")

    def test_pre_cancelled_call_does_not_spawn(self):
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        cancelled = threading.Event()
        cancelled.set()
        with patch("jawl_voicecompanion.giga_final.spawn_owned_worker") as spawn:
            with self.assertRaises(GigaAMBatchCancelled):
                transcriber.transcribe(b"audio", cancel_event=cancelled)
        spawn.assert_not_called()

    def test_cancellation_stops_and_reaps_its_child_before_temp_cleanup(self):
        records = {}
        event = self.IsSetOnlyEvent()
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        timer = threading.Timer(0.2, event.set)
        with patch(
            "jawl_voicecompanion.giga_final.spawn_owned_worker",
            side_effect=self._python_child_launcher(records),
        ):
            timer.start()
            try:
                with self.assertRaises(GigaAMBatchCancelled):
                    transcriber.transcribe(b"cancel", cancel_event=event)
            finally:
                timer.cancel()
                timer.join()
        process, out_base = records[b"cancel"]
        self.assertIsNotNone(process.poll())
        self.assertFalse(out_base.parent.exists())

    def test_timeout_stops_and_reaps_its_child(self):
        records = {}
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        transcriber.timeout_seconds = 0.15
        with patch(
            "jawl_voicecompanion.giga_final.spawn_owned_worker",
            side_effect=self._python_child_launcher(records),
        ):
            with self.assertRaisesRegex(GigaAMBatchError, "timed out"):
                transcriber.transcribe(b"timeout")
        process, out_base = records[b"timeout"]
        self.assertIsNotNone(process.poll())
        self.assertFalse(out_base.parent.exists())

    def test_buffer_discard_reaps_the_actual_owned_child(self):
        records = {}
        started = {b"cancel": threading.Event()}
        buffer = UtteranceBuffer(CrispASRFileTranscriber("crispasr.exe", "model"))
        buffer.feed_audio(b"\x01\x00" * 32, sample_rate=16000, channels=1, session_id="s")
        results = []
        worker = threading.Thread(target=lambda: results.append(buffer.finish("s")))
        with patch(
            "jawl_voicecompanion.giga_final.spawn_owned_worker",
            side_effect=self._python_child_launcher(records, started),
        ):
            try:
                worker.start()
                self.assertTrue(started[b"cancel"].wait(2))
                self.assertEqual(buffer.discard("s")["status"], "cancelled")
                worker.join(3)
                self.assertFalse(worker.is_alive())
            finally:
                buffer.close()
                worker.join(3)
        self.assertEqual(results[0]["status"], "cancelled")
        process, out_base = records[b"cancel"]
        self.assertIsNotNone(process.poll())
        self.assertFalse(out_base.parent.exists())

    def test_nonzero_child_exit_cannot_succeed_with_valid_json(self):
        records = {}
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        with patch(
            "jawl_voicecompanion.giga_final.spawn_owned_worker",
            side_effect=self._python_child_launcher(records),
        ) as spawn:
            with self.assertRaises(GigaAMBatchError):
                transcriber.transcribe(b"failure")
        spawn.assert_called_once()
        self.assertIsNotNone(records[b"failure"][0].poll())

    @unittest.skipUnless(sys.platform == "win32", "owned worker Job containment is Windows-specific")
    def test_success_reaps_grandchild_before_temporary_files_are_removed(self):
        records = {}
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        with tempfile.TemporaryDirectory() as fixture_root:
            fixture_root = Path(fixture_root)
            pid_path = fixture_root / "grandchild.pid"
            ready_path = fixture_root / "grandchild.ready"
            lock_path = fixture_root / "held-open.tmp"

            def launch(command):
                out_base = command[command.index("-of") + 1]
                grandchild_code = (
                    "import pathlib,sys,time; "
                    "handle=open(sys.argv[1],'w'); "
                    "pathlib.Path(sys.argv[2]).write_text('ready'); "
                    "time.sleep(30)"
                )
                root_code = (
                    "import json,pathlib,subprocess,sys,time\n"
                    "out,pid_file,ready_file,lock_file=sys.argv[1:]\n"
                    "child=subprocess.Popen([sys.executable,'-c',"
                    + repr(grandchild_code)
                    + ",lock_file,ready_file])\n"
                    "pathlib.Path(pid_file).write_text(str(child.pid))\n"
                    "deadline=time.monotonic()+5\n"
                    "while not pathlib.Path(ready_file).exists() and time.monotonic()<deadline:\n"
                    "    time.sleep(.01)\n"
                    "if not pathlib.Path(ready_file).exists(): raise SystemExit(9)\n"
                    "pathlib.Path(out+'.json').write_text(json.dumps({'transcription':[{'text':'child transcript'}]}))\n"
                )
                process = spawn_owned_worker(
                    [sys.executable, "-c", root_code, out_base, str(pid_path), str(ready_path), str(lock_path)]
                )
                records["root"] = (process, Path(out_base))
                return process

            try:
                with patch("jawl_voicecompanion.giga_final.spawn_owned_worker", side_effect=launch):
                    self.assertEqual(transcriber.transcribe(b"audio"), "child transcript")

                process, out_base = records["root"]
                descendant_pid = int(pid_path.read_text(encoding="utf-8"))
                self.assertEqual(process.poll(), 0)
                self.assertFalse(out_base.parent.exists(), "temporary files were not cleaned up")
                self.assertFalse(self._windows_process_is_running(descendant_pid))
            finally:
                # Keep a failing regression run from leaving its owned tree behind.
                if "root" in records and pid_path.exists():
                    if self._windows_process_is_running(int(pid_path.read_text(encoding="utf-8"))):
                        process = records["root"][0]
                        process.terminate()
                        process.wait(timeout=3)

    def test_teardown_failure_retains_only_task_audio_directory(self):
        processes = []
        workspaces = []
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        real_spawn = spawn_owned_worker
        real_stop_and_reap = giga_final_module._stop_and_reap
        real_mkdtemp = tempfile.mkdtemp

        def launch(command):
            process = real_spawn([sys.executable, "-c", "import time; time.sleep(30)"])
            processes.append(process)
            return process

        def record_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            workspaces.append(Path(path))
            return path

        try:
            with (
                patch("jawl_voicecompanion.giga_final.spawn_owned_worker", side_effect=launch),
                patch("jawl_voicecompanion.giga_final.tempfile.mkdtemp", side_effect=record_mkdtemp),
                patch("jawl_voicecompanion.giga_final._stop_and_reap", side_effect=OSError("injected drain failure")),
            ):
                with self.assertRaisesRegex(GigaAMBatchError, "temporary audio retained"):
                    transcriber.transcribe(b"audio")

            self.assertEqual(len(workspaces), 1)
            retained = workspaces[0]
            self.assertTrue(retained.is_dir())
            self.assertEqual({path.name for path in retained.iterdir()}, {"utterance.wav"})
        finally:
            for process in processes:
                real_stop_and_reap(process)
            for workspace in workspaces:
                if workspace.exists():
                    shutil.rmtree(workspace)

    def test_transcript_json_size_and_shape_are_bounded(self):
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        for marker, expected_message in (
            (b"large-json", "too large"),
            (b"bad-shape", "shape is invalid"),
        ):
            with self.subTest(marker=marker), patch(
                "jawl_voicecompanion.giga_final.spawn_owned_worker",
                side_effect=self._python_child_launcher({}),
            ):
                with self.assertRaisesRegex(GigaAMBatchError, expected_message):
                    transcriber.transcribe(marker)

    def test_cancelling_one_call_does_not_stop_a_concurrent_call(self):
        records = {}
        started = {b"slow-a": threading.Event(), b"fast-b": threading.Event()}
        cancel_a = threading.Event()
        transcriber = CrispASRFileTranscriber("crispasr.exe", "model")
        outcomes = {}

        def run_a():
            try:
                outcomes["a"] = transcriber.transcribe(b"slow-a", cancel_event=cancel_a)
            except Exception as exc:  # captured for assertions in the main test thread
                outcomes["a"] = exc

        def run_b():
            try:
                outcomes["b"] = transcriber.transcribe(b"fast-b")
            except Exception as exc:  # captured for assertions in the main test thread
                outcomes["b"] = exc

        with patch(
            "jawl_voicecompanion.giga_final.spawn_owned_worker",
            side_effect=self._python_child_launcher(records, started),
        ):
            thread_a = threading.Thread(target=run_a)
            thread_a.start()
            self.assertTrue(started[b"slow-a"].wait(2))
            thread_b = threading.Thread(target=run_b)
            thread_b.start()
            self.assertTrue(started[b"fast-b"].wait(2))
            cancel_a.set()
            thread_a.join(3)
            thread_b.join(3)

        self.assertFalse(thread_a.is_alive())
        self.assertFalse(thread_b.is_alive())
        self.assertIsInstance(outcomes["a"], GigaAMBatchCancelled)
        self.assertEqual(outcomes["b"], "child transcript")
        for process, _ in records.values():
            self.assertIsNotNone(process.poll())


if __name__ == "__main__":
    unittest.main()
