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
import threading
import tempfile
import time
import shutil
from contextlib import contextmanager
from pathlib import Path
from .owned_pipe import spawn_owned_worker

_MAX_TEXT_CHARS = 12_000
_MAX_TRANSCRIPT_JSON_BYTES = 256 * 1024
_MAX_TRANSCRIPT_SEGMENTS = 4_096
_PROCESS_STOP_GRACE_SECONDS = 1.0
_PROCESS_POLL_SECONDS = 0.05


@contextmanager
def _workspace():
    # Never remove a WAV that an unreaped process may still be using. On a
    # teardown fault retain only this task-owned temp directory for diagnosis.
    root = Path(tempfile.mkdtemp(prefix='gigaam-'))
    cleanup = {'safe': True}
    try:
        yield root, cleanup
    finally:
        if cleanup['safe']:
            shutil.rmtree(root)


class GigaAMBatchError(RuntimeError):
    """Raised when the batch GigaAM transcription fails."""


class GigaAMBatchCancelled(GigaAMBatchError):
    """Raised when this transcription call is cooperatively cancelled."""


def _stop_and_reap(process: subprocess.Popen[bytes]) -> None:
    """Stop and reap only the child created for this transcription call."""
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=_PROCESS_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=_PROCESS_STOP_GRACE_SECONDS)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GigaAMBatchError("crispasr child cleanup failed") from exc
    else:
        process.wait(timeout=_PROCESS_STOP_GRACE_SECONDS)


class CrispASRFileTranscriber:
    """Transcribe one complete WAV utterance with crispasr in file mode."""

    def __init__(self, executable: str, model: str, *, timeout_seconds: float = 20.0) -> None:
        self.executable = str(executable)
        self.model = str(model)
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 120.0))

    def prefetch(self, chunk_bytes: int = 4 * 1024 * 1024) -> int:
        """Read the model file once so the next crispasr spawn starts warm.

        The batch transcriber spawns a fresh process per final phrase; the
        first spawn after idle can spend seconds reloading the model from
        disk. Reading it while the user is still speaking keeps the final in
        the fast regime. Best-effort: returns bytes read, never raises for
        an unreadable model.
        """
        chunk = max(64 * 1024, int(chunk_bytes))
        total = 0
        try:
            with open(self.model, "rb") as stream:
                while True:
                    block = stream.read(chunk)
                    if not block:
                        break
                    total += len(block)
        except OSError:
            return total
        return total

    def transcribe(
        self,
        wav_bytes: bytes,
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise GigaAMBatchCancelled("crispasr batch run cancelled")
        if not wav_bytes:
            raise GigaAMBatchError("empty utterance")
        with _workspace() as (tmp, cleanup):
            wav_path = Path(tmp) / "utterance.wav"
            wav_path.write_bytes(wav_bytes)
            out_base = Path(tmp) / "out"
            command = [
                self.executable, "-m", self.model,
                "-oj", "-of", str(out_base), str(wav_path),
            ]
            process: subprocess.Popen[bytes] | None = None
            try:
                if cancel_event is not None and cancel_event.is_set():
                    raise GigaAMBatchCancelled("crispasr batch run cancelled")
                process = spawn_owned_worker(command)
                cleanup['safe'] = False
                deadline = time.monotonic() + self.timeout_seconds
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise GigaAMBatchCancelled("crispasr batch run cancelled")
                    return_code = process.poll()
                    if return_code is not None:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GigaAMBatchError("crispasr batch run timed out")
                    time.sleep(min(_PROCESS_POLL_SECONDS, remaining))
            except (OSError, subprocess.SubprocessError) as exc:
                raise GigaAMBatchError("crispasr batch run failed") from exc
            finally:
                if process is not None:
                    try:
                        _stop_and_reap(process)
                    except (OSError, subprocess.SubprocessError) as exc:
                        raise GigaAMBatchError('crispasr child cleanup failed; temporary audio retained') from exc
                    cleanup['safe'] = True
            if return_code != 0:
                raise GigaAMBatchError("crispasr batch run failed")
            if cancel_event is not None and cancel_event.is_set():
                raise GigaAMBatchCancelled("crispasr batch run cancelled")
            json_path = Path(str(out_base) + ".json")
            try:
                with json_path.open("rb") as stream:
                    transcript_json = stream.read(_MAX_TRANSCRIPT_JSON_BYTES + 1)
                if len(transcript_json) > _MAX_TRANSCRIPT_JSON_BYTES:
                    raise GigaAMBatchError("crispasr transcript json is too large")
                payload = json.loads(transcript_json.decode("utf-8"))
            except GigaAMBatchError:
                raise
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                raise GigaAMBatchError("crispasr produced no transcript json") from exc
        if not isinstance(payload, dict):
            raise GigaAMBatchError("crispasr transcript shape is invalid")
        segments = payload.get("transcription")
        if not isinstance(segments, list) or len(segments) > _MAX_TRANSCRIPT_SEGMENTS:
            raise GigaAMBatchError("crispasr transcript shape is invalid")
        parts: list[str] = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise GigaAMBatchError("crispasr transcript shape is invalid")
            part = segment.get("text", "")
            if not isinstance(part, str):
                raise GigaAMBatchError("crispasr transcript shape is invalid")
            parts.append(part.strip())
        text = " ".join(part for part in parts if part).strip()
        if not text:
            raise GigaAMBatchError("crispasr transcript is empty")
        if cancel_event is not None and cancel_event.is_set():
            raise GigaAMBatchCancelled("crispasr batch run cancelled")
        return text[:_MAX_TEXT_CHARS]


__all__ = ["CrispASRFileTranscriber", "GigaAMBatchError", "GigaAMBatchCancelled"]
