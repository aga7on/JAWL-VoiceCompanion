"""Local Russian-aware ASR via faster-whisper, OpenAI-compatible contract."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import threading
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np

os.environ.setdefault(
    "HF_HOME", r"G:\AI\JAWL-VoiceCompanion\runtime\models\hf",
)

MAX_BODY = 64 * 1024 * 1024
_TARGET_RATE = 16_000
_BOUNDARY_RE = re.compile(r"boundary=(?:\"([^\"]+)\"|([^;]+))", re.IGNORECASE)


class WhisperRuntime:
    """faster-whisper runtime loaded once, transcription serialized."""

    def __init__(
        self,
        model: str,
        *,
        language: str = "ru",
        initial_prompt: str = "Это русская речь.",
        threads: int = 12,
        beam_size: int = 5,
    ) -> None:
        from faster_whisper import WhisperModel

        self.language = str(language or "").strip() or None
        self.initial_prompt = initial_prompt
        self.beam_size = int(beam_size)
        self._lock = threading.Lock()
        self._model_name = model
        self._whisper = WhisperModel(
            model,
            device="cpu",
            compute_type="int8",
            cpu_threads=max(1, min(int(threads), 64)),
            num_workers=1,
        )

    def transcribe(self, wav_bytes: bytes) -> str:
        pcm, rate = _decode_wav(wav_bytes)
        if pcm.size == 0:
            raise ValueError("WAV contains no audio frames")
        if rate != _TARGET_RATE:
            pcm = _resample(pcm, rate, _TARGET_RATE)
        with self._lock:
            segments, _info = self._whisper.transcribe(
                pcm,
                language=self.language,
                initial_prompt=self.initial_prompt,
                beam_size=self.beam_size,
                temperature=0.0,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            parts = [segment.text for segment in segments]
        return "".join(parts).strip()


def _decode_wav(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with io.BytesIO(wav_bytes) as stream:
        with wave.open(stream, "rb") as audio:
            sample_rate = audio.getframerate()
            channels = audio.getnchannels()
            width = audio.getsampwidth()
            frames = audio.readframes(audio.getnframes())
    if width not in (1, 2, 4):
        raise ValueError("unsupported WAV sample width")
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[width]
    pcm = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if width == 1:
        pcm = (pcm - 128.0) / 128.0
    else:
        pcm /= float(1 << (8 * width - 1))
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, int(sample_rate)


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples
    count = int(round(len(samples) * target_rate / source_rate))
    if count < 2:
        return samples
    x_old = np.linspace(0.0, 1.0, len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, count, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32, copy=False)


def _parse_multipart(content_type: str, body: bytes) -> dict[str, bytes]:
    match = _BOUNDARY_RE.search(content_type or "")
    if not match:
        raise ValueError("multipart boundary was not found")
    boundary = (match.group(1) or match.group(2)).encode("utf-8")
    delimiter = b"--" + boundary
    fields: dict[str, bytes] = {}
    for raw_part in body.split(delimiter):
        if not raw_part or raw_part in (b"--", b"--\r\n") or raw_part[:2] == b"--":
            continue
        header_end = raw_part.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        headers = raw_part[:header_end].decode("utf-8", errors="replace")
        content = raw_part[header_end + 4:]
        if content.endswith(b"\r\n"):
            content = content[:-2]
        name_match = re.search(r'name="([^"]+)"', headers)
        if not name_match:
            continue
        fields[name_match.group(1)] = content
    return fields


class Handler(BaseHTTPRequestHandler):
    runtime: WhisperRuntime

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json({
            "status": "ok",
            "model": self.runtime._model_name,
            "language": self.runtime.language or "auto",
        })

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path not in ("/v1/audio/transcriptions", "/audio/transcriptions"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > MAX_BODY:
                raise ValueError("request body is too large")
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            fields = _parse_multipart(content_type, body)
            wav_bytes = fields.get("file") or fields.get("audio")
            if not wav_bytes:
                raise ValueError("no audio file field in multipart body")
            text = self.runtime.transcribe(wav_bytes)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)[:200]}, HTTPStatus.BAD_REQUEST)
            return
        except Exception:
            self._json({"error": "ASR transcription failed"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self._json({"text": text})

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="faster-whisper local /health + /v1/audio/transcriptions server")
    parser.add_argument("--model", default="mobiuslabsgmbh/faster-whisper-large-v3-turbo")
    parser.add_argument("--language", default="ru", help="whisper language code; 'auto' disables the hint")
    parser.add_argument("--initial-prompt", default="Это русская речь.")
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8984)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    language = None if str(args.language).strip().lower() in ("auto", "") else str(args.language).strip()
    runtime = WhisperRuntime(
        args.model,
        language=language,
        initial_prompt=args.initial_prompt,
        threads=args.threads,
        beam_size=args.beam_size,
    )
    Handler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"faster-whisper ASR listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()