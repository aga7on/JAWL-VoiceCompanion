"""Small loopback REST worker for the local Qwen3-TTS Base voice clone."""

from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_BODY = 64 * 1024
MAX_TEXT = 4_000
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _loopback_host(host: str) -> str:
    if str(host).strip() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Qwen TTS worker must bind to loopback")
    return str(host).strip()


class QwenRuntime:
    def __init__(
        self,
        model_dir: Path,
        ref_audio: Path,
        ref_text: str,
        *,
        voice: str,
        x_vector_only: bool,
        threads: int,
    ) -> None:
        model_dir = model_dir.resolve()
        ref_audio = ref_audio.resolve()
        if not model_dir.is_dir() or not (model_dir / "config.json").is_file():
            raise ValueError(f"Qwen3-TTS model directory was not found: {model_dir}")
        if not ref_audio.is_file():
            raise ValueError(f"Qwen3-TTS reference audio was not found: {ref_audio}")
        if not x_vector_only and not str(ref_text).strip():
            raise ValueError("Qwen3-TTS ICL voice clone requires reference text")
        if not str(voice).strip() or len(str(voice)) > 80:
            raise ValueError("voice must be a bounded non-empty label")

        import numpy as np
        import torch
        from qwen_tts import Qwen3TTSModel

        torch.set_num_threads(max(1, min(int(threads), 64)))
        self.model = Qwen3TTSModel.from_pretrained(
            str(model_dir), device_map="cpu", dtype=torch.float32,
        )
        self._numpy = np
        self.sample_rate = 24000
        self.default_voice = str(voice).strip()[:80]
        self.ref_audio = str(ref_audio)
        self.ref_text = str(ref_text).strip()[:1200]
        self.x_vector_only = bool(x_vector_only)
        self._lock = threading.Lock()

    def synthesize(self, text: str, voice: str | None, speed: Any) -> bytes:
        text = str(text or "").strip()
        if not text or len(text) > MAX_TEXT:
            raise ValueError("text must be non-empty and at most 4000 characters")
        selected_voice = str(voice or self.default_voice).strip()
        if selected_voice != self.default_voice:
            raise ValueError("only the configured Qwen reference voice is available")
        if isinstance(speed, bool):
            raise ValueError("speed must be numeric")
        speed = float(speed if speed is not None else 1.0)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("speed must be between 0.5 and 2.0")
        kwargs: dict[str, Any] = {
            "text": text,
            "language": "Russian",
            "ref_audio": self.ref_audio,
            "non_streaming_mode": True,
        }
        if self.x_vector_only:
            kwargs["x_vector_only_mode"] = True
        else:
            kwargs["ref_text"] = self.ref_text
        with self._lock:
            wavs, sample_rate = self.model.generate_voice_clone(**kwargs)
        if not wavs:
            raise ValueError("Qwen3-TTS returned no audio")
        samples = self._numpy.asarray(wavs[0], dtype=self._numpy.float32).reshape(-1)
        if samples.size == 0 or not self._numpy.isfinite(samples).all():
            raise ValueError("Qwen3-TTS returned invalid audio")
        samples = self._numpy.clip(samples, -1.0, 1.0)
        if abs(speed - 1.0) > 0.001:
            target = max(1, int(round(samples.size / speed)))
            positions = self._numpy.linspace(0, samples.size - 1, target)
            samples = self._numpy.interp(positions, self._numpy.arange(samples.size), samples).astype(self._numpy.float32)
        pcm = (samples * 32767.0).round().astype("<i2").tobytes()
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate or self.sample_rate))
            wav.writeframes(pcm)
        data = output.getvalue()
        if len(data) > MAX_AUDIO_BYTES:
            raise ValueError("generated audio exceeds 8 MiB")
        return data


class Handler(BaseHTTPRequestHandler):
    runtime: QwenRuntime

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json({
            "status": "ok",
            "model": "Qwen3-TTS-12Hz-0.6B-Base",
            "sample_rate": self.runtime.sample_rate,
            "voice_clone": True,
            "emotion_control": False,
        })

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/tts":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > MAX_BODY:
                raise ValueError("request body is too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            audio = self.runtime.synthesize(payload.get("text"), payload.get("voice"), payload.get("speed", 1.0))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._json({"error": str(exc)[:200]}, HTTPStatus.BAD_REQUEST)
            return
        except Exception:
            self._json({"error": "Qwen3-TTS synthesis failed"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)

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
    parser = argparse.ArgumentParser(description="Qwen3-TTS Base local /health + /tts server")
    parser.add_argument("--model-dir", type=Path, default=Path(r"G:\AI\tts_models\Qwen__Qwen3-TTS-12Hz-0.6B-Base"))
    parser.add_argument("--ref-audio", type=Path, default=Path(r"G:\AI\tts_inference\mita_ref_24k.wav"))
    parser.add_argument("--ref-text", type=Path, default=Path(r"G:\AI\tts_inference\mita_ref_text.txt"))
    parser.add_argument("--voice", default="mita")
    parser.add_argument("--x-vector-only", action="store_true")
    parser.add_argument("--threads", type=int, default=24)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9890)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.threads < 1:
        parser.error("threads must be positive")
    try:
        host = _loopback_host(args.host)
        ref_text = args.ref_text.read_text(encoding="utf-8") if not args.x_vector_only else ""
        runtime = QwenRuntime(
            args.model_dir, args.ref_audio, ref_text,
            voice=args.voice, x_vector_only=args.x_vector_only, threads=args.threads,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    Handler.runtime = runtime
    server = ThreadingHTTPServer((host, args.port), Handler)
    print(f"Qwen3-TTS listening on http://{host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
