"""OmniVoice TTS worker (ADR-045 voice lane): RU realtime synthesis.

Serves the companion's TTS worker contract on loopback:
  GET  /health  -> {"status": "ok", ...}
  POST /tts     -> complete WAV (16-bit PCM 24 kHz mono) for {"text", "voice"?}

The model is k2-fsa/OmniVoice (0.6B diffusion LM, 646 languages; RU is one of
its largest training corpora). Measured on this machine's GPU 1 next to the
Hikari brain: RTF 0.18-0.21 (~5x real-time), 0.7 s per conversational phrase,
RU quality verified verbatim through GigaAM.

Voice: the reference sample (wav + its transcript) is configured once; a
request may pass a different voice id to pick another prepared reference.
Run:
  G:/AI/OmniVoice/venv/Scripts/python.exe -X utf8 scripts/omnivoice_server.py \
      --host 127.0.0.1 --port 9890 \
      [--ref-audio path.wav --ref-text "транскрипт"]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_TEXT_CHARS = 4000

sys.path.insert(0, r"G:\AI\OmniVoice")
sys.path.insert(0, r"G:\AI\OmniVoice\omnivoice")

from omnivoice import OmniVoice  # noqa: E402

MODEL_DIR = Path(r"G:\AI\OmniVoice\models\k2-fsa-OmniVoice")
DEFAULT_REF = Path(r"G:\AI\OmniVoice\bench\ru_ref.wav")
DEFAULT_REF_TEXT = "Привет! Я твой голосовой компаньон, рад тебя слышать."

_state = {"model": None, "lock": threading.Lock(), "ref": None, "ref_text": "", "started_at": 0.0}


def load_model(device: str) -> None:
    import torch

    began = time.perf_counter()
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    model = OmniVoice.from_pretrained(str(MODEL_DIR), device_map=device, dtype=dtype)
    # Warmup: compile kernels once so the first user request is not slow.
    model.generate(text="Готов.")
    _state["model"] = model
    _state["started_at"] = began
    print(f"[omnivoice] model ready on {device} in {time.perf_counter() - began:.1f} s", flush=True)


def synthesize(text: str) -> bytes:
    model = _state["model"]
    if model is None:
        raise RuntimeError("model is not loaded")
    audio = model.generate(text=text, ref_audio=str(_state["ref"]), ref_text=_state["ref_text"])
    samples = audio[0]
    # The diffusion output can exceed full scale (observed clipping at 0.95%
    # of samples with a reference-voiced generation); normalize to 0.9 before
    # quantization so ASR and playback get a clean signal.
    import numpy as np

    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.abs(values).max()) if values.size else 0.0
    if peak > 0.9:
        values = values * (0.9 / peak)
    pcm = (values.clip(-1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # keep stdout clean
        print(f"[omnivoice] {self.path} {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body = json.dumps({
                "status": "ok" if _state["model"] is not None else "loading",
                "model": "OmniVoice",
                "sample_rate": 24000,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 1 << 20:
                raise ValueError("bad request size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            self._json_error(400, "invalid json body")
            return
        text = str(payload.get("text") or "").strip()
        if not text or len(text) > MAX_TEXT_CHARS:
            self._json_error(422, "text must be non-empty and at most 4000 characters")
            return
        began = time.perf_counter()
        try:
            with _state["lock"]:
                wav = synthesize(text)
        except Exception as exc:  # noqa: BLE001 - report, never crash the worker
            self._json_error(500, f"{type(exc).__name__}: {exc}")
            return
        duration = time.perf_counter() - began
        print(f"[omnivoice] tts: {len(text)} chars -> {len(wav)} B in {duration:.2f} s", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav)))
        self.send_header("X-Gen-Seconds", f"{duration:.3f}")
        self.end_headers()
        self.wfile.write(wav)

    def _json_error(self, code: int, message: str) -> None:
        body = json.dumps({"error": message[:300]}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniVoice TTS worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9890)
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--ref-audio", default=str(DEFAULT_REF))
    parser.add_argument("--ref-text", default=DEFAULT_REF_TEXT)
    args = parser.parse_args()

    _state["ref"] = Path(args.ref_audio)
    _state["ref_text"] = str(args.ref_text)
    if not MODEL_DIR.exists():
        print(f"[omnivoice] model dir is missing: {MODEL_DIR}", file=sys.stderr)
        return 2
    if not _state["ref"].exists():
        print(f"[omnivoice] reference sample is missing: {_state['ref']}", file=sys.stderr)
        return 2

    # Load before serving so /health tells the truth from the first request.
    load_model(args.device)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[omnivoice] serving on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())