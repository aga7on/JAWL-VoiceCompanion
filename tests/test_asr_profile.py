import io
import json
import sys
import tempfile
import unittest
import wave
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_asr_profile as profile  # noqa: E402
from jawl_voicecompanion.asr import ASRNoSpeech  # noqa: E402


def _write_fixture_wav(path: Path, sample_bytes: bytes | None = None) -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(sample_bytes or (b"\0\0" * 1600))
    path.write_bytes(output.getvalue())


class ASRProfileTests(unittest.TestCase):
    def test_loopback_guard_rejects_remote_and_credentials(self):
        with self.assertRaises(ValueError):
            profile._loopback_url("https://example.test/v1")
        with self.assertRaises(ValueError):
            profile._loopback_url("http://user:pass@127.0.0.1:8984/v1")

    def test_dry_run_does_not_construct_provider(self):
        args = Namespace(
            url="http://127.0.0.1:8984/v1", model="Qwen3-ASR-0.6B", wav=[Path("missing.wav")],
            timeout=2.0, allow_live_model=False, dry_run=True, report=None, expects=None,
        )
        with patch.object(profile, "OpenAICompatibleASRClient") as client:
            self.assertEqual(profile.run(args), 0)
            client.assert_not_called()

    def test_profile_requires_non_empty_transcript_and_writes_report(self):
        class Client:
            def __init__(self, *_args, **_kwargs):
                pass

            def health(self):
                return {"status": "online", "mode": "final_utterance", "model": "Qwen3-ASR-0.6B"}

            def transcribe(self, *_args, **_kwargs):
                return "тест"

        with tempfile.TemporaryDirectory() as root, patch.object(profile, "OpenAICompatibleASRClient", Client):
            wav_path = Path(root) / "fixture.wav"
            _write_fixture_wav(wav_path)
            report_path = Path(root) / "report.json"
            args = Namespace(
                url="http://127.0.0.1:8984/v1", model="Qwen3-ASR-0.6B", wav=[wav_path],
                timeout=2.0, allow_live_model=True, dry_run=False, report=report_path, expects=None,
            )
            self.assertEqual(profile.run(args), 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["samples"][0]["non_empty"])
        self.assertTrue(report["samples"][0]["accepted"])

    def test_manifest_expectations_tolerate_no_speech_only_when_allowed(self):
        class QuietClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def health(self):
                return {"status": "online", "mode": "final_utterance", "model": "Qwen3-ASR-0.6B"}

            def transcribe(self, *_args, **_kwargs):
                raise ASRNoSpeech("no speech text")

        with tempfile.TemporaryDirectory() as root, patch.object(profile, "OpenAICompatibleASRClient", QuietClient):
            noise_path = Path(root) / "noise_only.wav"
            speech_path = Path(root) / "tempo_slow.wav"
            _write_fixture_wav(noise_path)
            _write_fixture_wav(speech_path)
            manifest = Path(root) / "cases.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "cases": [
                    {"file": "noise_only.wav", "must_transcribe": False, "min_chars": 0},
                    {"file": "tempo_slow.wav", "must_transcribe": True, "min_chars": 1},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            report_path = Path(root) / "report.json"
            args = Namespace(
                url="http://127.0.0.1:8984/v1", model="Qwen3-ASR-0.6B",
                wav=[speech_path, noise_path], timeout=2.0, allow_live_model=True,
                dry_run=False, report=report_path, expects=manifest,
            )
            self.assertEqual(profile.run(args), 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        by_file = {item["file"]: item for item in report["samples"]}
        self.assertEqual(report["status"], "failed")
        self.assertTrue(by_file["noise_only.wav"]["accepted_empty"])
        self.assertTrue(by_file["noise_only.wav"]["accepted"], "tolerated no-speech must still count for coverage")
        self.assertFalse(by_file["tempo_slow.wav"]["accepted"], "missing required speech must fail the profile")


if __name__ == "__main__":
    unittest.main()