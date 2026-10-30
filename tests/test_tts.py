import io
import base64
import json
import threading
import time
import unittest
import wave
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.tts import CozyVoiceHttpClient, Qwen3TTSHttpClient, TeraTTSHttpClient, TTSCancelled, TTSService, TTSUnavailable, VoxCPMHttpClient, split_sentences  # noqa: E402
from jawl_voicecompanion.resources import ResourceGovernor  # noqa: E402


class TTSServiceTests(unittest.TestCase):
    def test_cancelled_response_returning_from_opener_does_not_leak_tracking(self):
        for client_type in (CozyVoiceHttpClient, VoxCPMHttpClient):
            with self.subTest(client=client_type.__name__):
                cancelled = threading.Event()

                class Response:
                    closed = False

                    def __enter__(self): return self
                    def __exit__(self, *_args): self.close()
                    def close(self): self.closed = True
                    def read(self, *_args): raise AssertionError("cancelled response must not be read")
                    def __iter__(self): raise AssertionError("cancelled response must not be iterated")

                response = Response()

                def opener(*args, **kwargs):
                    cancelled.set()
                    return response

                client = client_type("http://127.0.0.1:1", opener=opener)
                with self.assertRaises(TTSCancelled):
                    if client_type is VoxCPMHttpClient:
                        list(client.stream_synthesize("A.", cancel_event=cancelled))
                    else:
                        client.synthesize("A.", cancel_event=cancelled)
                self.assertTrue(response.closed)
                self.assertEqual(client._active_responses, {})

    def test_generation_cancel_interrupts_real_http_blocking_body_read(self):
        release = threading.Event()
        reading = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Length", "4096")
                self.end_headers()
                self.wfile.write(b"x")
                self.wfile.flush()
                release.wait(3)  # intentionally incomplete provider body

            def log_message(self, *_args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        serving = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        serving.start()

        def opener(request, timeout):
            response = urlopen(request, timeout=timeout)
            original_read = response.read

            def read(*args, **kwargs):
                reading.set()
                return original_read(*args, **kwargs)

            response.read = read
            return response

        client = CozyVoiceHttpClient(f"http://127.0.0.1:{server.server_port}", opener=opener, timeout_seconds=10)
        cancelled = threading.Event()
        results = []

        def request_audio():
            try:
                client.synthesize("A.", cancel_event=cancelled)
            except Exception as exc:
                results.append(exc)

        worker = threading.Thread(target=request_audio, daemon=True)
        try:
            worker.start()
            self.assertTrue(reading.wait(1))
            started = time.monotonic()
            cancelled.set()
            client.cancel_generation(cancelled)
            worker.join(1)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], TTSCancelled)
            self.assertEqual(client._active_responses, {})
        finally:
            release.set()
            client.cancel()
            worker.join(2)
            server.shutdown()
            serving.join(2)
            server.server_close()

    def test_selected_tera_adapter_uses_shared_local_rest_contract(self):
        requests = []
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\x00\x00" * 4)

        class Response:
            def __init__(self):
                self._sent = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                if self._sent:
                    return b""
                self._sent = True
                return output.getvalue()

        def opener(request, timeout):
            del timeout
            requests.append(request)
            return Response()

        audio = TeraTTSHttpClient("http://127.0.0.1:9889", opener=opener).synthesize("Привет")
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:9889/tts")
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(set(payload), {"text", "speed", "stream", "request_id"})
        self.assertEqual(str(uuid.UUID(payload["request_id"])), payload["request_id"])
        self.assertEqual(len(requests), 1)  # successful cleanup sends no /cancel

    def test_tera_uses_a_distinct_uuid_for_each_sentence(self):
        requests = []

        class Response:
            def __init__(self): self.sent = False
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit=-1):
                if self.sent: return b""
                self.sent = True
                return TTSServiceTests._wav(b"u")

        def opener(request, timeout):
            del timeout
            requests.append(request)
            return Response()

        client = TeraTTSHttpClient("http://127.0.0.1:9889", opener=opener)
        client.synthesize("First. Second.")
        ids = [json.loads(request.data.decode("utf-8"))["request_id"] for request in requests]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(str(uuid.UUID(value)) == value for value in ids))

    def test_tera_pre_cancelled_event_does_not_submit_inference(self):
        requests = []
        event = threading.Event()
        event.set()
        client = TeraTTSHttpClient(
            "http://127.0.0.1:9889",
            opener=lambda request, **kwargs: requests.append(request),
        )
        with self.assertRaises(TTSCancelled):
            client.synthesize("Already stopped.", cancel_event=event)
        self.assertEqual(requests, [])
        self.assertEqual(client._worker_requests, {})

    def test_tera_sends_request_scoped_cancel_batches_without_global_cancel(self):
        calls = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit=-1): return b"{}"

        def opener(request, timeout):
            calls.append((request, timeout))
            return Response()

        client = TeraTTSHttpClient("http://127.0.0.1:9889", opener=opener)
        event = threading.Event()
        ids = [client._begin_worker_request(event) for _ in range(9)]
        client.cancel_generation(event)

        posted = [(request, timeout) for request, timeout in calls]
        self.assertEqual([request.full_url for request, _ in posted], [
            "http://127.0.0.1:9889/cancel", "http://127.0.0.1:9889/cancel",
        ])
        batches = [json.loads(request.data.decode("ascii"))["request_ids"] for request, _ in posted]
        self.assertEqual([len(batch) for batch in batches], [8, 1])
        self.assertEqual(sorted(item for batch in batches for item in batch), sorted(ids))
        for request, timeout in posted:
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertLessEqual(timeout, 1.0)
        self.assertTrue(all(1 <= len(batch) <= 8 for batch in batches))
        self.assertEqual(client._worker_requests[event], set(ids))

    def test_tera_concurrent_generation_cancel_is_identity_scoped(self):
        entered = {"A": threading.Event(), "B": threading.Event()}
        release = {"A": threading.Event(), "B": threading.Event()}
        inference_ids = {}
        posted = []
        lock = threading.Lock()

        class Response:
            def __init__(self): self.sent = False
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit=-1):
                if self.sent: return b""
                self.sent = True
                return TTSServiceTests._wav(b"B")

        def opener(request, timeout):
            if request.full_url.endswith("/tts"):
                label = json.loads(request.data.decode("utf-8"))["text"]
                inference_ids[label] = json.loads(request.data.decode("utf-8"))["request_id"]
                entered[label].set()
                if label == "A":
                    release[label].wait(2)
                    raise OSError("request stopped")
                release[label].wait(2)
                return Response()
            with lock:
                posted.append((request, timeout))
            return Response()

        client = TeraTTSHttpClient("http://127.0.0.1:9889", opener=opener)
        events = {"A": threading.Event(), "B": threading.Event()}
        workers = [
            threading.Thread(
                target=lambda label=label: self._capture(
                    lambda: client.synthesize(label, cancel_event=events[label])
                ), daemon=True,
            )
            for label in ("A", "B")
        ]
        for worker in workers: worker.start()
        self.assertTrue(entered["A"].wait(1))
        self.assertTrue(entered["B"].wait(1))
        events["A"].set()
        client.cancel_generation(events["A"])
        release["A"].set()
        # B was not selected by A's cancellation and remains registered until
        # its own successful response completes.
        self.assertFalse(events["B"].is_set())
        self.assertEqual(len(client._worker_requests[events["B"]]), 1)
        release["B"].set()
        for worker in workers: worker.join(2)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        targeted = [
            json.loads(request.data.decode("utf-8"))["request_ids"]
            for request, _ in posted
        ]
        self.assertEqual(len(targeted), 2)  # explicit A cancel + A's failed opener
        self.assertTrue(all(len(batch) == 1 for batch in targeted))
        self.assertEqual(targeted[0], targeted[1])
        self.assertEqual(targeted[0][0], inference_ids["A"])
        self.assertNotIn(inference_ids["B"], targeted[0])
        self.assertEqual(client._worker_requests, {})

    def test_tera_cancel_before_headers_unblocks_real_service_and_governor(self):
        arrived = threading.Event()
        cancelled_ids = set()
        cancelled = threading.Event()
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                if self.path == "/tts":
                    request_id = payload["request_id"]
                    with lock:
                        is_cancelled = request_id in cancelled_ids
                    arrived.set()
                    if not is_cancelled:
                        cancelled.wait(2)
                    with lock:
                        is_cancelled = request_id in cancelled_ids
                    self.send_response(409 if is_cancelled else 200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/cancel":
                    with lock:
                        cancelled_ids.update(payload["request_ids"])
                    cancelled.set()
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                self.send_error(404)

            def log_message(self, *_args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        serving = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        serving.start()
        governor = ResourceGovernor()
        service = TTSService(
            TeraTTSHttpClient(f"http://127.0.0.1:{server.server_port}", timeout_seconds=10),
            governor=governor,
        )
        results = []
        worker = threading.Thread(
            target=lambda: results.append(self._capture(
                lambda: list(service.stream("Wait.", request_id="cancel-before-headers"))
            )), daemon=True,
        )
        try:
            worker.start()
            self.assertTrue(arrived.wait(1))
            self.assertEqual(governor.state()["active"].get("speech"), 1)
            service.cancel(request_id="cancel-before-headers")
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0], TTSCancelled)
            self.assertEqual(len(cancelled_ids), 1)
            self.assertEqual(governor.state()["active"], {})
        finally:
            cancelled.set()
            worker.join(1)
            server.shutdown()
            serving.join(2)
            server.server_close()

    def test_tera_failed_opener_cancels_own_id_and_cleans_registry(self):
        calls = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self, _limit=-1): return b"{}"

        def opener(request, timeout):
            if request.full_url.endswith("/tts"):
                raise TimeoutError("headers timed out")
            calls.append((request, timeout))
            return Response()

        client = TeraTTSHttpClient("http://127.0.0.1:9889", opener=opener)
        with self.assertRaises(TTSUnavailable):
            client.synthesize("Fail.")
        self.assertEqual(client._worker_requests, {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0].full_url, "http://127.0.0.1:9889/cancel")
        self.assertEqual(len(json.loads(calls[0][0].data)["request_ids"]), 1)

    def test_tera_registered_request_bound_fails_closed_and_recovers(self):
        client = TeraTTSHttpClient("http://127.0.0.1:9889", opener=lambda *_a, **_k: None)
        owners = [threading.Event() for _ in range(client.MAX_REGISTERED_REQUESTS)]
        for owner in owners:
            client._begin_worker_request(owner)
        with self.assertRaises(TTSUnavailable):
            client._begin_worker_request(threading.Event())
        for owner in owners:
            token = next(iter(client._worker_requests[owner]))
            client._finish_worker_request(owner, token)
        self.assertEqual(client._worker_requests, {})

    def test_selected_qwen_adapter_uses_shared_local_rest_contract(self):
        requests = []
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\x00\x00" * 4)

        class Response:
            def __init__(self):
                self._sent = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                if self._sent:
                    return b""
                self._sent = True
                return output.getvalue()

        def opener(request, timeout):
            del timeout
            requests.append(request)
            return Response()

        audio = Qwen3TTSHttpClient("http://127.0.0.1:9890", opener=opener).synthesize("Привет")
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:9890/tts")

    def test_voxcpm_adapter_decodes_native_stream_contract(self):
        requests = []
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(b"\x00\x00" * 4)
        encoded = base64.b64encode(output.getvalue()).decode("ascii")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter((
                    (json.dumps({"type": "audio", "data_base64": encoded}) + "\n").encode(),
                    b'{"type":"done","count":1}\n',
                ))

            def close(self):
                return None

        def opener(request, timeout):
            del timeout
            requests.append(request)
            return Response()

        chunks = list(VoxCPMHttpClient("http://127.0.0.1:9891", opener=opener).stream_synthesize("Привет"))
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith(b"RIFF"))
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:9891/tts/stream")

    def test_voxcpm_cancel_requests_worker_cancel_endpoint(self):
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b'{"ok":true}'

        def opener(request, timeout):
            requests.append((request, timeout))
            return Response()

        VoxCPMHttpClient("http://127.0.0.1:9891", opener=opener).cancel()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0].full_url, "http://127.0.0.1:9891/cancel")
        self.assertEqual(requests[0][0].method, "POST")

    def test_native_stream_provider_is_used_by_service(self):
        calls = []

        def wav(marker):
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(48000)
                result.writeframes(marker * 4)
            return output.getvalue()

        class Provider:
            def stream_synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                calls.append((text, voice, speed, cancel_event))
                yield wav(b"3")

        service = TTSService(Provider())
        result = list(service.stream("first. second.", voice="voxcpm-reference", speed=1.1))
        self.assertEqual(len(result), 2)
        self.assertEqual([item[0] for item in calls], ["first.", "second."])
        self.assertEqual(calls[0][1:], ("voxcpm-reference", 1.1, calls[0][3]))

    def test_native_stream_close_cancels_only_its_generation(self):
        events = []
        active = {"event": None}

        class Provider:
            def stream_synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                del text, voice, speed
                active["event"] = cancel_event
                events.append(("stream", cancel_event))
                yield TTSServiceTests._wav(b"n")

            def cancel_generation(self, cancel_event):
                events.append(("cancel", cancel_event))

            def cancel(self):
                event = active["event"]
                events.append(("global", event))
                if event is not None:
                    event.set()

        service = TTSService(Provider())
        stream_a = service.stream("A.")
        next(stream_a)
        event_a = service._active
        stream_b = service.stream("B.")
        next(stream_b)
        event_b = service._active

        stream_a.close()

        self.assertIsNot(event_a, event_b)
        self.assertTrue(event_a.is_set())
        self.assertFalse(event_b.is_set())
        self.assertEqual([event for kind, event in events if kind == "cancel"], [event_a, event_a])
        self.assertFalse(any(kind == "global" for kind, *_ in events))
        stream_b.close()

    def test_voxcpm_generation_cancel_does_not_call_worker_global_cancel(self):
        requests = []
        opened = threading.Event()
        cancelled = threading.Event()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                opened.set()
                cancelled.wait(1)
                raise OSError("stream closed")
                yield b""

            def read(self, _limit=-1):
                return b""

            def close(self):
                cancelled.set()

        def opener(request, timeout):
            del timeout
            requests.append(request.full_url)
            return Response()

        client = VoxCPMHttpClient("http://127.0.0.1:9891", opener=opener)
        event = threading.Event()
        worker = threading.Thread(
            target=lambda: self._capture(lambda: list(client.stream_synthesize("A.", cancel_event=event))),
            daemon=True,
        )
        worker.start()
        self.assertTrue(opened.wait(1))
        event.set()
        client.cancel_generation(event)
        worker.join(1)

        self.assertEqual(requests, ["http://127.0.0.1:9891/tts/stream"])
        self.assertFalse(worker.is_alive())

    def test_legacy_provider_old_stream_finalizer_does_not_cancel_new_owner(self):
        cancel_calls = []

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                del text, voice, speed, cancel_event
                return TTSServiceTests._wav(b"l")

            def cancel(self):
                cancel_calls.append("global")

        service = TTSService(Provider())
        stream_a = service.stream("A.")
        next(stream_a)
        stream_b = service.stream("B.")
        next(stream_b)
        self.assertEqual(cancel_calls, ["global"])

        stream_a.close()

        self.assertEqual(cancel_calls, ["global"])
        self.assertIsNotNone(service._active)
        stream_b.close()
        self.assertEqual(cancel_calls, ["global", "global"])

    def test_legacy_native_stream_new_owner_survives_old_close(self):
        class Provider:
            def __init__(self):
                self.active = None

            def stream_synthesize(self, text, *, cancel_event=None, **kwargs):
                self.active = cancel_event
                yield TTSServiceTests._wav(b"n")
                if cancel_event.is_set():
                    raise TTSCancelled()
                yield TTSServiceTests._wav(b"n")

            def cancel(self):
                if self.active is not None:
                    self.active.set()

        service = TTSService(Provider())
        old = service.stream("A.")
        new = service.stream("B.")
        try:
            next(old)
            next(new)
            current = service._active
            old.close()
            self.assertFalse(current.is_set())
            self.assertIs(service._active, current)
            self.assertTrue(next(new))
        finally:
            old.close()
            new.close()

    def test_prosody_cleanup_does_not_cancel_new_legacy_owner(self):
        cancel_calls = []

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None, prosody=None):
                del text, voice, speed, cancel_event, prosody
                return TTSServiceTests._wav(b"p")

            def cancel(self):
                cancel_calls.append("global")

        class Planner:
            timeout_seconds = 0.01

            def plan(self, sentences):
                return [{"pitch": 0.0} for _ in sentences]

        service = TTSService(Provider(), prosody_planner=Planner())
        stream_a = service.stream("A. A2.")
        next(stream_a)
        stream_b = service.stream("B.")
        next(stream_b)
        self.assertEqual(cancel_calls, ["global"])

        stream_a.close()

        self.assertEqual(cancel_calls, ["global"])
        stream_b.close()

    def test_http_cancel_generation_closes_only_owned_response(self):
        opened = {"A": threading.Event(), "B": threading.Event()}
        responses = {}
        results = []

        class Response:
            def __init__(self, key):
                self.key = key
                self.closed = threading.Event()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                if not self.closed.wait(2):
                    return b""
                raise OSError("response closed")

            def close(self):
                self.closed.set()

        def opener(request, timeout):
            del timeout
            key = json.loads(request.data.decode("utf-8"))["text"]
            response = Response(key)
            responses[key] = response
            opened[key].set()
            return response

        client = CozyVoiceHttpClient("http://127.0.0.1:1", opener=opener)
        event_a = threading.Event()
        event_b = threading.Event()

        def run(key, event):
            try:
                client.synthesize(key, cancel_event=event)
            except Exception as exc:  # noqa: BLE001 - thread result is asserted below
                results.append((key, exc))

        worker_a = threading.Thread(target=run, args=("A", event_a), daemon=True)
        worker_b = threading.Thread(target=run, args=("B", event_b), daemon=True)
        worker_a.start()
        worker_b.start()
        self.assertTrue(opened["A"].wait(1))
        self.assertTrue(opened["B"].wait(1))

        event_a.set()
        client.cancel_generation(event_a)
        worker_a.join(1)
        self.assertTrue(responses["A"].closed.is_set())
        self.assertFalse(responses["B"].closed.is_set())
        self.assertTrue(any(key == "A" and isinstance(exc, TTSCancelled) for key, exc in results))

        event_b.set()
        client.cancel()
        worker_b.join(1)
        self.assertTrue(responses["B"].closed.is_set())
        self.assertTrue(any(key == "B" and isinstance(exc, TTSCancelled) for key, exc in results))


    def test_sentence_split_keeps_russian_punctuation_and_bounds_chunks(self):
        self.assertEqual(split_sentences("Привет. Как дела?"), ["Привет.", "Как дела?"])
        self.assertTrue(all(len(part) <= 10 for part in split_sentences("Очень длинная фраза", max_chars=10)))

    def test_newer_request_cancels_older_generation(self):
        started = threading.Event()
        calls = []

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                calls.append(text)
                if text == "старый":
                    started.set()
                    while not cancel_event.is_set():
                        time.sleep(0.005)
                    raise TTSCancelled()
                return b"new-audio"

        service = TTSService(Provider())
        result = []
        worker = threading.Thread(
            target=lambda: result.append(self._capture(lambda: service.synthesize("старый"))),
            daemon=True,
        )
        worker.start()
        self.assertTrue(started.wait(1))
        self.assertEqual(service.synthesize("новый"), b"new-audio")
        worker.join(1)
        self.assertIsInstance(result[0], TTSCancelled)
        self.assertEqual(calls, ["старый", "новый"])

    def test_explicit_cancel_stops_active_generation(self):
        started = threading.Event()

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                del text, voice, speed
                started.set()
                while not cancel_event.is_set():
                    time.sleep(0.005)
                raise TTSCancelled()

        service = TTSService(Provider())
        result = []
        worker = threading.Thread(
            target=lambda: result.append(self._capture(lambda: service.synthesize("ожидание"))),
            daemon=True,
        )
        worker.start()
        self.assertTrue(started.wait(1))
        service.cancel()
        worker.join(1)
        self.assertIsInstance(result[0], TTSCancelled)

    def test_cozyvoice_synthesizes_sentences_in_parallel_but_merges_in_order(self):
        first_started = threading.Event()
        release_first = threading.Event()
        lock = threading.Lock()
        active = 0
        peak = 0

        class Response:
            def __init__(self, body):
                self.body = body
                self.done = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                if self.done:
                    return b""
                self.done = True
                return self.body

        def wav(marker):
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(22050)
                result.writeframes(marker * 4)
            return output.getvalue()

        def opener(request, timeout):
            del timeout
            nonlocal active, peak
            text = json.loads(request.data.decode("utf-8"))["text"]
            with lock:
                active += 1
                peak = max(peak, active)
            if text == "first.":
                first_started.set()
                release_first.wait(1)
            with lock:
                active -= 1
            return Response(wav(b"1" if text == "first." else b"2"))

        client = CozyVoiceHttpClient("http://127.0.0.1:1", opener=opener)
        result = []
        worker = threading.Thread(
            target=lambda: result.append(client.synthesize("first. second.")), daemon=True
        )
        worker.start()
        self.assertTrue(first_started.wait(1))
        deadline = time.monotonic() + 1
        while peak < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertGreaterEqual(peak, 2)
        release_first.set()
        worker.join(2)
        self.assertEqual(len(result), 1)
        with wave.open(io.BytesIO(result[0]), "rb") as merged:
            self.assertEqual(merged.readframes(2), b"1" * 4)
            self.assertEqual(merged.readframes(2), b"2" * 4)

    def test_service_streams_sentence_audio_in_source_order(self):
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def wav(marker):
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(22050)
                result.writeframes(marker * 4)
            return output.getvalue()

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                del voice, speed, cancel_event
                if text == "first.":
                    first_started.set()
                    release_first.wait(1)
                    return wav(b"1")
                second_started.set()
                return wav(b"2")

        result = []
        service = TTSService(Provider())
        worker = threading.Thread(
            target=lambda: result.extend(service.stream("first. second.")), daemon=True
        )
        worker.start()
        self.assertTrue(first_started.wait(1))
        self.assertTrue(second_started.wait(1))
        release_first.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result), 2)
        with wave.open(io.BytesIO(result[0]), "rb") as first:
            self.assertEqual(first.readframes(2), b"1" * 4)
        with wave.open(io.BytesIO(result[1]), "rb") as second:
            self.assertEqual(second.readframes(2), b"2" * 4)

    def test_closing_sentence_stream_calls_provider_cancel(self):
        cancelled = threading.Event()

        def wav(marker):
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(22050)
                result.writeframes(marker * 4)
            return output.getvalue()

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None):
                del voice, speed
                if text == "first.":
                    return wav(b"1")
                while not cancel_event.is_set():
                    time.sleep(0.005)
                raise TTSCancelled()

            def cancel(self):
                cancelled.set()

        service = TTSService(Provider())
        stream = service.stream("first. second.")
        next(stream)
        stream.close()
        self.assertTrue(cancelled.wait(1))

    def test_prosody_planner_annotates_tail_and_preserves_order(self):
        collected: list[dict] = []
        ordered: list[str] = []
        done = threading.Event()

        def wav(marker):
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(22050)
                result.writeframes(marker * 4)
            return output.getvalue()

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None, prosody=None):
                del voice, speed, cancel_event
                collected.append({"text": text, "prosody": prosody})
                ordered.append(text)
                if len(ordered) == 2:
                    done.set()
                return wav(str(len(ordered)).encode() or b"x")

        class Planner:
            timeout_seconds = 1.0

            def plan(self, sentences):
                time.sleep(0.05)
                return [{"pitch": 0.0, "f0_range": 1.0, "energy": 1.0, "speed": 1.0},
                        {"pitch": 2.5, "f0_range": 1.6, "energy": 1.2, "speed": 1.0}]

        service = TTSService(Provider(), prosody_planner=Planner())
        result = list(service.stream("Первое предложение. Второе взволнованное!"))
        self.assertEqual(len(result), 2)
        self.assertTrue(done.wait(1))
        self.assertEqual(ordered[0], "Первое предложение.")
        self.assertEqual(ordered[1], "Второе взволнованное!")
        self.assertIsNone(collected[0]["prosody"])
        self.assertEqual(collected[1]["prosody"]["pitch"], 2.5)

    def test_prosody_planner_failure_degrades_to_neutral(self):
        ordered: list[str] = []
        done = threading.Event()

        def wav(marker):
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(22050)
                result.writeframes(marker * 4)
            return output.getvalue()

        class Provider:
            def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None, prosody=None):
                del voice, speed, cancel_event
                ordered.append(text)
                if len(ordered) == 2:
                    done.set()
                return wav(b"x")

        class Planner:
            timeout_seconds = 0.2

            def plan(self, sentences):
                del sentences
                raise RuntimeError("provider down")

        service = TTSService(Provider(), prosody_planner=Planner())
        result = list(service.stream("Первое. Второе."))
        self.assertEqual(len(result), 2)
        self.assertTrue(done.wait(1))
        self.assertEqual(ordered, ["Первое.", "Второе."])

    @staticmethod
    def _wav(marker):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(marker * 4)
        return output.getvalue()

    @staticmethod
    def _capture(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - assert the cancellation type below
            return exc
        return None


if __name__ == "__main__":
    unittest.main()
