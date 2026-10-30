from array import array
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.ambient_segments import AmbientSegment
from jawl_voicecompanion.music_frame import build_music_frame


def _pcm(levels: list[int], *, sample_rate: int = 10) -> bytes:
    samples = array("h")
    for level in levels:
        samples.extend([level] * sample_rate)
    return samples.tobytes()


def _segment(pcm: bytes) -> AmbientSegment:
    return AmbientSegment(
        segment_id="seg-1", session_id="session", generation="gen", sequence=0,
        pcm16=pcm, sample_rate=10, channels=1, started_at=12.5, ended_at=16.5,
    )


def test_music_frame_keeps_segment_provenance_and_model_unknown() -> None:
    frame = build_music_frame(_segment(_pcm([1000] * 4)), {
        "kind": "unknown", "music_score_median": 0.2, "music_score_max": 0.9,
        "music_windows": 0, "windows": 4,
    }).as_dict()
    assert frame["state"] == "unknown"
    assert frame["segment_id"] == "seg-1"
    assert frame["started_at_monotonic"] == 12.5
    assert frame["ended_at_monotonic"] == 16.5
    assert frame["processed_at_monotonic"] >= frame["ended_at_monotonic"]
    assert frame["age_ms"] >= 0
    assert frame["source"] == "system_audio_loopback"
    assert frame["calibrated"] is False
    assert frame["energy_trend"] == "stable"


def test_music_frame_accepts_explicit_fixture_provenance() -> None:
    frame = build_music_frame(_segment(_pcm([1000] * 4)), {"kind": "unknown"},
                              source="local_fixture_replay")
    assert frame.source == "local_fixture_replay"
    assert frame.age_ms >= 0


def test_music_frame_energy_trend_requires_sustained_change() -> None:
    rising = build_music_frame(_segment(_pcm([500, 1000, 4000, 12000])), {"kind": "music"})
    falling = build_music_frame(_segment(_pcm([12000, 4000, 1000, 500])), {"kind": "music"})
    assert rising.energy_trend == "rising"
    assert falling.energy_trend == "falling"
    assert rising.state == falling.state == "music"


def test_music_frame_silence_and_short_audio_abstain_on_trend() -> None:
    silence = build_music_frame(_segment(_pcm([0] * 4)), {"kind": "music"})
    short = build_music_frame(_segment(_pcm([5000])), {"kind": "music"})
    assert silence.rms_dbfs is not None and silence.rms_dbfs <= -55
    assert silence.energy_trend == "unknown"
    assert short.energy_trend == "unknown"
