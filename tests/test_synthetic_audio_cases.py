"""Unit tests for the deterministic synthetic acoustic case generator."""

from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import sys
from pathlib import Path as _P

ROOT = _P(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_synthetic_audio_cases import make_cases  # noqa: E402

EXPECTED_CASES = [
    "tempo_slow.wav",
    "pause_short.wav",
    "pause_long.wav",
    "quiet.wav",
    "faint.wav",
    "noisy_snr10.wav",
    "noisy_snr0.wav",
    "noise_only.wav",
    "phrase_end_0.wav",
    "phrase_end_400.wav",
    "phrase_end_800.wav",
    "consecutive_two.wav",
]


def _make_source_wav(path: Path, rate: int, seconds: float, amplitude: int = 8000) -> None:
    samples = []
    for index in range(int(rate * seconds)):
        samples.append(int(amplitude * math.sin(2.0 * math.pi * 120.0 * index / rate)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(int(frame).to_bytes(2, "little", signed=True) for frame in samples))


def _read_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def _read_rms(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("expected mono PCM16")
        frames = wav.readframes(wav.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0.0


def _db(ratio: float) -> float:
    return 20.0 * math.log10(ratio) if ratio > 0 else -math.inf


class SyntheticAudioCasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._src = self._dir / "source.wav"
        _make_source_wav(self._src, 16000, 1.0)
        self._out = self._dir / "cases"
        self._manifest = make_cases(self._src, self._out, seed=7)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generates_the_full_case_set(self) -> None:
        files = sorted(item.name for item in self._out.iterdir() if item.suffix == ".wav")
        self.assertEqual(files, sorted(EXPECTED_CASES))
        manifest_names = [item["file"] for item in self._manifest["cases"]]
        self.assertEqual(sorted(manifest_names), sorted(EXPECTED_CASES))
        self.assertEqual(self._manifest["schema_version"], 1)

    def test_manifest_round_trips_from_disk(self) -> None:
        payload = (self._out / "cases.json").read_text(encoding="utf-8").strip()
        loaded = __import__("json").loads(payload)
        self.assertEqual(len(loaded["cases"]), len(EXPECTED_CASES))
        self.assertEqual(loaded["source"], "source.wav")
        self.assertEqual(loaded["source_rate"], 16000)

    def test_tempo_slow_roughly_doubles_duration(self) -> None:
        slow = _read_duration(self._out / "tempo_slow.wav")
        self.assertAlmostEqual(slow, 2.0, delta=0.06)
        case = next(item for item in self._manifest["cases"] if item["file"] == "tempo_slow.wav")
        self.assertTrue(case["must_transcribe"])
        self.assertGreaterEqual(case["min_chars"], 1)

    def test_quiet_applies_requested_gain(self) -> None:
        source_rms = _read_rms(self._src)
        quiet_rms = _read_rms(self._out / "quiet.wav")
        self.assertAlmostEqual(_db(quiet_rms / source_rms), -18.0, delta=1.5)

    def test_faint_is_26db_below_baseline_and_tolerated(self) -> None:
        source_rms = _read_rms(self._src)
        faint_rms = _read_rms(self._out / "faint.wav")
        self.assertAlmostEqual(_db(faint_rms / source_rms), -26.0, delta=1.5)
        case = next(item for item in self._manifest["cases"] if item["file"] == "faint.wav")
        self.assertFalse(case["must_transcribe"])

    def test_noise_only_is_not_silence_and_tolerated(self) -> None:
        source_rms = _read_rms(self._src)
        noise_rms = _read_rms(self._out / "noise_only.wav")
        self.assertGreater(noise_rms, 1)
        self.assertAlmostEqual(_db(noise_rms / source_rms), 0.0, delta=3.0)
        case = next(item for item in self._manifest["cases"] if item["file"] == "noise_only.wav")
        self.assertFalse(case["must_transcribe"])

    def test_noisy_snr0_is_tolerated_and_snr10_required(self) -> None:
        by_file = {item["file"]: item for item in self._manifest["cases"]}
        self.assertFalse(by_file["noisy_snr0.wav"]["must_transcribe"])
        self.assertTrue(by_file["noisy_snr10.wav"]["must_transcribe"])

    def test_pause_and_consecutive_durations(self) -> None:
        source = _read_duration(self._src)
        self.assertAlmostEqual(_read_duration(self._out / "pause_long.wav"), source + 2.0, delta=0.05)
        self.assertAlmostEqual(_read_duration(self._out / "consecutive_two.wav"), 2.0 * source + 0.5, delta=0.05)

    def test_consecutive_two_requires_two_chars(self) -> None:
        case = next(item for item in self._manifest["cases"] if item["file"] == "consecutive_two.wav")
        self.assertTrue(case["must_transcribe"])
        self.assertGreaterEqual(case["min_chars"], 2)

    def test_same_seed_is_bit_identical(self) -> None:
        out2 = self._dir / "cases2"
        make_cases(self._src, out2, seed=7)
        a = (self._out / "tempo_slow.wav").read_bytes()
        b = (out2 / "tempo_slow.wav").read_bytes()
        self.assertEqual(a, b)

    def test_all_cases_respect_duration_bound(self) -> None:
        for case in self._manifest["cases"]:
            self.assertLessEqual(case["duration_seconds"], 60.0)


if __name__ == "__main__":
    unittest.main()