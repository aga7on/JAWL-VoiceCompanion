import io
import json
import threading
import time
import unittest
import wave
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.tts import CozyVoiceHttpClient, TTSCancelled, TTSService, split_sentences  # noqa: E402


class TTSServiceTests(unittest.TestCase):
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

    @staticmethod
    def _capture(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - assert the cancellation type below
            return exc
        return None


if __name__ == "__main__":
    unittest.main()
