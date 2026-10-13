import io
import json
import math
import sys
import threading
import time
import unittest
import wave
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import run_real_voice_synthetic_acceptance as acceptance  # noqa: E402
from jawl_voicecompanion.asr import UtteranceBuffer  # noqa: E402
from jawl_voicecompanion.gateway import TextGateway  # noqa: E402
from jawl_voicecompanion.tts import TTSService  # noqa: E402
from jawl_voicecompanion.web import create_server  # noqa: E402


TRANSCRIPT = "Этот прибор для измерения температуры называется градусник."
ANSWER = "Для измерения температуры используют термометр или градусник."


def make_wav(rate=24_000, channels=1, duration=0.24, amplitude=8_000):
    frames = bytearray()
    for index in range(int(rate * duration)):
        sample = int(amplitude * math.sin(2 * math.pi * 440 * index / rate))
        frames.extend(sample.to_bytes(2, "little", signed=True) * channels)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return stream.getvalue()


class _ContractJawl:
    def respond(self, _text, **_kwargs):
        return ANSWER

    def chat_status(self):
        return "connected"


class _ContractJawlWeb:
    def status(self):
        return "online"


class _ContractTeraProvider:
    def __init__(self):
        self.calls = []

    def health(self):
        return {"status": "ok", "model": "TeraTTSv2", "sample_rate": 24_000}

    def synthesize(self, text, *, voice=None, speed=1.0, cancel_event=None, **_kwargs):
        self.calls.append(text)
        return make_wav()


class _ContractTranscriber:
    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = 0

    def transcribe(self, wav_bytes, *, cancel_event=None):
        self.calls += 1
        with wave.open(io.BytesIO(wav_bytes), "rb") as source:
            if source.getframerate() != 16_000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
                raise AssertionError("production final-ASR input was not mono PCM16 at 16 kHz")
            self.asserted_frames = source.getnframes()
        if self.delay:
            time.sleep(self.delay)
        return TRANSCRIPT


class _ContractConfigHub:
    def read_voice_capture(self):
        return {
            "settings": {"gate_open": 0.02, "gate_close": 0.012, "silence_ms": 1_200, "pre_roll_ms": 120},
            "revision": "contract-revision",
        }


class _BoundedResponse:
    status_code = 200
    headers = {"Content-Length": str(acceptance.MAX_JSON_BYTES + 1)}

    def __init__(self):
        self.iterated = False

    def iter_content(self, chunk_size):
        self.iterated = True
        yield b"{}"

    def close(self):
        pass


class RealVoiceSyntheticAcceptanceTests(unittest.TestCase):
    def test_loopback_url_rejects_remote_and_credential_urls(self):
        self.assertEqual(acceptance.loopback_url("http://127.0.0.1:2367/"), "http://127.0.0.1:2367")
        self.assertEqual(acceptance.loopback_url("http://[::1]:2367"), "http://[::1]:2367")
        for value in (
            "https://example.invalid:2367",
            "http://user:pass@127.0.0.1:2367",
            "http://127.0.0.1:2367/?token=hidden",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.loopback_url(value)

    def test_resamples_and_downmixes_bounded_pcm16_wav(self):
        mono, rate = acceptance._pcm_from_wav(make_wav())
        self.assertEqual((rate, len(mono)), (16_000, int(16_000 * 0.24) * 2))
        stereo, stereo_rate = acceptance._pcm_from_wav(make_wav(rate=16_000, channels=2))
        self.assertEqual((stereo_rate, len(stereo)), (16_000, int(16_000 * 0.24) * 2))
        self.assertGreater(acceptance._pcm_metrics(mono)["rms"], 16)

    def test_json_content_length_is_checked_before_body_iteration(self):
        response = _BoundedResponse()
        with self.assertRaises(acceptance.AcceptanceFailure):
            acceptance._json(response, "fixture")
        self.assertFalse(response.iterated)

    def setUp(self):
        self.transcriber = _ContractTranscriber()
        self.tera = _ContractTeraProvider()
        gateway = TextGateway(
            responder=_ContractJawl(),
            jawl_web=_ContractJawlWeb(),
            brain_name="jawl_terminal",
        )
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            frontend_dir=Path(__file__).parents[1] / "frontend",
            gateway=gateway,
            asr_service=UtteranceBuffer(self.transcriber),
            tts_service=TTSService(self.tera),
            config_hub=_ContractConfigHub(),
        )
        # /api/voice/status and /api/voice/audio exercise the production route
        # and response serializers; no VoiceMem process or external provider is started.
        self.server.voice_mem = SimpleNamespace(
            health=lambda: {"status": "ok", "provider": "contract-fake"},
            close=lambda: None,
        )
        self.renewals = 0
        original_renew = self.server.voice_capture.renew

        def count_renew(*args, **kwargs):
            self.renewals += 1
            return original_renew(*args, **kwargs)

        self.server.voice_capture.renew = count_renew
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.args = Namespace(
            url=f"http://127.0.0.1:{self.server.server_port}",
            owned_profile_id="unit-test-profile-label",
            expected_instance_id=self.server.runtime_instance_id,
            timeout=5.0,
            confirm_no_capture=True,
            fake_provider_evidence=True,
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_full_run_uses_production_http_routes_and_marks_fake_evidence(self):
        report = acceptance.run(self.args)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["evidence_class"], "fake_provider_production_http_contract")
        self.assertEqual(report["mode"], "GigaAM_to_native_JAWL_to_TeraTTS")
        self.assertEqual(report["readiness"]["asr_engine"], "gigaam")
        self.assertEqual(report["readiness"]["brain_mode"], "jawl_terminal")
        self.assertEqual(report["readiness"]["tts_model"], "TeraTTSv2")
        self.assertFalse(report["readiness"]["runtime_identity"]["profile_ownership_proven_by_instance_id"])
        self.assertTrue(report["capture_attestation"]["no_physical_mic_system_audio_or_screen_capture_active"])
        self.assertTrue(report["fixture"]["pcm_bytes"] > 0)
        self.assertTrue(report["jawl_answer"]["meaningful_ru"])
        self.assertTrue(report["playable_tts"]["verified"])
        self.assertEqual(self.transcriber.calls, 1)
        self.assertEqual(len(self.tera.calls), 2)
        self.assertTrue(report["capture_lease_released"])
        self.assertIsNone(self.server.voice_capture.state()["owner"])

    def test_lease_is_released_when_acquire_response_parsing_fails(self):
        real_json = acceptance._json

        def fail_acquire_parse(response, label):
            if label == "synthetic PCM capture lease":
                response.close()
                raise acceptance.AcceptanceFailure("injected response parse failure")
            return real_json(response, label)

        with patch.object(acceptance, "_json", side_effect=fail_acquire_parse):
            report = acceptance.run(self.args)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["capture_lease_release_attempted"])
        self.assertTrue(report["capture_lease_released"])
        self.assertIsNone(self.server.voice_capture.state()["owner"])

    def test_capture_lease_is_renewed_while_finalization_waits(self):
        self.transcriber.delay = 0.12
        with patch.object(acceptance, "LEASE_RENEW_INTERVAL_SECONDS", 0.02):
            report = acceptance.run(self.args)
        self.assertEqual(report["status"], "passed", report)
        self.assertGreaterEqual(self.renewals, 1)
        self.assertIsNone(self.server.voice_capture.state()["owner"])


if __name__ == "__main__":
    unittest.main()
