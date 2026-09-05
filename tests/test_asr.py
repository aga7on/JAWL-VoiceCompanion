import io
import json
import sys
import wave
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.asr import ASRNoSpeech, ASRUnavailable, ExternalASRService, OpenAICompatibleASRClient


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode("utf-8")


class _Provider:
    def __init__(self):
        self.audio = None

    def health(self):
        return {"status": "online", "model": "test-asr"}

    def transcribe(self, wav_bytes):
        self.audio = wav_bytes
        return "тестовая фраза"


class _NoSpeechProvider:
    def __init__(self):
        self.calls = 0

    def health(self):
        return {"status": "online", "model": "test-asr"}

    def transcribe(self, wav_bytes):
        self.calls += 1
        raise ASRNoSpeech("ASR endpoint returned no speech text")


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ASRTests(unittest.TestCase):
    def test_openai_client_accepts_llama_event_response_and_builds_multipart(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return _Response({
                "type": "transcript.text.done",
                "text": "language Russian<asr_text>Привет, компаньон.</asr_text>",
            })

        client = OpenAICompatibleASRClient(
            "http://127.0.0.1:8984/v1",
            "Qwen3-ASR-0.6B",
            opener=opener,
        )
        text = client.transcribe(b"RIFF-test", filename="voice sample.wav")

        self.assertEqual(text, "Привет, компаньон.")
        request = requests[0][0]
        body = request.data
        self.assertIn(b'name="model"', body)
        self.assertIn(b"Qwen3-ASR-0.6B", body)
        self.assertIn(b'name="prompt"', body)
        self.assertIn(b"Transcribe the audio exactly as spoken.", body)
        self.assertIn(b'filename="voice_sample.wav"', body)
        self.assertEqual(request.full_url, "http://127.0.0.1:8984/v1/audio/transcriptions")

    def test_health_maps_llama_ok_to_online(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url, "http://127.0.0.1:8984/health")
            return _Response({"status": "ok"})

        result = OpenAICompatibleASRClient("http://127.0.0.1:8984", "qwen", opener=opener).health()
        self.assertEqual(result["status"], "online")
        self.assertEqual(result["mode"], "final_utterance")

    def test_service_buffers_audio_until_finish_and_creates_wav(self):
        provider = _Provider()
        service = ExternalASRService(provider)
        buffered = service.feed_audio(
            b"\x01\x00" * 1600,
            sample_rate=16000,
            channels=1,
            session_id="browser-mic",
        )

        self.assertEqual(buffered["status"], "buffered")
        self.assertEqual(buffered["bytes"], 3200)
        self.assertFalse(buffered["raw_audio_persisted"])
        self.assertEqual(service.state()["active_sessions"], 1)
        result = service.finish("browser-mic")

        self.assertEqual(result["status"], "transcribed")
        self.assertEqual(result["text"], "тестовая фраза")
        self.assertEqual(service.state()["active_sessions"], 0)
        with wave.open(io.BytesIO(provider.audio), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), b"\x01\x00" * 1600)

    def test_service_discards_empty_session_without_calling_provider(self):
        provider = _Provider()
        result = ExternalASRService(provider).finish("missing")
        self.assertEqual(result["status"], "empty")
        self.assertIsNone(provider.audio)

    def test_service_expires_stale_disconnected_session_and_never_calls_provider(self):
        provider = _NoSpeechProvider()
        clock = _FakeClock()
        service = ExternalASRService(provider, session_ttl_seconds=10.0, clock=clock)
        service.feed_audio(b"\x01\x00" * 64, sample_rate=16000, channels=1, session_id="stale")
        self.assertEqual(service.state()["active_sessions"], 1)
        clock.now = 20.0
        state = service.state()
        self.assertEqual(state["active_sessions"], 0)
        self.assertEqual(provider.calls, 0, "a disconnected session must never reach the provider")
        result = service.finish("stale")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(provider.calls, 0)
        service.feed_audio(b"\x02\x00" * 64, sample_rate=16000, channels=1, session_id="fresh")
        self.assertEqual(service.state()["active_sessions"], 1, "a new session must work after eviction")

    def test_service_maps_absent_speech_to_no_speech_outcome(self):
        provider = _NoSpeechProvider()
        service = ExternalASRService(provider)
        service.feed_audio(b"\x01\x00" * 64, sample_rate=16000, channels=1, session_id="quiet")
        result = service.finish("quiet")
        self.assertEqual(result["status"], "no_speech")
        self.assertEqual(result["text"], "")
        self.assertEqual(service.state()["active_sessions"], 0)

    def test_transcribe_empty_reply_raises_asr_no_speech(self):
        def opener(request, timeout):
            return _Response({"text": ""})

        client = OpenAICompatibleASRClient("http://127.0.0.1:8984/v1", "qwen", opener=opener)
        with self.assertRaises(ASRNoSpeech):
            client.transcribe(b"RIFF-test", filename="quiet.wav")

    def test_translate_transport_failure_still_raises_asr_unavailable(self):
        def opener(request, timeout):
            raise OSError("connection refused")

        client = OpenAICompatibleASRClient("http://127.0.0.1:8984/v1", "qwen", opener=opener)
        with self.assertRaises(ASRUnavailable):
            client.transcribe(b"RIFF-test", filename="utterance.wav")


if __name__ == "__main__":
    unittest.main()
