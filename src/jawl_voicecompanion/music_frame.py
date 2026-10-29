"""Small, deterministic telemetry frame for the independent music lane."""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from math import log10, sqrt
import sys
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class MusicFrame:
    schema_version: int
    segment_id: str
    source: str
    started_at_monotonic: float
    ended_at_monotonic: float
    processed_at_monotonic: float
    age_ms: float
    state: str
    music_score_median: float | None
    music_score_max: float | None
    music_windows: int | None
    windows: int | None
    rms_dbfs: float | None
    energy_trend: str
    calibrated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _energy_trend(pcm16: bytes, sample_rate: int, channels: int) -> tuple[float | None, str]:
    if sample_rate <= 0 or channels not in (1, 2) or len(pcm16) < channels * 2:
        return None, "unknown"
    samples = array("h")
    usable = len(pcm16) - (len(pcm16) % (channels * 2))
    samples.frombytes(pcm16[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    frame_count = len(samples) // channels
    if frame_count == 0:
        return None, "unknown"
    bin_frames = max(1, sample_rate)
    rms_bins: list[float] = []
    total_squares = 0.0
    total_frames = 0
    for start in range(0, frame_count, bin_frames):
        end = min(frame_count, start + bin_frames)
        squares = 0.0
        for frame in range(start, end):
            base = frame * channels
            value = sum(samples[base : base + channels]) / channels
            square = value * value
            squares += square
            total_squares += square
            total_frames += 1
        rms_bins.append(sqrt(squares / max(1, end - start)) / 32768.0)
    overall = sqrt(total_squares / max(1, total_frames)) / 32768.0
    dbfs = max(-120.0, 20.0 * log10(max(overall, 1e-6)))
    if dbfs < -55 or len(rms_bins) < 3:
        return round(dbfs, 2), "unknown"
    # Compare robust first/last thirds; require a 6 dB shift to avoid calling
    # normal dynamics a trend. This is energy telemetry, not a music mood label.
    third = max(1, len(rms_bins) // 3)
    first = sum(rms_bins[:third]) / third
    last = sum(rms_bins[-third:]) / third
    delta_db = 20.0 * log10(max(last, 1e-6) / max(first, 1e-6))
    trend = "rising" if delta_db >= 6.0 else "falling" if delta_db <= -6.0 else "stable"
    return round(dbfs, 2), trend


def build_music_frame(
    segment: Any,
    soundscape: dict[str, Any],
    *,
    source: str = "system_audio_loopback",
) -> MusicFrame:
    rms, trend = _energy_trend(segment.pcm16, int(segment.sample_rate), int(segment.channels))
    processed_at = monotonic()
    kind = str(soundscape.get("kind") or "unknown").lower()
    return MusicFrame(
        schema_version=1,
        segment_id=str(segment.segment_id),
        source=str(source or "unknown")[:80],
        started_at_monotonic=float(segment.started_at),
        ended_at_monotonic=float(segment.ended_at),
        processed_at_monotonic=processed_at,
        age_ms=round(max(0.0, processed_at - float(segment.ended_at)) * 1000.0, 1),
        state="music" if kind == "music" else "unknown",
        music_score_median=soundscape.get("music_score_median"),
        music_score_max=soundscape.get("music_score_max"),
        music_windows=soundscape.get("music_windows"),
        windows=soundscape.get("windows"),
        rms_dbfs=rms,
        energy_trend=trend,
        calibrated=bool(soundscape.get("calibrated", False)),
    )


__all__ = ["MusicFrame", "build_music_frame"]
