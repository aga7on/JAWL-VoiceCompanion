"""Small local REST wrapper for the optional TeraTTSv2 release."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import threading
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_BODY = 64 * 1024
MAX_TEXT = 4_000
_LANGUAGE_TAG = re.compile(r"^\s*<(?:ru|en)>.*</(?:ru|en)>\s*$", re.IGNORECASE | re.DOTALL)
_VOICE = re.compile(r"^(?:ru|en)_[a-z0-9_]{1,60}$", re.IGNORECASE)


class TeraRuntime:
    def __init__(self, release: Path, voice: str, model: str, threads: int) -> None:
        release = release.resolve()
        if not release.is_dir():
            raise ValueError("TeraTTS release directory was not found")
        sys.path.insert(0, str(release))
        from teratts import SAMPLE_RATE, generate_speech, load_model

        if not _VOICE.fullmatch(voice):
            raise ValueError("voice must be a bounded Tera style name")
        self.sample_rate = int(SAMPLE_RATE)
        self.default_voice = voice
        self._generate = generate_speech
        self._lock = threading.Lock()
        self._loaded = load_model(
            release, model=model, threads=max(1, min(int(threads), 64)),
            provider="CPUExecutionProvider", russian_stress=True,
        )

    def synthesize(self, text: str, voice: str | None, speed: Any) -> bytes:
        text = str(text or "").strip()
        if not text or len(text) > MAX_TEXT:
            raise ValueError("text must be non-empty and at most 4000 characters")
        selected_voice = str(voice or self.default_voice).strip()
        if not _VOICE.fullmatch(selected_voice):
            raise ValueError("unsupported voice")
        if isinstance(speed, bool):
            raise ValueError("speed must be numeric")
        speed = float(speed if speed is not None else 1.0)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("speed must be between 0.5 and 2.0")
        tagged = text if _LANGUAGE_TAG.fullmatch(text) else f"<ru>{text}</ru>"
        with self._lock:
            samples = self._generate(
                self._loaded, tagged, selected_voice,
                duration_scale=1.0 / speed, seed=42,
            )
        pcm = (samples.clip(-1.0, 1.0) * 32767.0).round().astype("<i2")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm.tobytes())
        data = output.getvalue()
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("generated audio exceeds 8 MiB")
        return data


class Handler(BaseHTTPRequestHandler):
    runtime: TeraRuntime

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json({"status": "ok", "model": "TeraTTSv2", "sample_rate": self.runtime.sample_rate})

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
            self._json({"error": "TTS synthesis failed"}, HTTPStatus.SERVICE_UNAVAILABLE)
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
    parser = argparse.ArgumentParser(description="TeraTTSv2 local /health + /tts server")
    parser.add_argument("--release-dir", type=Path, default=Path(r"G:\AI\tts_models\TeraSpace__TeraTTSv2"))
    parser.add_argument("--voice", default="ru_f1")
    parser.add_argument("--model", choices=("distilled", "teacher"), default="distilled")
    parser.add_argument("--threads", type=int, default=24)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9889)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    runtime = TeraRuntime(args.release_dir, args.voice, args.model, args.threads)
    Handler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"TeraTTSv2 listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
