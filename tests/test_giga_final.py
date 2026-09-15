import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.giga_final import (  # noqa: E402
    CrispASRFileTranscriber,
    GigaAMBatchError,
)


class CrispASRFileTranscriberTests(unittest.TestCase):
    def test_prefetch_reads_the_whole_model_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.gguf"
            model.write_bytes(b"x" * 300_000)
            transcriber = CrispASRFileTranscriber("crispasr.exe", str(model))
            self.assertEqual(transcriber.prefetch(chunk_bytes=65_536), 300_000)
            missing = CrispASRFileTranscriber("crispasr.exe", str(Path(tmp) / "missing.gguf"))
            self.assertEqual(missing.prefetch(), 0)

    def test_missing_executable_raises_batch_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model.gguf"
            model.write_bytes(b"x")
            transcriber = CrispASRFileTranscriber(str(Path(tmp) / "no-such-crispasr.exe"), str(model))
            with self.assertRaises(GigaAMBatchError):
                transcriber.transcribe(b"RIFF....WAVE")


if __name__ == "__main__":
    unittest.main()
