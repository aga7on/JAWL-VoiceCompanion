"""UtteranceBuffer tests: the bounded PCM16 buffer in front of canonical GigaAM.

GigaAM (crispasr file mode) is the only ASR engine, so the buffer never talks to
a network provider: it collects browser/ambient PCM16 and hands one WAV per
utterance to the injected ``giga_final.CrispASRFileTranscriber``. These tests use
stub transcriber objects, so no crispasr process, model file or socket is needed.
"""

import io
import sys
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.asr import (  # noqa: E402
    MAX_ASR_TEXT_CHARS,
    MAX_UTTERANCE_BYTES,
    UtteranceBuffer,
)


class _StubTranscriber:
    """Stand-in for the canonical GigaAM batch transcriber."""

    def __init__(self, text="тестовая фраза"):
        self.text = text
        self.wavs = []

    def transcribe(self, wav_bytes):
        self.wavs.append(wav_bytes)
        return self.text


class _RaisingTranscriber:
    def __init__(self, error=None):
        self.error = error or RuntimeError("crispasr exited with code 1")
        self.calls = 0

    def transcribe(self, wav_bytes):
        self.calls += 1
        raise self.error


class _FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def _pcm(frames=1600):
    return b"\x01\x00" * frames


class BufferingTests(unittest.TestCase):
    def test_feed_audio_buffers_pcm16_and_reports_the_gigaam_final_mode(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        buffered = buffer.feed_audio(
            _pcm(1600), sample_rate=16000, channels=1, session_id="browser-mic",
        )

        self.assertEqual(buffered["status"], "buffered")
        self.assertEqual(buffered["mode"], "gigaam_final")
        self.assertEqual(buffered["bytes"], 3200)
        self.assertEqual(buffered["sample_rate"], 16000)
        self.assertEqual(buffered["channels"], 1)
        self.assertFalse(buffered["raw_audio_persisted"])
        state = buffer.state()
        self.assertEqual(state["active_sessions"], 1)
        self.assertEqual(state["buffered_bytes"], 3200)
        self.assertFalse(state["raw_audio_persisted"])

    def test_feed_audio_accumulates_chunks_until_the_utterance_ends(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        first = buffer.feed_audio(_pcm(800), sample_rate=16000, channels=2, session_id="s")
        second = buffer.feed_audio(_pcm(200), sample_rate=16000, channels=2, session_id="s")

        self.assertEqual(first["bytes"], 1600)
        self.assertEqual(second["bytes"], 2000)
        self.assertEqual(buffer.state()["active_sessions"], 1)
        self.assertEqual(buffer.state()["buffered_bytes"], 2000)

    def test_feed_audio_rejects_invalid_pcm_and_format(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        for kwargs in (
            {"pcm16": b"", "sample_rate": 16000, "channels": 1},
            {"pcm16": b"\x01", "sample_rate": 16000, "channels": 1},
            {"pcm16": _pcm(8), "sample_rate": 7999, "channels": 1},
            {"pcm16": _pcm(8), "sample_rate": 96001, "channels": 1},
            {"pcm16": _pcm(8), "sample_rate": True, "channels": 1},
            {"pcm16": _pcm(8), "sample_rate": 16000, "channels": 0},
            {"pcm16": _pcm(8), "sample_rate": 16000, "channels": 3},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    buffer.feed_audio(session_id="invalid", **kwargs)
        self.assertEqual(buffer.state()["active_sessions"], 0)

    def test_audio_format_cannot_change_inside_one_utterance(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="fixed")

        with self.assertRaises(ValueError) as rate_error:
            buffer.feed_audio(_pcm(64), sample_rate=48000, channels=1, session_id="fixed")
        self.assertIn("format", str(rate_error.exception))
        with self.assertRaises(ValueError):
            buffer.feed_audio(_pcm(64), sample_rate=16000, channels=2, session_id="fixed")

        self.assertEqual(buffer.state()["buffered_bytes"], 128, "a rejected chunk must not be stored")
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="fixed")
        self.assertEqual(buffer.state()["buffered_bytes"], 256, "the first 128 bytes plus the accepted 128 bytes")

    def test_utterance_byte_limit_is_bounded_and_drops_the_overflowing_session(self):
        buffer = UtteranceBuffer(_StubTranscriber(), max_utterance_bytes=32768)
        self.assertEqual(buffer.max_utterance_bytes, 32768)
        buffer.feed_audio(b"\x00\x00" * 16384, sample_rate=16000, channels=1, session_id="loud")
        self.assertEqual(buffer.state()["buffered_bytes"], 32768)

        with self.assertRaises(ValueError) as error:
            buffer.feed_audio(b"\x00\x00", sample_rate=16000, channels=1, session_id="loud")
        self.assertIn("byte limit", str(error.exception))
        self.assertEqual(buffer.state()["active_sessions"], 0)
        self.assertEqual(buffer.finish("loud")["status"], "empty")

    def test_configured_byte_limit_is_clamped_into_the_supported_range(self):
        low = UtteranceBuffer(_StubTranscriber(), max_utterance_bytes=1)
        high = UtteranceBuffer(_StubTranscriber(), max_utterance_bytes=MAX_UTTERANCE_BYTES * 4)

        self.assertEqual(low.max_utterance_bytes, 32 * 1024)
        self.assertEqual(high.max_utterance_bytes, MAX_UTTERANCE_BYTES)

    def test_concurrent_sessions_are_bounded(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        for index in range(8):
            buffer.feed_audio(_pcm(8), sample_rate=16000, channels=1, session_id=f"s{index}")
        self.assertEqual(buffer.state()["active_sessions"], 8)

        with self.assertRaises(ValueError) as error:
            buffer.feed_audio(_pcm(8), sample_rate=16000, channels=1, session_id="s8")
        self.assertIn("session limit", str(error.exception))

    def test_missing_session_id_falls_back_to_a_local_session(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        buffered = buffer.feed_audio(_pcm(8), sample_rate=16000, channels=1, session_id="")

        self.assertEqual(buffered["status"], "buffered")
        self.assertEqual(buffer.to_wav("") is not None, True)
        self.assertEqual(buffer.finish("")["status"], "transcribed")


class FinishTests(unittest.TestCase):
    def test_finish_transcribes_the_buffered_utterance_and_clears_the_session(self):
        transcriber = _StubTranscriber("Привет, компаньон.")
        buffer = UtteranceBuffer(transcriber)
        buffer.feed_audio(_pcm(1600), sample_rate=16000, channels=1, session_id="browser-mic")

        result = buffer.finish("browser-mic")

        self.assertEqual(result["status"], "transcribed")
        self.assertEqual(result["text"], "Привет, компаньон.")
        self.assertEqual(result["bytes"], 3200)
        self.assertFalse(result["raw_audio_persisted"])
        self.assertEqual(buffer.state()["active_sessions"], 0)
        self.assertEqual(len(transcriber.wavs), 1)
        with wave.open(io.BytesIO(transcriber.wavs[0]), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), _pcm(1600))
        self.assertEqual(buffer.finish("browser-mic")["status"], "empty")
        self.assertEqual(len(transcriber.wavs), 1, "an empty session must not reach GigaAM")

    def test_finish_truncates_an_unbounded_transcript(self):
        buffer = UtteranceBuffer(_StubTranscriber("а" * (MAX_ASR_TEXT_CHARS + 500)))
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="long")

        result = buffer.finish("long")

        self.assertEqual(result["status"], "transcribed")
        self.assertEqual(len(result["text"]), MAX_ASR_TEXT_CHARS)

    def test_finish_on_a_missing_session_is_empty(self):
        transcriber = _StubTranscriber()
        buffer = UtteranceBuffer(transcriber)

        result = buffer.finish("never-fed")

        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["text"], "")
        self.assertFalse(result["raw_audio_persisted"])
        self.assertEqual(transcriber.wavs, [])

    def test_finish_without_a_transcriber_is_unavailable(self):
        buffer = UtteranceBuffer(None)
        buffer.feed_audio(_pcm(1600), sample_rate=16000, channels=1, session_id="no-engine")

        self.assertFalse(buffer.configured)
        result = buffer.finish("no-engine")

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["bytes"], 3200)
        self.assertIn("not configured", result["error"])
        self.assertEqual(buffer.state()["active_sessions"], 0, "the failed session is discarded")

    def test_finish_reports_a_transcriber_failure_instead_of_masking_it(self):
        transcriber = _RaisingTranscriber(TimeoutError("crispasr timed out"))
        buffer = UtteranceBuffer(transcriber)
        buffer.feed_audio(_pcm(1600), sample_rate=16000, channels=1, session_id="broken")

        result = buffer.finish("broken")

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["bytes"], 3200)
        self.assertEqual(result["error"], "TimeoutError: crispasr timed out")
        self.assertEqual(transcriber.calls, 1)
        self.assertEqual(buffer.state()["active_sessions"], 0)

    def test_finish_maps_an_empty_transcript_to_no_speech(self):
        transcriber = _StubTranscriber("   ")
        buffer = UtteranceBuffer(transcriber)
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="quiet")

        result = buffer.finish("quiet")

        self.assertEqual(result["status"], "no_speech")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["bytes"], 128)
        self.assertEqual(buffer.state()["active_sessions"], 0)

    def test_finish_is_never_called_twice_for_one_utterance(self):
        transcriber = _StubTranscriber()
        buffer = UtteranceBuffer(transcriber)
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="once")

        self.assertEqual(buffer.finish("once")["status"], "transcribed")
        self.assertEqual(buffer.finish("once")["status"], "empty")
        self.assertEqual(len(transcriber.wavs), 1)


class SessionLifecycleTests(unittest.TestCase):
    def test_discard_drops_the_utterance_without_calling_the_transcriber(self):
        transcriber = _StubTranscriber()
        buffer = UtteranceBuffer(transcriber)
        buffer.feed_audio(_pcm(1600), sample_rate=16000, channels=1, session_id="cancelled")

        discarded = buffer.discard("cancelled")

        self.assertEqual(discarded["status"], "discarded")
        self.assertEqual(discarded["bytes"], 3200)
        self.assertFalse(discarded["raw_audio_persisted"])
        self.assertEqual(transcriber.wavs, [])
        self.assertEqual(buffer.state()["active_sessions"], 0)
        self.assertEqual(buffer.discard("cancelled")["status"], "empty")

    def test_to_wav_peeks_without_clearing_the_utterance(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        self.assertIsNone(buffer.to_wav("peek"))
        buffer.feed_audio(_pcm(1600), sample_rate=16000, channels=2, session_id="peek")

        wav_bytes = buffer.to_wav("peek")

        self.assertIsNotNone(wav_bytes)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 2)
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.getnframes(), 800, "3200 bytes of interleaved stereo PCM16")
            self.assertEqual(wav_file.readframes(800), _pcm(1600))
        self.assertEqual(buffer.state()["buffered_bytes"], 3200)
        self.assertEqual(buffer.finish("peek")["status"], "transcribed")

    def test_stale_sessions_expire_on_the_injected_clock(self):
        transcriber = _StubTranscriber()
        clock = _FakeClock()
        buffer = UtteranceBuffer(transcriber, session_ttl_seconds=10.0, clock=clock)
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="stale")
        self.assertEqual(buffer.state()["active_sessions"], 1)

        clock.now = 20.0
        state = buffer.state()

        self.assertEqual(state["active_sessions"], 0)
        self.assertEqual(state["buffered_bytes"], 0)
        self.assertEqual(buffer.finish("stale")["status"], "empty")
        self.assertEqual(transcriber.wavs, [], "an abandoned utterance must never reach GigaAM")

        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="fresh")
        self.assertEqual(buffer.state()["active_sessions"], 1, "a new session works after eviction")

    def test_a_touched_session_survives_the_ttl_window(self):
        transcriber = _StubTranscriber()
        clock = _FakeClock()
        buffer = UtteranceBuffer(transcriber, session_ttl_seconds=10.0, clock=clock)
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="alive")
        clock.now = 9.0
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="alive")
        clock.now = 15.0

        self.assertEqual(buffer.state()["active_sessions"], 1)
        self.assertEqual(buffer.finish("alive")["status"], "transcribed")

    def test_configured_session_ttl_is_clamped(self):
        self.assertEqual(UtteranceBuffer(_StubTranscriber(), session_ttl_seconds=0.1).session_ttl_seconds, 10.0)
        self.assertEqual(UtteranceBuffer(_StubTranscriber(), session_ttl_seconds=9999.0).session_ttl_seconds, 600.0)

    def test_close_clears_every_buffered_session(self):
        transcriber = _StubTranscriber()
        buffer = UtteranceBuffer(transcriber)
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="a")
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="b")

        buffer.close()

        state = buffer.state()
        self.assertEqual(state["active_sessions"], 0)
        self.assertEqual(state["buffered_bytes"], 0)
        self.assertEqual(buffer.finish("a")["status"], "empty")
        self.assertEqual(transcriber.wavs, [])


class HealthTests(unittest.TestCase):
    def test_configured_buffer_reports_the_gigaam_engine(self):
        buffer = UtteranceBuffer(_StubTranscriber())
        buffer.feed_audio(_pcm(64), sample_rate=16000, channels=1, session_id="health")

        health = buffer.health()

        self.assertTrue(buffer.configured)
        self.assertTrue(health["configured"])
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["engine"], "gigaam")
        self.assertEqual(health["mode"], "gigaam_final")
        self.assertEqual(health["active_sessions"], 1)
        self.assertEqual(health["buffered_bytes"], 128)
        self.assertEqual(health["max_utterance_bytes"], MAX_UTTERANCE_BYTES)
        self.assertFalse(health["raw_audio_persisted"])

    def test_unconfigured_buffer_reports_not_configured(self):
        health = UtteranceBuffer(None).health()

        self.assertFalse(health["configured"])
        self.assertEqual(health["status"], "not_configured")
        self.assertEqual(health["engine"], "gigaam")
        self.assertEqual(health["active_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
