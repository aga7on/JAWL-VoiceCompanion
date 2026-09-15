"""Batch (file-mode) GigaAM transcription through the crispasr binary.

The streaming bridge keeps only a rolling window of partials, so long
utterances lose their beginning and no stable "final" event is emitted.
The file mode of the same binary transcribes the complete buffered
utterance in ~0.5 s (measured 21x realtime on a 9.6 s clip) and produced
more accurate Russian than the Qwen3-ASR fallback on the same audio
(correct case forms, sentence punctuation, quotes).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

_MAX_TEXT_CHARS = 12_000


class GigaAMBatchError(RuntimeError):
    """Raised when the batch GigaAM transcription fails."""


class CrispASRFileTranscriber:
    """Transcribe one complete WAV utterance with crispasr in file mode."""

    def __init__(self, executable: str, model: str, *, timeout_seconds: float = 20.0) -> None:
        self.executable = str(executable)
        self.model = str(model)
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))

    def transcribe(self, wav_bytes: bytes) -> str:
        if not wav_bytes:
            raise GigaAMBatchError("empty utterance")
        with tempfile.TemporaryDirectory(prefix="gigaam-") as tmp:
            wav_path = Path(tmp) / "utterance.wav"
            wav_path.write_bytes(wav_bytes)
            out_base = Path(tmp) / "out"
            command = [
                self.executable, "-m", self.model,
                "-oj", "-of", str(out_base), str(wav_path),
            ]
            try:
                subprocess.run(
                    command, capture_output=True, timeout=self.timeout_seconds, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GigaAMBatchError(f"crispasr batch run failed: {type(exc).__name__}") from exc
            json_path = Path(str(out_base) + ".json")
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GigaAMBatchError("crispasr produced no transcript json") from exc
        segments = payload.get("transcription")
        if not isinstance(segments, list):
            raise GigaAMBatchError("crispasr transcript shape is invalid")
        parts = [
            str(segment.get("text") or "").strip()
            for segment in segments
            if isinstance(segment, dict)
        ]
        text = " ".join(part for part in parts if part).strip()
        if not text:
            raise GigaAMBatchError("crispasr transcript is empty")
        return text[:_MAX_TEXT_CHARS]


__all__ = ["CrispASRFileTranscriber", "GigaAMBatchError"]
