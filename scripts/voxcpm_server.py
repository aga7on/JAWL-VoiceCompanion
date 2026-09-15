"""Loopback REST worker for the externally installed VoxCPM2 runtime.

Run this file with ``G:\\AI\\VoxCPM\\.venv\\Scripts\\python.exe``.  The
Companion process stays model-agnostic and talks to this worker through the
same complete-WAV contract as Tera/Qwen, while ``/tts/stream`` exposes
VoxCPM2's native generator for first-audio latency and barge-in cancellation.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import threading
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import numpy as np


MAX_BODY = 64 * 1024
MAX_TEXT = 4_000
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _loopback_host(host: str) -> str:
    if str(host).strip() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("VoxCPM worker must bind to loopback")
    return str(host).strip()


def _bounded_speed(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("speed must be numeric")
    speed = float(value if value is not None else 1.0)
    if not 0.5 <= speed <= 2.0:
        raise ValueError("speed must be between 0.5 and 2.0")
    return speed


def _bounded_seed(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("seed must be an integer")
    seed = int(value if value is not None else 42)
    if not -(2**31) <= seed <= 2**31 - 1:
        raise ValueError("seed is out of range")
    return seed


def _bounded_pitch(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("pitch must be numeric")
    pitch = float(value if value is not None else 0.0)
    if not -6.0 <= pitch <= 6.0:
        raise ValueError("pitch must be within [-6, 6] semitones")
    return pitch


def _bounded_energy(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("energy must be numeric")
    energy = float(value if value is not None else 1.0)
    if not 0.5 <= energy <= 1.5:
        raise ValueError("energy must be within [0.5, 1.5]")
    return energy


def _prosody(samples: np.ndarray, sample_rate: int, speed: float,
             pitch: float, energy: float) -> np.ndarray:
    """DSP prosody layer: cheap post-TTS emotion shaping.

    Order: speed resample, pitch shift (semitones), energy gain. Each step is
    skipped when neutral so the default contract stays byte-compatible.
    """
    values = _resample_speed(samples, speed)
    if abs(pitch) >= 0.05:
        import librosa
        values = librosa.effects.pitch_shift(values.astype(np.float32), sr=sample_rate, n_steps=float(pitch))
    if abs(energy - 1.0) >= 0.01:
        values = values * energy
    return values


def _resample_speed(samples: np.ndarray, speed: float) -> np.ndarray:
    if samples.size == 0 or abs(speed - 1.0) < 0.001:
        return samples
    target = max(1, int(round(samples.size / speed)))
    positions = np.linspace(0, samples.size - 1, target)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)


def _wav_bytes(samples: Any, sample_rate: int, speed: float) -> bytes:
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("VoxCPM returned invalid audio")
    values = _resample_speed(values, speed)
    values = np.clip(values, -1.0, 1.0)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes((values * 32767.0).round().astype("<i2").tobytes())
    data = output.getvalue()
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("generated audio exceeds 8 MiB")
    return data


class VoxCPMRuntime:
    def __init__(
        self,
        model_dir: Path,
        *,
        device: str,
        reference_wav: Path | None,
        inference_timesteps: int,
        threads: int,
    ) -> None:
        model_dir = model_dir.resolve()
        if not model_dir.is_dir() or not (model_dir / "config.json").is_file():
            raise ValueError(f"VoxCPM model directory was not found: {model_dir}")
        if reference_wav is not None:
            reference_wav = reference_wav.resolve()
            if not reference_wav.is_file():
                raise ValueError(f"VoxCPM reference audio was not found: {reference_wav}")
        if not 1 <= int(inference_timesteps) <= 50:
            raise ValueError("inference timesteps must be between 1 and 50")
        if not 1 <= int(threads) <= 64:
            raise ValueError("threads must be between 1 and 64")

        import torch
        from voxcpm import VoxCPM

        torch.set_num_threads(int(threads))
        self.model = VoxCPM.from_pretrained(
            str(model_dir),
            load_denoiser=False,
            optimize=False,
            device=str(device),
        )
        self.sample_rate = int(self.model.tts_model.sample_rate)
        self.model_dir = str(model_dir)
        self.device = str(device)
        self.reference_wav = str(reference_wav) if reference_wav else None
        self.inference_timesteps = int(inference_timesteps)
        self.default_voice = "voxcpm-reference" if self.reference_wav else "voxcpm-zero-shot"
        self._lock = threading.Lock()
        self._active_cancel_lock = threading.Lock()
        self._active_cancel: threading.Event | None = None

    def _validate(self, text: Any, voice: Any, speed: Any, seed: Any) -> tuple[str, float, int]:
        value = str(text or "").strip()
        if not value or len(value) > MAX_TEXT:
            raise ValueError("text must be non-empty and at most 4000 characters")
        selected_voice = str(voice or self.default_voice).strip()
        if selected_voice != self.default_voice:
            raise ValueError("only the configured VoxCPM reference voice is available")
        return value, _bounded_speed(speed), _bounded_seed(seed)

    def _prosody_params(self, payload: dict[str, Any]) -> tuple[float, float]:
        return _bounded_pitch(payload.get("pitch")), _bounded_energy(payload.get("energy"))

    def synthesize(self, text: Any, voice: Any, speed: Any, seed: Any = 42,
                   pitch: float = 0.0, energy: float = 1.0) -> bytes:
        value, rate, seed_value = self._validate(text, voice, speed, seed)
        with self._lock:
            samples = self.model.generate(
                text=value,
                reference_wav_path=self.reference_wav,
                inference_timesteps=self.inference_timesteps,
                seed=seed_value,
            )
        samples = _prosody(samples, self.sample_rate, rate, float(pitch), float(energy))
        return _wav_bytes(samples, self.sample_rate, 1.0)

    def stream(self, text: Any, voice: Any, speed: Any, seed: Any = 42,
               pitch: float = 0.0, energy: float = 1.0) -> Iterator[bytes]:
        value, rate, seed_value = self._validate(text, voice, speed, seed)
        cancel = threading.Event()
        with self._active_cancel_lock:
            self._active_cancel = cancel
        try:
            with self._lock:
                generator = self.model.generate_streaming(
                    text=value,
                    reference_wav_path=self.reference_wav,
                    inference_timesteps=self.inference_timesteps,
                    seed=seed_value,
                )
                try:
                    for samples in generator:
                        if cancel.is_set():
                            break
                        shaped = _prosody(samples, self.sample_rate, rate, float(pitch), float(energy))
                        yield _wav_bytes(shaped, self.sample_rate, 1.0)
                finally:
                    generator.close()
        finally:
            with self._active_cancel_lock:
                if self._active_cancel is cancel:
                    self._active_cancel = None

    def cancel(self) -> None:
        with self._active_cancel_lock:
            if self._active_cancel is not None:
                self._active_cancel.set()


class Handler(BaseHTTPRequestHandler):
    runtime: VoxCPMRuntime

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json({
            "status": "ok",
            "model": "VoxCPM2",
            "sample_rate": self.runtime.sample_rate,
            "voice_clone": bool(self.runtime.reference_wav),
            "capabilities": {
                "native_streaming": True,
                "barge_in_disconnect": True,
                "voice_clone": bool(self.runtime.reference_wav),
                "emotion_control": False,
                "speed_control": "postprocess",
            },
            "device": self.runtime.device,
        })

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/cancel":
            self.runtime.cancel()
            self._json({"ok": True, "status": "cancelled"})
            return
        if self.path not in {"/tts", "/tts/stream"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._payload()
            if self.path == "/tts":
                audio = self.runtime.synthesize(
                    payload.get("text"), payload.get("voice"), payload.get("speed", 1.0), payload.get("seed", 42),
                    *self.runtime._prosody_params(payload),
                )
                self._audio(audio)
                return
            self._stream(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._json({"error": str(exc)[:300]}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._json({"error": "VoxCPM synthesis failed"}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "-1"))
        if length < 0 or length > MAX_BODY:
            raise ValueError("request body is too large")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return payload

    def _stream(self, payload: dict[str, Any]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        pitch, energy = self.runtime._prosody_params(payload)
        chunks = self.runtime.stream(
            payload.get("text"), payload.get("voice"), payload.get("speed", 1.0), payload.get("seed", 42),
            pitch=pitch, energy=energy,
        )
        try:
            count = 0
            for index, audio in enumerate(chunks):
                self._event({
                    "type": "audio",
                    "index": index,
                    "media_type": "audio/wav",
                    "data_base64": base64.b64encode(audio).decode("ascii"),
                })
                count += 1
            self._event({"type": "done", "count": count})
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            # Closing the Companion/browser response is the barge-in signal.
            return
        finally:
            chunks.close()

    def _event(self, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="VoxCPM2 local /health + /tts + native /tts/stream server")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(r"G:\AI\VoxCPM\models\models--openbmb--VoxCPM2\snapshots\32279effe8c19989596f05d353d1447f51d9e915"),
    )
    parser.add_argument(
        "--reference-wav",
        type=Path,
        default=None,
        help="Optional reference clip for voice cloning; omitted for lowest streaming latency.",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--inference-timesteps", type=int, default=10)
    parser.add_argument("--threads", type=int, default=24)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9891)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        host = _loopback_host(args.host)
        runtime = VoxCPMRuntime(
            args.model_dir,
            device=args.device,
            reference_wav=args.reference_wav,
            inference_timesteps=args.inference_timesteps,
            threads=args.threads,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    Handler.runtime = runtime
    server = ThreadingHTTPServer((host, args.port), Handler)
    print(f"VoxCPM2 listening on http://{host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
