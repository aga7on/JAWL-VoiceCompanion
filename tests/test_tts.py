import io
import base64
import json
import threading
import time
import unittest
import wave
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.tts import CozyVoiceHttpClient, Qwen3TTSHttpClient, TeraTTSHttpClient, TTSCancelled, TTSService, VoxCPMHttpClient, split_sentences  # noqa: E402


class TTSServiceTests(unittest.TestCase):
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
    def _capture(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - assert the cancellation type below
            return exc
        return None


if __name__ == "__main__":
    unittest.main()
