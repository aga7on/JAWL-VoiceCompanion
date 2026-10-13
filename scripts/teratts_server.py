"""Small local REST wrapper for the optional TeraTTSv2 release."""

from __future__ import annotations

import argparse
import io
import ipaddress
import json
import re
import sys
import threading
import time
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.onnx_cancellation import (  # noqa: E402
    InferenceCancellation, InferenceCancelled, inference_scope, wrap_loaded_tts,
)
from jawl_voicecompanion.speech_requests import SpeechRequests, validate_speech_request_id  # noqa: E402


MAX_BODY = 64 * 1024
MAX_TEXT = 4_000
_LANGUAGE_TAG = re.compile(r"^\s*<(?:ru|en)>.*</(?:ru|en)>\s*$", re.IGNORECASE | re.DOTALL)
_VOICE = re.compile(r"^(?:ru|en)_[a-z0-9_]{1,60}$", re.IGNORECASE)


class TeraBusy(RuntimeError):
    """The bounded worker queue/registry cannot admit this request."""


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
        sys.dont_write_bytecode = True  # external release is a read-only input
        sys.path.insert(0, str(release))
        from teratts import SAMPLE_RATE, generate_speech, load_model
        from onnxruntime import RunOptions

        if not _VOICE.fullmatch(voice):
            raise ValueError("voice must be a bounded Tera style name")
        self.sample_rate = int(SAMPLE_RATE)
        self.default_voice = voice
        self._generate = generate_speech
        self._loaded = wrap_loaded_tts(load_model(
            release, model=model, threads=max(1, min(int(threads), 64)),
            provider="CPUExecutionProvider", russian_stress=True,
        ), RunOptions)
        self._init_lifecycle()

    def _init_lifecycle(self, *, max_pending: int = 8, queue_timeout: float = 10.0,
                        request_timeout: float = 120.0) -> None:
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_pending)
        # Admission and shutdown share one lock so close cannot miss a token
        # between request registration and bounded queue reservation.
        self._lifecycle_lock = threading.Lock()
        self._pending = 0
        self._running_id: str | None = None
        self._closing = False
        self._tokens: dict[int, InferenceCancellation] = {}
        self._queue_timeout = queue_timeout
        self._request_timeout = request_timeout
        self._requests = SpeechRequests(event_factory=InferenceCancellation)

    def close(self) -> None:
        """Reject new work and signal only tokens admitted by this runtime.

        Cancellation is cooperative at the scoped ONNX boundary. This does not
        forcibly stop native work that cannot observe its RunOptions.
        """
        with self._lifecycle_lock:
            if self._closing:
                return
            self._closing = True
            for token in self._tokens.values():
                token.set()

    def cancel_requests(self, request_ids: Any) -> None:
        if not isinstance(request_ids, list) or not 1 <= len(request_ids) <= 8:
            raise ValueError("request_ids must be an array of 1-8 request IDs")
        keys = [validate_speech_request_id(value) for value in request_ids]
        with self._lifecycle_lock:
            if self._closing:
                raise TeraBusy("Tera runtime is closing")
            for key in keys:
                try:
                    self._requests.cancel(key)
                except RuntimeError as exc:
                    raise TeraBusy(str(exc)) from exc

    def state(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            return {"pending": self._pending, "running": self._running_id is not None,
                    "closing": self._closing,
                    "cancel_capability": "scoped_onnx_run_options",
                    "queue_timeout_seconds": self._queue_timeout,
                    "request_timeout_seconds": self._request_timeout}

    def synthesize(self, text: str, voice: str | None, speed: Any, seed: Any = 42,
                   pitch: float = 0.0, f0_range: float = 1.0, energy: float = 1.0,
                   *, request_id: str | None = None) -> bytes:
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
        job_id = validate_speech_request_id(request_id) if request_id is not None else uuid4().hex
        with self._lifecycle_lock:
            if self._closing:
                raise TeraBusy("Tera runtime is closing")
            try:
                token = self._requests.begin(job_id)
            except RuntimeError as exc:
                raise TeraBusy(str(exc)) from exc
            token.check()
            if not self._slots.acquire(blocking=False):
                self._requests.finish(token)
                raise TeraBusy("speech queue is full")
            self._tokens[id(token)] = token
            self._pending += 1
        locked = False
        deadline = time.monotonic() + self._queue_timeout
        timeout = threading.Timer(self._request_timeout, token.set)
        timeout.daemon = True
        try:
            timeout.start()
            while not self._lock.acquire(timeout=0.05):
                token.check()
                if time.monotonic() >= deadline:
                    raise TeraBusy("speech queue wait timed out")
            locked = True
            token.check()
            if time.monotonic() >= deadline:
                raise TeraBusy("speech queue wait timed out")
            with self._lifecycle_lock:
                if self._closing:
                    token.set()
                token.check()
                self._running_id = job_id
            with inference_scope(token):
                samples = self._generate(
                    self._loaded, tagged, selected_voice,
                    duration_scale=1.0 / speed, seed=seed,
                )
            token.check()
            return self._encode(samples, text, speed, pitch, f0_range, energy, token)
        finally:
            timeout.cancel()
            if locked:
                with self._lifecycle_lock:
                    self._running_id = None
                self._lock.release()
            with self._lifecycle_lock:
                self._tokens.pop(id(token), None)
                self._pending -= 1
                self._slots.release()
            self._requests.finish(token)

    def _encode(self, samples: Any, text: str, speed: float, pitch: float,
                f0_range: float, energy: float, token: InferenceCancellation) -> bytes:
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
        token.check()
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
        token.check()
        return data


class Handler(BaseHTTPRequestHandler):
    runtime: TeraRuntime

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json({"status": "ok", "model": "TeraTTSv2", "sample_rate": self.runtime.sample_rate,
                    **self.runtime.state()})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path not in {"/tts", "/cancel"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("Origin"):
            self._json({"error": "worker accepts non-browser loopback clients only"}, HTTPStatus.FORBIDDEN)
            return
        try:
            self.connection.settimeout(3.0)
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > MAX_BODY:
                raise ValueError("request body is too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            if self.path == "/cancel":
                self.runtime.cancel_requests(payload.get("request_ids"))
                self._json({"ok": True, "status": "cancelled"})
                return
            request_kwargs = ({"request_id": validate_speech_request_id(payload["request_id"])}
                              if "request_id" in payload else {})
            audio = self.runtime.synthesize(
                payload.get("text"), payload.get("voice"), payload.get("speed", 1.0),
                payload.get("seed", 42),
                _bounded_pitch(payload.get("pitch")), _bounded_range(payload.get("f0_range")),
                _bounded_energy(payload.get("energy")),
                **request_kwargs,
            )
        except InferenceCancelled:
            self._json({"error": "speech inference cancelled"}, HTTPStatus.CONFLICT)
            return
        except TeraBusy as exc:
            self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
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
    try:
        local_host = args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        local_host = False
    if not local_host:
        parser.error("Tera worker must bind loopback; use the authenticated Companion gateway for LAN")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    runtime = TeraRuntime(args.release_dir, args.voice, args.model, args.threads)
    Handler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    # Handler work is cooperatively cancelled by runtime.close(). Native work
    # beyond a cancellation checkpoint may continue, so server_close must not
    # wait indefinitely for handler threads.
    server.daemon_threads = True
    server.block_on_close = False
    print(f"TeraTTSv2 listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        server.server_close()


if __name__ == "__main__":
    main()
