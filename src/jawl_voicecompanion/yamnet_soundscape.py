"""Small CPU-only rolling soundscape classifier backed by YAMNet ONNX.

YAMNet is used here for persistent event evidence (especially music), not as a
free-form audio captioner. ASR remains a separate lane and may coexist with the
soundscape result for the same PCM segment.
"""
from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_YAMNET_DIR = (
    Path(__file__).resolve().parents[2]
    / "runtime/models/audio/yamnet-onnx-f25b741c2f0bdc6d7e6db24b5fddda23347dbafd"
)
# A model score of 0.30 let a stationary two-tone synthetic control through as
# music (and emitted an unsupported "Singing bowl" tag). A 0.35 cut retained
# all 18 source-disjoint FMA positives while rejecting the checked synthetic
# noise/tone controls; this is an operating threshold, not calibrated confidence.
MUSIC_THRESHOLD = 0.35
MIN_MUSIC_WINDOWS = 2
MIN_RMS_DBFS = -55.0
WINDOW_SAMPLES = 2 * 16000
HOP_SAMPLES = 16000
_IGNORED_TAGS = frozenset({
    "Music", "Speech", "Silence", "Background music", "Musical instrument",
})


class YamnetSoundscapeDetector:
    """Classify bounded PCM clips with one-thread ONNX CPU inference."""

    name = "yamnet-onnx-cpu"

    def __init__(
        self,
        model_dir: str | Path = DEFAULT_YAMNET_DIR,
        *,
        session: Any | None = None,
        tag_threshold: float = 0.15,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.tag_threshold = max(0.05, min(float(tag_threshold), 0.95))
        model_path = self.model_dir / "yamnet.onnx"
        class_map = self.model_dir / "yamnet_class_map.csv"
        if session is None:
            if not model_path.is_file() or not class_map.is_file():
                raise FileNotFoundError("YAMNet ONNX model or class map is unavailable")
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        providers = list(session.get_providers()) if hasattr(session, "get_providers") else ["CPUExecutionProvider"]
        if providers != ["CPUExecutionProvider"]:
            raise RuntimeError("YAMNet soundscape inference must use CPUExecutionProvider only")
        self.session = session
        if class_map.is_file():
            rows = class_map.read_text(encoding="utf-8-sig").splitlines()[1:]
            self.labels = [row.split(",", 2)[2].strip().strip('"') for row in rows]
        elif session is not None and hasattr(session, "labels"):
            self.labels = list(session.labels)
        else:
            raise FileNotFoundError("YAMNet class map is unavailable")
        if "Music" not in self.labels or "Speech" not in self.labels:
            raise ValueError("YAMNet class map is missing core event labels")
        self.music_index = self.labels.index("Music")
        self.speech_index = self.labels.index("Speech")

    @staticmethod
    def _to_mono_16k(pcm16: bytes, sample_rate: int, channels: int) -> np.ndarray:
        if not isinstance(pcm16, bytes) or not pcm16 or len(pcm16) % 2:
            raise ValueError("soundscape input must be non-empty PCM16")
        if isinstance(sample_rate, bool) or not 8000 <= int(sample_rate) <= 96000:
            raise ValueError("soundscape sample rate is unsupported")
        if isinstance(channels, bool) or not 1 <= int(channels) <= 2:
            raise ValueError("soundscape channels must be one or two")
        pcm = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        if channels == 2:
            pcm = pcm[: len(pcm) - (len(pcm) % 2)].reshape(-1, 2).mean(axis=1)
        if int(sample_rate) != 16000:
            target_count = max(1, round(len(pcm) * 16000 / int(sample_rate)))
            source_positions = np.arange(len(pcm), dtype=np.float32)
            target_positions = np.arange(target_count, dtype=np.float32) * int(sample_rate) / 16000
            pcm = np.interp(target_positions, source_positions, pcm).astype(np.float32)
        return pcm

    def describe(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        channels: int,
        clip_id: str = "audio-clip",
    ) -> dict[str, Any]:
        waveform = self._to_mono_16k(pcm16, sample_rate, channels)
        duration = len(waveform) / 16000.0
        rms = float(np.sqrt(np.mean(waveform * waveform))) if waveform.size else 0.0
        rms_dbfs = 20.0 * np.log10(max(rms, 1e-8))
        base: dict[str, Any] = {
            "schema_version": 1,
            "clip_id": str(clip_id or "audio-clip")[:120],
            "kind": "unknown",
            "description": "No reliable audio event detected.",
            "tags": [],
            "mood": "",
            "confidence": 0.0,
            "duration_seconds": round(min(duration, 30.0), 3),
            "raw_audio_persisted": False,
            "detector": self.name,
            "calibrated": False,
            "windows": 0,
            "music_windows": 0,
            "music_score_max": None,
            "music_score_median": None,
        }
        if duration <= 0 or duration > 30.0 or rms_dbfs < MIN_RMS_DBFS or duration < 2.0:
            return base

        starts = list(range(
            0,
            max(1, len(waveform) - WINDOW_SAMPLES + HOP_SAMPLES),
            HOP_SAMPLES,
        ))
        rows: list[np.ndarray] = []
        for start in starts:
            frame = waveform[start : start + WINDOW_SAMPLES]
            if len(frame) < WINDOW_SAMPLES:
                frame = np.pad(frame, (0, WINDOW_SAMPLES - len(frame)))
            scores = np.asarray(
                self.session.run(None, {"waveform": frame.astype(np.float32)})[0],
                dtype=np.float32,
            ).mean(axis=0).reshape(-1)
            rows.append(scores)
        if not rows:
            return base
        music_scores = [float(row[self.music_index]) for row in rows]
        music_hits = sum(score >= MUSIC_THRESHOLD for score in music_scores)
        music_score_max = round(max(music_scores), 4)
        music_score_median = round(float(np.median(music_scores)), 4)
        required_hits = MIN_MUSIC_WINDOWS if len(rows) < 8 else max(
            MIN_MUSIC_WINDOWS, ceil(len(rows) * 0.25)
        )
        if music_hits < required_hits:
            return {
                **base,
                "windows": len(rows),
                "music_windows": music_hits,
                "music_score_max": music_score_max,
                "music_score_median": music_score_median,
            }

        # Emit only stable, sufficiently strong non-generic tags; YAMNet scores
        # for weak style guesses are intentionally left out.
        counts: dict[str, int] = {}
        maxima: dict[str, float] = {}
        for row in rows:
            for index in np.argsort(row)[::-1][:12]:
                label = self.labels[int(index)]
                score = float(row[int(index)])
                if label in _IGNORED_TAGS or score < self.tag_threshold:
                    continue
                counts[label] = counts.get(label, 0) + 1
                maxima[label] = max(maxima.get(label, 0.0), score)
        stable_candidates = [
            label for label in sorted(counts, key=lambda item: (-counts[item], -maxima[item], item))
            if counts[label] >= required_hits
        ]
        specific_candidates = [
            label for label in stable_candidates
            if "instrument" not in label.casefold()
        ]
        if specific_candidates:
            stable_candidates = specific_candidates
        # A single strongest recurrent label is more trustworthy than several
        # mutually competing YAMNet instrument guesses on one mixed clip.
        stable_tags = stable_candidates[:1]
        return {
            **base,
            "kind": "music",
            "description": f"Music detected in {music_hits} of {len(rows)} recent audio windows.",
            "tags": stable_tags,
            "confidence": round(float(np.median(music_scores)), 3),  # raw model score; not calibrated
            "windows": len(rows),
            "music_windows": music_hits,
            "music_score_max": music_score_max,
            "music_score_median": music_score_median,
        }


__all__ = ["DEFAULT_YAMNET_DIR", "YamnetSoundscapeDetector"]
