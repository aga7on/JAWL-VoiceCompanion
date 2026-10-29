"""Small loopback OpenAI-compatible server for the locally tested LFM3-Omni checkpoint.

This adapter intentionally loads the existing Transformers checkpoint and serves
text, one-frame image, or one-audio-clip chat requests. It stores no request
media or generated conversation history.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading
import time
import uuid
import wave

import numpy as np
import torch
from PIL import Image
from scipy.signal import resample_poly
from transformers import AutoModelForImageTextToText, AutoProcessor


MODEL = None
PROCESSOR = None
DEVICE = "cuda:1"
MODEL_ALIAS = "local-lfm3-omni"
MAX_NEW_TOKENS = 512
INFERENCE_LOCK = threading.Lock()


def _decode_data_url(value: str) -> bytes:
    header, sep, data = value.partition(",")
    if not sep or not header.startswith("data:"):
        raise ValueError("only inline data URLs are accepted")
    return base64.b64decode(data, validate=True)


def _audio_array(raw: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(raw), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        if width != 2:
            raise ValueError("audio input must be 16-bit PCM WAV")
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        divisor = np.gcd(rate, 16000)
        samples = resample_poly(samples, 16000 // divisor, rate // divisor).astype(np.float32, copy=False)
    return samples


def _normalize_messages(messages: list[dict], response_format: object):
    conversation: list[dict] = []
    images: list[Image.Image] = []
    audios: list[np.ndarray] = []
    for source in messages:
        role = str(source.get("role") or "user")
        content = source.get("content")
        if isinstance(content, str):
            conversation.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            conversation.append({"role": role, "content": str(content or "")})
            continue
        parts: list[dict] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "text":
                parts.append({"type": "text", "text": str(item.get("text") or "")})
            elif kind == "image_url":
                info = item.get("image_url") or {}
                url = info.get("url") if isinstance(info, dict) else None
                if not isinstance(url, str):
                    raise ValueError("image_url is missing an inline data URL")
                image = Image.open(io.BytesIO(_decode_data_url(url))).convert("RGB")
                images.append(image)
                parts.append({"type": "image", "image": image})
            elif kind in {"input_audio", "audio"}:
                info = item.get("input_audio") if kind == "input_audio" else item
                if isinstance(info, dict) and isinstance(info.get("data"), str):
                    audios.append(_audio_array(base64.b64decode(info["data"], validate=True)))
                elif isinstance(item.get("audio"), str) and item["audio"].startswith("data:"):
                    audios.append(_audio_array(_decode_data_url(item["audio"])))
                else:
                    raise ValueError("audio must be supplied as inline PCM WAV data")
                parts.append({"type": "audio", "audio": "waveform passed separately"})
            else:
                raise ValueError(f"unsupported multimodal content type: {kind}")
        conversation.append({"role": role, "content": parts})

    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        schema = response_format.get("json_schema") or {}
        instruction = "Return only a JSON object matching this schema: " + json.dumps(schema, ensure_ascii=False)
        system = next((m for m in conversation if m["role"] == "system"), None)
        if system is None:
            conversation.insert(0, {"role": "system", "content": instruction})
        elif isinstance(system.get("content"), str):
            system["content"] += "\n" + instruction
    return conversation, images, audios


def _generate(payload: dict) -> tuple[str, str]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    conversation, images, audios = _normalize_messages(messages, payload.get("response_format"))
    rendered = PROCESSOR.apply_chat_template(conversation, add_generation_prompt=True, tokenize=False)
    kwargs = {"text": rendered, "return_tensors": "pt"}
    if images:
        kwargs["images"] = images
    if audios:
        kwargs["audio"] = audios
        kwargs["audio_kwargs"] = {"sampling_rate": 16000}
    inputs = PROCESSOR(**kwargs).to(DEVICE)
    requested = payload.get("max_tokens", payload.get("max_completion_tokens", MAX_NEW_TOKENS))
    token_budget = max(16, min(int(requested or MAX_NEW_TOKENS), MAX_NEW_TOKENS))
    with INFERENCE_LOCK, torch.inference_mode():
        output = MODEL.generate(**inputs, max_new_tokens=token_budget, generation_mode="text", do_sample=False)
    start = int(inputs["input_ids"].shape[1])
    end = int(output.sequence_lengths[0])
    text = PROCESSOR.decode(output.sequences[0, start:end], skip_special_tokens=True).strip()
    finish = "length" if end - start >= token_budget else "stop"
    return text, finish


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        if self.path == "/v1/models":
            return self._send(200, {"object": "list", "data": [{"id": MODEL_ALIAS, "object": "model", "owned_by": "local"}]})
        return self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "not found"}})
        started = time.perf_counter()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 32 * 1024 * 1024:
                raise ValueError("request body is empty or exceeds 32 MiB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text, finish = _generate(payload)
            result = {
                "id": "chatcmpl-" + uuid.uuid4().hex,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": MODEL_ALIAS,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "x_local_latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            return self._send(200, result)
        except Exception as exc:
            return self._send(500, {"error": {"message": f"{type(exc).__name__}: {str(exc)[:400]}", "type": "server_error"}})

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> int:
    global MODEL, PROCESSOR, DEVICE, MODEL_ALIAS, MAX_NEW_TOKENS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--alias", default="local-lfm3-omni")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("this adapter is restricted to loopback")
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    DEVICE = args.device.lower().replace("cuda1", "cuda:1").replace("cuda0", "cuda:0")
    MODEL_ALIAS = args.alias
    MAX_NEW_TOKENS = max(16, min(args.max_new_tokens, 1024))
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the tested LFM3-Omni profile")
    torch.cuda.set_device(1 if DEVICE == "cuda:1" else 0)
    MODEL = AutoModelForImageTextToText.from_pretrained(
        args.model_dir, dtype=torch.bfloat16, device_map=DEVICE, trust_remote_code=True
    ).eval()
    PROCESSOR = AutoProcessor.from_pretrained(args.model_dir, trust_remote_code=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(json.dumps({"ready": True, "model": MODEL_ALIAS, "device": DEVICE, "port": args.port}), flush=True)
    server.serve_forever(poll_interval=0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
