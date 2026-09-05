import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_teratts_profile as profile  # noqa: E402


class TeraTTSProfileTests(unittest.TestCase):
    def test_loopback_guard_rejects_remote_and_credentials(self):
        with self.assertRaises(ValueError):
            profile._loopback_url("https://example.test")
        with self.assertRaises(ValueError):
            profile._loopback_url("http://user:pass@127.0.0.1:9889")

    def test_dry_run_does_not_construct_provider(self):
        args = Namespace(
            url="http://127.0.0.1:9889", voice="ru_f1", speed=1.0,
            timeout=2.0, requests=1, texts=[], allow_live_model=False,
            dry_run=True, report=None,
        )
        with patch.object(profile, "TeraTTSHttpClient") as client:
            self.assertEqual(profile.run(args), 0)
            client.assert_not_called()

    def test_live_profile_validates_wav_and_writes_bounded_report(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b""

        def wav():
            import io
            import wave

            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setnchannels(1)
                result.setsampwidth(2)
                result.setframerate(22050)
                result.writeframes(b"\0\0" * 2205)
            return output.getvalue()

        class Client:
            def __init__(self, *_args, **_kwargs):
                pass

            def health(self):
                return {"status": "ok", "model": "TeraTTSv2", "sample_rate": 22050}

            def synthesize(self, *_args, **_kwargs):
                return wav()

        args = Namespace(
            url="http://127.0.0.1:9889", voice="ru_f1", speed=1.0,
            timeout=2.0, requests=2, texts=["Привет"], allow_live_model=True,
            dry_run=False, report=None,
        )
        with tempfile.TemporaryDirectory() as root, patch.object(profile, "TeraTTSHttpClient", Client):
            args.report = Path(root) / "report.json"
            self.assertEqual(profile.run(args), 0)
            report = json.loads(args.report.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["samples"]), 2)
        self.assertEqual(report["samples"][0]["sample_rate"], 22050)


if __name__ == "__main__":
    unittest.main()
