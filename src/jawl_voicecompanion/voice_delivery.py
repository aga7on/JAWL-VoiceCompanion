"""Lightweight, non-emotional acoustic measurements for a microphone utterance.

This module deliberately avoids a learned emotion classifier. It estimates a
coarse fundamental-frequency contour and short-term signal-level variation from
PCM16 already held by :class:`UtteranceBuffer`; it never writes audio or text.
The estimates are descriptive signal measurements, not claims about a speaker's
emotion, intent, health, or identity.
"""

from __future__ import annotations

from array import array
import math
import struct
import time
from typing import Any


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * max(0.0, min(1.0, fraction))
    lower = int(index)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def analyze_voice_delivery(
    pcm16: bytes, sample_rate: int, channels: int, *, observed_monotonic: float | None = None,
) -> dict[str, Any] | None:
    """Return bounded pitch/level statistics, or ``None`` when evidence is weak.

    The PCM is downsampled by block averaging (a cheap boxcar prefilter) to
    roughly 8 kHz for a small autocorrelation pitch estimate. Analysis uses
    40 ms frames at 200 ms steps; no waveform or frame series leaves this
    function.
    """
    started = time.perf_counter()
    if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) % 2:
        return None
    try:
        rate = int(sample_rate)
        channel_count = int(channels)
    except (TypeError, ValueError):
        return None
    if rate < 8000 or rate > 96000 or channel_count not in (1, 2):
        return None

    sample_count = len(pcm16) // 2
    if sample_count % channel_count:
        return None
    raw = array("h")
    raw.frombytes(pcm16)
    if struct.pack("=h", 1) != struct.pack("<h", 1):
        raw.byteswap()

    stride = max(1, round(rate / 8000))
    effective_rate = rate / stride
    mono: list[float] = []
    source_frames = sample_count // channel_count
    analysis_start_frame = max(0, source_frames - rate * 30)
    for frame_start in range(analysis_start_frame, source_frames, stride):
        frame_end = min(source_frames, frame_start + stride)
        block_sum = 0.0
        for source_frame in range(frame_start, frame_end):
            offset = source_frame * channel_count
            sample = raw[offset] if channel_count == 1 else (raw[offset] + raw[offset + 1]) * 0.5
            block_sum += sample
        mono.append(block_sum / max(1, frame_end - frame_start) / 32768.0)

    frame_size = max(160, round(effective_rate * 0.040))
    hop = max(160, round(effective_rate * 0.200))
    if len(mono) < frame_size * 3:
        return None
    min_lag = max(2, int(effective_rate / 400.0))
    max_lag = min(frame_size // 2, int(effective_rate / 65.0))
    levels_db: list[float] = []
    pitches_hz: list[float] = []
    for start in range(0, len(mono) - frame_size + 1, hop):
        frame = mono[start : start + frame_size]
        mean = sum(frame) / frame_size
        centered = [value - mean for value in frame]
        energy = sum(value * value for value in centered) / frame_size
        rms = math.sqrt(max(0.0, energy))
        if rms < 0.006:
            continue
        levels_db.append(20.0 * math.log10(max(rms, 1e-8)))
        energy_prefix = [0.0]
        for value in centered:
            energy_prefix.append(energy_prefix[-1] + value * value)

        def correlation_at(lag: int) -> float:
            left_energy = energy_prefix[frame_size - lag]
            right_energy = energy_prefix[frame_size] - energy_prefix[lag]
            if left_energy <= 1e-10 or right_energy <= 1e-10:
                return 0.0
            numerator = sum(a * b for a, b in zip(centered[:-lag], centered[lag:]))
            return numerator / math.sqrt(left_energy * right_energy)

        best_score = 0.0
        best_lag = 0
        for lag in range(min_lag, max_lag + 1):
            score = correlation_at(lag)
            if score > best_score:
                best_score, best_lag = score, lag
        if best_lag and best_score >= 0.45:
            # Parabolic interpolation reduces the quantization error from the
            # integer-lag search without making the estimate look exact.
            offset = 0.0
            if min_lag < best_lag < max_lag:
                corr = [correlation_at(lag) for lag in (best_lag - 1, best_lag, best_lag + 1)]
                divisor = corr[0] - 2.0 * corr[1] + corr[2]
                if abs(divisor) > 1e-9:
                    offset = max(-0.5, min(0.5, 0.5 * (corr[0] - corr[2]) / divisor))
            pitches_hz.append(effective_rate / (best_lag + offset))

    if len(levels_db) < 3:
        return None
    result: dict[str, Any] = {
        "duration_ms": round((sample_count / channel_count) * 1000.0 / rate, 1),
        "observed_monotonic": float(observed_monotonic) if observed_monotonic is not None else None,
        "signal_level_p10_dbfs": round(_percentile(levels_db, 0.10), 1),
        "signal_level_p90_dbfs": round(_percentile(levels_db, 0.90), 1),
        "voiced_frame_ratio": round(len(pitches_hz) / max(1, len(levels_db)), 3),
        "pitch_estimate_method": "coarse_pcm_autocorrelation",
    }
    if len(pitches_hz) >= 5:
        result["pitch_median_hz"] = round(_percentile(pitches_hz, 0.50), 1)
        result["pitch_p10_hz"] = round(_percentile(pitches_hz, 0.10), 1)
        result["pitch_p90_hz"] = round(_percentile(pitches_hz, 0.90), 1)
    result["analysis_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return result


__all__ = ["analyze_voice_delivery"]
