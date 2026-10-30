import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.companion_runtime import CompanionRuntime  # noqa: E402
from jawl_voicecompanion.sensory_history import SensoryHistoryStore  # noqa: E402


class _Closable:
    def __init__(self):
        self.calls = []

    def serve_forever(self):
        self.calls.append("serve")

    def shutdown(self):
        self.calls.append("shutdown")

    def server_close(self):
        self.calls.append("close")


class _StubbornControl:
    def __init__(self):
        self.close_calls = 0

    def server_close(self):
        self.close_calls += 1
        if self.close_calls == 1:
            raise RuntimeError("control close failed")


class _History:
    def __init__(self, calls, *, fail_once=False):
        self.calls = calls
        self.fail_once = fail_once

    def flush(self):
        self.calls.append("history_flush")
        if self.fail_once:
            self.fail_once = False
            return {"last_error": "history_write_failed:OSError"}


class _ControlWithHistory(_Closable):
    def __init__(self, *, fail_flush_once=False):
        super().__init__()
        self.sensory_history = _History(self.calls, fail_once=fail_flush_once)


class CompanionRuntimeTests(unittest.TestCase):
    def test_close_is_idempotent(self):
        control = _Closable()
        runtime = CompanionRuntime(control)

        runtime.close()
        runtime.close()

        self.assertEqual(control.calls, ["close"])

    def test_serve_after_close_fails(self):
        runtime = CompanionRuntime(_Closable())
        runtime.close()
        with self.assertRaises(RuntimeError):
            runtime.serve_forever()

    def test_close_flushes_sensory_history_after_stopping_capture_owners(self):
        control = _ControlWithHistory()
        runtime = CompanionRuntime(control)

        runtime.close()
        runtime.close()

        self.assertEqual(control.calls, ["close", "history_flush"])

    def test_failed_sensory_history_flush_is_reported_and_retried(self):
        control = _ControlWithHistory(fail_flush_once=True)
        runtime = CompanionRuntime(control)

        with self.assertRaisesRegex(OSError, "history_write_failed:OSError"):
            runtime.close()
        runtime.close()

        self.assertEqual(control.calls, ["close", "history_flush", "history_flush"])

    def test_close_persists_unflushed_observation_for_next_runtime(self):
        import time
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as directory:
            path = Path(directory) / "weekly-history.json"
            history = SensoryHistoryStore(path, enabled=True, flush_interval_seconds=60)
            history.record(
                "visual", "A new game scene appears", observed_at=time.time(),
                scene_id="scene-7", source="screen:test",
            )
            control = _Closable()
            control.sensory_history = history

            CompanionRuntime(control).close()

            reopened = SensoryHistoryStore(path, enabled=True)
            self.assertIn("A new game scene appears", reopened.context_text())

    def test_failed_control_close_stays_retryable(self):
        control = _StubbornControl()
        runtime = CompanionRuntime(control)
        with self.assertRaises(RuntimeError):
            runtime.close()
        runtime.close()
        self.assertEqual(control.close_calls, 2)


if __name__ == "__main__":
    unittest.main()
