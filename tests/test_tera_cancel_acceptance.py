"""Cheap harness safety tests: no Tera weights or model worker starts."""
import importlib.util
import io
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch
import wave

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_tera_cancel_acceptance.py"
spec = importlib.util.spec_from_file_location("tera_cancel_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
from jawl_voicecompanion.tts import split_sentences


class TeraProbeSafetyTests(unittest.TestCase):
    def test_low_ram_skips_before_manifest_or_spawn(self):
        report = {}
        with patch.object(probe, "free_ram", return_value=3 * probe.GIB), \
             patch.object(probe, "load_runtime_manifest") as manifest, \
             patch.object(probe, "RuntimeSupervisor") as supervisor:
            probe.probe(report, Path("unused.json"))
        self.assertEqual(report["status"], "skipped")
        manifest.assert_not_called()
        supervisor.assert_not_called()

    def test_guard_stops_owned_callback_and_joins(self):
        called = threading.Event()
        owned_processes = {1234}

        def stop_owned_supervisor():
            owned_processes.clear()
            called.set()

        with patch.object(probe, "free_ram", side_effect=[3 * probe.GIB, probe.GIB]):
            guard = probe.RamGuard(stop_owned_supervisor, floor=2 * probe.GIB)
            guard.thread.start()
            self.assertTrue(called.wait(1))
            guard.close()
        self.assertEqual(guard.reason, "ram_floor")
        self.assertEqual(guard.minimum, probe.GIB)
        self.assertFalse(guard.thread.is_alive())
        self.assertFalse(owned_processes, "guard must stop its owned process")
        with self.assertRaises(RuntimeError):
            guard.check()

    def test_guard_retriggers_supervisor_stop_until_close(self):
        second_signal = threading.Event()
        signals = []

        def stop_owned_supervisor():
            signals.append(time.monotonic())
            if len(signals) >= 2:
                second_signal.set()

        with patch.object(probe, "free_ram", return_value=probe.GIB):
            guard = probe.RamGuard(stop_owned_supervisor, floor=2 * probe.GIB)
            guard.thread.start()
            self.assertTrue(second_signal.wait(1), "guard should re-signal supervisor.stop")
            guard.close()

        self.assertGreaterEqual(len(signals), 2)
        self.assertFalse(guard.thread.is_alive(), "close must stop guard re-signalling")

    def test_listener_ownership_mismatch_skips_inference_and_stops_supervisor(self):
        startup = Mock(ok=True)
        startup.worker_summary.return_value = {"pid": 4321}
        supervisor = Mock()
        supervisor.owns_pid.return_value = False
        supervisor.start.return_value = startup
        supervisor.health.return_value = Mock(workers={"tera-probe": "stopped"})
        service = Mock()
        guard = Mock()
        guard.reason = None
        guard.stop_error = None
        guard.minimum = 5 * probe.GIB
        guard.thread = Mock()
        models = {"tera_python": Path(__file__), "tera_release": Path(__file__).parent}

        with patch.object(probe, "free_ram", return_value=5 * probe.GIB), \
             patch.object(probe, "load_runtime_manifest", return_value={"models": models}), \
             patch.object(probe, "RuntimeSupervisor", return_value=supervisor), \
             patch.object(probe, "RamGuard", return_value=guard), \
             patch.object(probe, "ResourceGovernor"), \
             patch.object(probe, "TTSService", return_value=service), \
             patch.object(probe, "listener_pids", side_effect=[{9999}, set()]) as listeners:
            report = {}
            with self.assertRaisesRegex(RuntimeError, "listener ownership"):
                probe.probe(report, Path("unused.json"))

        service.stream.assert_not_called()
        supervisor.stop.assert_called_once_with()
        guard.close.assert_called_once_with()
        self.assertEqual(listeners.call_count, 2)
        self.assertTrue(report["owned_listener_gone"])

    def test_startup_failure_still_closes_service_and_stops_supervisor(self):
        startup = Mock(ok=False, workers={"tera-probe": "failed"})
        supervisor = Mock()
        supervisor.start.return_value = startup
        supervisor.health.return_value = Mock(workers={"tera-probe": "stopped"})
        service = Mock()
        guard = Mock()
        guard.reason = None
        guard.stop_error = None
        guard.minimum = 5 * probe.GIB
        guard.thread = Mock()
        models = {"tera_python": Path(__file__), "tera_release": Path(__file__).parent}

        with patch.object(probe, "free_ram", return_value=5 * probe.GIB), \
             patch.object(probe, "load_runtime_manifest", return_value={"models": models}), \
             patch.object(probe, "RuntimeSupervisor", return_value=supervisor), \
             patch.object(probe, "RamGuard", return_value=guard), \
             patch.object(probe, "ResourceGovernor"), \
             patch.object(probe, "TTSService", return_value=service), \
             patch.object(probe, "listener_pids") as listeners:
            report = {}
            with self.assertRaisesRegex(RuntimeError, "did not start"):
                probe.probe(report, Path("unused.json"))

        service.close.assert_called_once_with()
        service.stream.assert_not_called()
        supervisor.stop.assert_called_once_with()
        guard.close.assert_called_once_with()
        listeners.assert_not_called()

    def test_guard_memory_accounting_failure_stops(self):
        called = threading.Event()
        with patch.object(probe, "free_ram", side_effect=[3 * probe.GIB, OSError()]):
            guard = probe.RamGuard(called.set, floor=probe.GIB)
            guard.thread.start()
            self.assertTrue(called.wait(1))
            guard.close()
        self.assertEqual(guard.reason, "ram_accounting_failed")

    def test_stop_failure_does_not_skip_other_cleanup(self):
        supervisor = Mock()
        supervisor.start.return_value = Mock(ok=False, workers={})
        supervisor.stop.side_effect = OSError("fixture stop failure")
        supervisor.health.return_value = Mock(workers={})
        service = Mock()
        service.close.side_effect = OSError("fixture service failure")
        guard = Mock(reason=None, stop_error=None, minimum=5 * probe.GIB)
        models = {"tera_python": Path(__file__), "tera_release": Path(__file__).parent}
        with patch.object(probe, "free_ram", return_value=5 * probe.GIB), \
             patch.object(probe, "load_runtime_manifest", return_value={"models": models}), \
             patch.object(probe, "RuntimeSupervisor", return_value=supervisor), \
             patch.object(probe, "RamGuard", return_value=guard), \
             patch.object(probe, "TTSService", return_value=service):
            report = {}
            with self.assertRaisesRegex(RuntimeError, "did not start"):
                probe.probe(report, Path("unused.json"))
        guard.close.assert_called_once_with()
        supervisor.health.assert_called_once_with()
        self.assertEqual(report["reason"], "cleanup_error")
        self.assertEqual([error["stage"] for error in report["cleanup_errors"]],
                         ["service_close", "supervisor_stop"])

    def test_guard_retries_failed_owned_stop_and_joins(self):
        stopped = threading.Event()
        calls = []
        def stop():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("fixture")
            stopped.set()
        with patch.object(probe, "free_ram", return_value=probe.GIB):
            guard = probe.RamGuard(stop, floor=2 * probe.GIB)
            guard.thread.start()
            self.assertTrue(stopped.wait(1))
            guard.close()
        self.assertEqual(guard.stop_error, "OSError")
        self.assertFalse(guard.thread.is_alive())

    def test_guard_deadline_stops(self):
        called = threading.Event()
        with patch.object(probe, "free_ram", return_value=3 * probe.GIB):
            guard = probe.RamGuard(called.set, floor=probe.GIB, seconds=0)
            guard.thread.start()
            self.assertTrue(called.wait(1))
            guard.close()
        self.assertEqual(guard.reason, "probe_deadline")

    def test_wav_must_be_pcm16_nonempty_and_nonsilent(self):
        def wav_data(raw, channels=1, width=2):
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(width)
                wav.setframerate(24000)
                wav.writeframes(raw)
            return output.getvalue()
        info = probe.wav_info(wav_data(b"\xff\x1f\x01\xe0" * 100))
        self.assertGreater(info["rms"], 0)
        self.assertEqual(info["sample_rate"], 24000)
        for invalid in (b"", wav_data(b""), wav_data(b"\0\0" * 10),
                        wav_data(b"\x11\x22" * 10, channels=2)):
            with self.subTest(size=len(invalid)), self.assertRaises(ValueError):
                probe.wav_info(invalid)

    def test_wait_is_bounded_and_guard_is_checked(self):
        class Guard:
            done = threading.Event()
            def check(self):
                pass
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            probe.wait_until(lambda: False, Guard(), 0.05)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_short_inputs_are_single_service_chunks(self):
        for text in probe.TEXTS:
            self.assertEqual(len(split_sentences(text)), 1)


if __name__ == "__main__":
    unittest.main()
