import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_audio_pipeline_profile as profile  # noqa: E402


class AudioPipelineProfileTests(unittest.TestCase):
    def test_loopback_guard_rejects_remote_and_credentials(self):
        with self.assertRaises(ValueError):
            profile._loopback_url("https://example.test")
        with self.assertRaises(ValueError):
            profile._loopback_url("http://user:pass@127.0.0.1:2367")

    def test_dry_run_does_not_open_companion(self):
        args = Namespace(
            url="http://127.0.0.1:2367", wav=Path("missing.wav"), session="s",
            chunk_frames=2048, timeout=2.0, max_end_seconds=8.0, tts_voice="ru_f1", skip_tts=False, live=False,
            dry_run=True, report=None,
        )
        with patch.object(profile, "build_opener") as opener:
            self.assertEqual(profile.run(args), 0)
            opener.assert_not_called()

    def test_audio_info_rejects_non_pcm_wav(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.wav"
            path.write_bytes(b"RIFFbad")
            with self.assertRaises(Exception):
                profile._audio_info(path.read_bytes())


if __name__ == "__main__":
    unittest.main()
