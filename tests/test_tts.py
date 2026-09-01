import threading
import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.tts import TTSCancelled, TTSService, split_sentences  # noqa: E402


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

    @staticmethod
    def _capture(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - assert the cancellation type below
            return exc
        return None


if __name__ == "__main__":
    unittest.main()
