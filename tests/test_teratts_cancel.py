import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teratts_server as worker
from jawl_voicecompanion.onnx_cancellation import CancellableSession, InferenceCancelled
from jawl_voicecompanion.resources import ResourceGovernor
from jawl_voicecompanion.tts import TeraTTSHttpClient, TTSService, TTSCancelled


def runtime_fixture(*, max_pending=2, queue_timeout=1, request_timeout=2):
    runtime = object.__new__(worker.TeraRuntime)
    runtime.default_voice = "ru_f1"
    runtime.sample_rate = 16000
    runtime._init_lifecycle(max_pending=max_pending, queue_timeout=queue_timeout,
                            request_timeout=request_timeout)
    runtime.entered = threading.Event()
    runtime.release = threading.Event()
    runtime.seen = []
    runtime.options = []

    class Native:
        def run(self, names, feeds, options):
            runtime.options.append(options)
            runtime.seen.append(feeds["text"])
            runtime.entered.set()
            while not runtime.release.wait(0.005):
                if options.terminate:
                    raise RuntimeError("native run terminated")
            return np.ones(160, dtype=np.float32) * 0.2

    runtime._loaded = CancellableSession(Native(), lambda: SimpleNamespace(terminate=False))
    runtime._generate = lambda loaded, text, voice, **kwargs: loaded.run(None, {"text": text})
    return runtime


def begin(runtime, request_id):
    outcome = []
    def synthesize():
        try:
            outcome.append(runtime.synthesize(request_id, None, 1.0, request_id=request_id))
        except Exception as exc:
            outcome.append(exc)
    thread = threading.Thread(target=synthesize, daemon=True)
    thread.start()
    return thread, outcome


class TeraWorkerCancellationTests(unittest.TestCase):
    def test_active_cancel_releases_real_runtime_lock_and_new_request_runs(self):
        runtime = runtime_fixture()
        active, outcome = begin(runtime, "old")
        self.assertTrue(runtime.entered.wait(1))
        runtime.cancel_requests(["old"])
        active.join(1)
        self.assertFalse(active.is_alive())
        self.assertIsInstance(outcome[0], InferenceCancelled)
        self.assertTrue(runtime.options[0].terminate)
        self.assertEqual(runtime.state()["pending"], 0)
        runtime.release.set()
        self.assertTrue(runtime.synthesize("new", None, 1.0, request_id="new").startswith(b"RIFF"))
        self.assertFalse(runtime.options[-1].terminate)

    def test_queued_cancel_never_enters_model_or_cancels_active_job(self):
        runtime = runtime_fixture()
        active, first = begin(runtime, "active")
        self.assertTrue(runtime.entered.wait(1))
        queued, second = begin(runtime, "queued")
        deadline = time.monotonic() + 1
        while runtime.state()["pending"] != 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(runtime.state()["pending"], 2)
        runtime.cancel_requests(["queued"])
        queued.join(0.5)
        self.assertFalse(queued.is_alive())
        self.assertIsInstance(second[0], InferenceCancelled)
        self.assertEqual(runtime.seen, ["<ru>active</ru>"])
        self.assertFalse(runtime.options[0].terminate)
        runtime.release.set()
        active.join(1)
        self.assertTrue(first[0].startswith(b"RIFF"))

    def test_cancel_before_start_and_replay_do_not_reenter_model(self):
        runtime = runtime_fixture()
        runtime.cancel_requests(["early"])
        with self.assertRaises(InferenceCancelled):
            runtime.synthesize("early", None, 1.0, request_id="early")
        runtime.release.set()
        runtime.synthesize("done", None, 1.0, request_id="done")
        with self.assertRaises(InferenceCancelled):
            runtime.synthesize("done", None, 1.0, request_id="done")
        self.assertEqual(runtime.seen, ["<ru>done</ru>"])

    def test_queue_full_fails_immediately_and_queue_wait_is_bounded(self):
        runtime = runtime_fixture(max_pending=1)
        active, _ = begin(runtime, "active")
        self.assertTrue(runtime.entered.wait(1))
        with self.assertRaises(worker.TeraBusy):
            runtime.synthesize("full", None, 1.0, request_id="full")
        runtime.cancel_requests(["active"])
        active.join(1)
        self.assertEqual(runtime.state()["pending"], 0)
        runtime = runtime_fixture(queue_timeout=0.06)
        active, _ = begin(runtime, "active")
        self.assertTrue(runtime.entered.wait(1))
        queued, outcome = begin(runtime, "wait")
        queued.join(0.5)
        self.assertFalse(queued.is_alive())
        self.assertIsInstance(outcome[0], worker.TeraBusy)
        runtime.cancel_requests(["active"])
        active.join(1)

    def test_close_cancels_active_and_queued_tokens_and_clears_tracking(self):
        runtime = runtime_fixture()
        active, active_result = begin(runtime, "close-active")
        self.assertTrue(runtime.entered.wait(1))
        queued, queued_result = begin(runtime, "close-queued")
        deadline = time.monotonic() + 1
        while runtime.state()["pending"] != 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(runtime.state()["pending"], 2)

        runtime.close()
        active.join(1)
        queued.join(1)

        self.assertFalse(active.is_alive())
        self.assertFalse(queued.is_alive())
        self.assertTrue(runtime.options[0].terminate)
        self.assertIsInstance(active_result[0], InferenceCancelled)
        self.assertIsInstance(queued_result[0], InferenceCancelled)
        self.assertEqual(runtime.state()["pending"], 0)
        self.assertEqual(runtime._tokens, {})
        self.assertTrue(runtime.state()["closing"])

    def test_http_rejects_new_work_after_runtime_close(self):
        runtime = runtime_fixture()
        class Handler(worker.Handler):
            pass
        Handler.runtime = runtime
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.block_on_close = False
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        serving.start()
        runtime.close()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            request = Request(base + "/tts", json.dumps({"text": "late"}).encode(),
                             {"Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request, timeout=2)
            self.assertEqual(rejected.exception.code, 503)
            self.assertEqual(json.loads(rejected.exception.read()),
                             {"error": "Tera runtime is closing"})
            rejected.exception.close()
            self.assertEqual(runtime.state()["pending"], 0)
            self.assertEqual(runtime.seen, [])
        finally:
            server.shutdown()
            serving.join(1)
            server.server_close()

    def test_concurrent_close_cannot_miss_inflight_admission(self):
        runtime = runtime_fixture()
        begin_entered = threading.Event()
        finish_begin = threading.Event()
        original_begin = runtime._requests.begin

        def paused_begin(request_id):
            begin_entered.set()
            self.assertTrue(finish_begin.wait(1))
            return original_begin(request_id)

        runtime._requests.begin = paused_begin
        request, outcome = begin(runtime, "admission-race")
        self.assertTrue(begin_entered.wait(1))
        closers = [threading.Thread(target=runtime.close, daemon=True) for _ in range(6)]
        for closer in closers:
            closer.start()
        finish_begin.set()
        request.join(1)
        for closer in closers:
            closer.join(1)

        self.assertFalse(request.is_alive())
        self.assertTrue(all(not closer.is_alive() for closer in closers))
        self.assertIsInstance(outcome[0], InferenceCancelled)
        self.assertFalse(runtime.entered.is_set())
        self.assertEqual(runtime.state()["pending"], 0)
        self.assertEqual(runtime._tokens, {})

        with self.assertRaises(worker.TeraBusy):
            runtime.synthesize("after close", None, 1.0, request_id="late-id")
        with self.assertRaises(worker.TeraBusy):
            runtime.cancel_requests(["late-cancel"])

    def test_finished_request_timer_cannot_cancel_a_later_job(self):
        runtime = runtime_fixture(request_timeout=0.1)
        runtime.release.set()
        runtime.synthesize("first", None, 1.0, request_id="timer-first")
        time.sleep(0.12)

        runtime.release.clear()
        runtime.entered.clear()
        second, outcome = begin(runtime, "timer-second")
        self.assertTrue(runtime.entered.wait(1))
        time.sleep(0.02)
        self.assertFalse(runtime.options[-1].terminate)
        runtime.cancel_requests(["timer-second"])
        second.join(1)
        self.assertFalse(second.is_alive())
        self.assertIsInstance(outcome[0], InferenceCancelled)

    def test_request_deadline_terminates_only_its_inference(self):
        runtime = runtime_fixture(request_timeout=0.06)
        active, outcome = begin(runtime, "deadline")
        active.join(0.5)
        self.assertFalse(active.is_alive())
        self.assertIsInstance(outcome[0], InferenceCancelled)
        self.assertEqual(runtime.state()["pending"], 0)

    def test_invalid_batch_validates_all_ids_before_cancelling(self):
        runtime = runtime_fixture()
        active, _ = begin(runtime, "active")
        self.assertTrue(runtime.entered.wait(1))
        for invalid in ([], {}, ["active", None], ["x"] * 9):
            with self.assertRaises(ValueError):
                runtime.cancel_requests(invalid)
            self.assertFalse(runtime.options[0].terminate)
        runtime.cancel_requests(["active"])
        active.join(1)

    def test_http_cancel_while_tts_is_waiting_before_headers(self):
        runtime = runtime_fixture()
        class Handler(worker.Handler):
            pass
        Handler.runtime = runtime
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        serving.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def post(path, payload):
            with urlopen(Request(base + path, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"}), timeout=2) as response:
                return json.loads(response.read())
        result = []
        def synthesize():
            try:
                post("/tts", {"text": "active", "request_id": "http"})
            except HTTPError as exc:
                result.append((exc.code, json.loads(exc.read())))
                exc.close()
        request = threading.Thread(target=synthesize, daemon=True)
        try:
            request.start()
            self.assertTrue(runtime.entered.wait(1))
            browser_cancel = Request(base + "/cancel", json.dumps({"request_ids": ["http"]}).encode(),
                                     {"Content-Type": "application/json", "Origin": "https://example.test"})
            with self.assertRaises(HTTPError) as rejected:
                urlopen(browser_cancel, timeout=2)
            self.assertEqual(rejected.exception.code, 403)
            rejected.exception.close()
            self.assertFalse(runtime.options[0].terminate)
            started = time.monotonic()
            self.assertTrue(post("/cancel", {"request_ids": ["http"]})["ok"])
            request.join(1)
            self.assertFalse(request.is_alive())
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual(result, [(409, {"error": "speech inference cancelled"})])
            self.assertEqual(runtime.state()["pending"], 0)
        finally:
            runtime.release.set()
            request.join(2)
            server.shutdown()
            serving.join(2)
            server.server_close()

    def test_standalone_worker_refuses_remote_bind_before_loading_models(self):
        child = subprocess.run([sys.executable, "-B", str(Path(worker.__file__).resolve()),
                                "--host", "0.0.0.0"], capture_output=True, text=True, timeout=5)
        self.assertEqual(child.returncode, 2)
        self.assertIn("must bind loopback", child.stderr)
        self.assertEqual(child.stdout, "")

    def test_service_governor_adapter_and_worker_cancel_release_before_headers(self):
        runtime = runtime_fixture()
        class Handler(worker.Handler):
            pass
        Handler.runtime = runtime
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        serving.start()
        governor = ResourceGovernor()
        service = TTSService(TeraTTSHttpClient(f"http://127.0.0.1:{server.server_port}"), governor)
        results = []
        def request_speech():
            try:
                results.append(list(service.stream("Old.", request_id="service-old")))
            except Exception as exc:
                results.append(exc)
        speech = threading.Thread(target=request_speech, daemon=True)
        try:
            speech.start()
            self.assertTrue(runtime.entered.wait(1))
            self.assertEqual(governor.state()["active"], {"speech": 1})
            service.cancel(request_id="service-old")
            speech.join(1)
            self.assertFalse(speech.is_alive())
            self.assertIsInstance(results[0], TTSCancelled)
            self.assertEqual(runtime.state()["pending"], 0)
            self.assertEqual(governor.state()["active"], {})
            self.assertEqual(service.provider._worker_requests, {})
            self.assertTrue(runtime.options[0].terminate)
            runtime.release.set()
            audio = list(service.stream("New.", request_id="service-new"))
            self.assertEqual(len(audio), 1)
            self.assertTrue(audio[0].startswith(b"RIFF"))
            self.assertFalse(runtime.options[-1].terminate)
        finally:
            runtime.release.set()
            service.cancel()
            speech.join(2)
            server.shutdown()
            serving.join(2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
