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

import numpy as np


MAX_BODY = 64 * 1024
MAX_TEXT = 4_000
_LANGUAGE_TAG = re.compile(r"^\s*<(?:ru|en)>.*</(?:ru|en)>\s*$", re.IGNORECASE | re.DOTALL)
_VOICE = re.compile(r"^(?:ru|en)_[a-z0-9_]{1,60}$", re.IGNORECASE)


def _bounded_pitch(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("pitch must be numeric")
    pitch = float(value if value is not None else 0.0)
    if not -6.0 <= pitch <= 6.0:
        raise ValueError("pitch must be within [-6, 6] semitones")
    return pitch


def _bounded_range(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("f0_range must be numeric")
    f0_range = float(value if value is not None else 1.0)
    if not 0.4 <= f0_range <= 2.2:
        raise ValueError("f0_range must be within [0.4, 2.2]")
    return f0_range


def _bounded_energy(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("energy must be numeric")
    energy = float(value if value is not None else 1.0)
    if not 0.5 <= energy <= 1.5:
        raise ValueError("energy must be within [0.5, 1.5]")
    return energy


def _insert_pauses(samples: np.ndarray, sample_rate: int, text: str) -> np.ndarray:
    """Punctuation-aware silence insertion: ~320 ms on .!? and ~180 ms on ,:;."""
    pieces: list[np.ndarray] = []
    per_char = len(samples) / max(1, len(text))
    buf_start = 0
    for i, ch in enumerate(text):
        if ch in ".!?":
            pieces.append(samples[buf_start:int(i * per_char)])
            pieces.append(np.zeros(int(sample_rate * 0.32), dtype=np.float32))
            buf_start = int(i * per_char)
        elif ch in ",:;":
            pieces.append(samples[buf_start:int(i * per_char)])
            pieces.append(np.zeros(int(sample_rate * 0.18), dtype=np.float32))
            buf_start = int(i * per_char)
    pieces.append(samples[buf_start:])
    return np.concatenate(pieces)


def _prosody(samples: np.ndarray, sample_rate: int, speed: float,
             pitch: float, f0_range: float, energy: float, text: str) -> np.ndarray:
    """WORLD-based prosody layer: F0 rescale + dynamic-range shaping + energy
    gain + punctuation pauses. Formant-preserving (no phase-vocoder metal).
    Neutral parameters stay passthrough (speed is model-native duration)."""
    values = samples.astype(np.float32)
    needs_world = abs(pitch) >= 0.05 or abs(f0_range - 1.0) >= 0.05
    if needs_world:
        import pyworld as pw
        x = values.astype(np.float64)
        f0, t = pw.harvest(x, sample_rate, frame_period=5.0)
        f0 = pw.stonemask(x, f0, t, sample_rate)
        sp = pw.cheaptrick(x, f0, t, sample_rate)
        ap = pw.d4c(x, f0, t, sample_rate)
        voiced = f0 > 0
        if voiced.any():
            median = float(np.median(f0[voiced]))
            f0_v = median + (f0[voiced] - median) * f0_range
            f0_v = f0_v * (2.0 ** (pitch / 12.0))
            f0[voiced] = np.clip(f0_v, 40.0, 700.0)
        sp = sp * (energy ** 2)
        values = pw.synthesize(f0, sp, ap, sample_rate).astype(np.float32)
    elif abs(energy - 1.0) >= 0.01:
        values = values * energy
    return _insert_pauses(values, sample_rate, text)


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

    def synthesize(self, text: str, voice: str | None, speed: Any, seed: Any = 42,
                   pitch: float = 0.0, f0_range: float = 1.0, energy: float = 1.0) -> bytes:
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
        if isinstance(seed, bool):
            raise ValueError("seed must be an integer")
        try:
            seed = int(seed)
        except (TypeError, ValueError) as exc:
            raise ValueError("seed must be an integer") from exc
        if not -(2**31) <= seed <= 2**31 - 1:
            raise ValueError("seed is out of range")
        tagged = text if _LANGUAGE_TAG.fullmatch(text) else f"<ru>{text}</ru>"
        with self._lock:
            samples = self._generate(
                self._loaded, tagged, selected_voice,
                duration_scale=1.0 / speed, seed=seed,
            )
        samples = np.asarray(samples, dtype=np.float32)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak <= 1e-6:
            raise ValueError("TTS produced a silent waveform")
        # Some Tera releases return a valid waveform at a very small gain.
        # Normalize only that pathological range so browser gate/VAD can see
        # speech; leave normally scaled model output untouched.
        if peak < 0.1:
            samples = samples * (0.85 / peak)
        samples = _prosody(samples, self.sample_rate, speed, float(pitch), float(f0_range), float(energy), text)
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
            audio = self.runtime.synthesize(
                payload.get("text"), payload.get("voice"), payload.get("speed", 1.0),
                payload.get("seed", 42),
                _bounded_pitch(payload.get("pitch")), _bounded_range(payload.get("f0_range")),
                _bounded_energy(payload.get("energy")),
            )
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
