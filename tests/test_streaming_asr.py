import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.streaming_asr import StreamingASRBridge  # noqa: E402


class StreamingASRBridgeTests(unittest.TestCase):
    def _bridge(self):
        return StreamingASRBridge("missing-crispasr.exe", "missing-model.gguf")

    def test_disabled_when_executable_missing(self):
        bridge = self._bridge()
        self.assertFalse(bridge._ensure_started())
        self.assertTrue(bridge.disabled)
        # feed() must stay a silent no-op once failed
        bridge.feed(b"\x00\x00" * 160)

    def test_partial_and_silence_state(self):
        bridge = self._bridge()
        bridge.fed_seconds = 3.0
        bridge._apply_event({"type": "partial", "text": "Привет, я думаю", "t1": 2.0})
        snap = bridge.snapshot()
        self.assertEqual(snap["text"], "Привет, я думаю")
        self.assertGreaterEqual(snap["silence_ms"], 900.0)
        bridge._apply_event({"type": "silence"})
        self.assertGreaterEqual(bridge.snapshot()["silence_ms"], 900.0)

    def test_reset_clears_partial(self):
        bridge = self._bridge()
        bridge.fed_seconds = 2.0
        bridge._apply_event({"type": "partial", "text": "тест", "t1": 1.0})
        bridge.reset_utterance()
        snap = bridge.snapshot()
        self.assertEqual(snap["text"], "")
        self.assertEqual(snap["silence_ms"], 0.0)

    def test_downmix_and_resample(self):
        import numpy as np
        stereo_48k = np.zeros(4800 * 2, dtype="<i2")
        stereo_48k[::2] = 1000
        out = StreamingASRBridge._to_mono16k(stereo_48k.tobytes(), 48000, 2)
        mono = np.frombuffer(out, dtype="<i2")
        self.assertEqual(len(mono), 1600)
        self.assertTrue((mono == 500).all())


if __name__ == "__main__":
    unittest.main()
