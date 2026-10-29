"""Record one physical-microphone turn and feed it through the live voice path."""
from __future__ import annotations

import base64
import http.cookiejar
import io
import json
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio

BASE = "http://127.0.0.1:2367"
OUT = Path(__file__).resolve().parents[1] / "runtime" / "live-mic-turn-20261020.json"
SECONDS = 6.0


def find_fifine(p: pyaudio.PyAudio) -> int:
    candidates = []
    for index in range(p.get_device_count()):
        info = p.get_device_info_by_index(index)
        if int(info.get("maxInputChannels") or 0) > 0 and "fifine" in str(info.get("name", "")).lower():
            candidates.append((index, info))
    if not candidates:
        raise RuntimeError("Fifine input device was not found")
    wasapi = [item for item in candidates if "wasapi" in str(p.get_host_api_info_by_index(item[1]["hostApi"])["name"]).lower()]
    index, info = (wasapi or candidates)[0]
    return index


def resample_pcm16(raw: bytes, source_rate: int, channels: int) -> bytes:
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if source_rate != 16000:
        count = int(len(samples) * 16000 / source_rate)
        indices = np.linspace(0, len(samples) - 1, count).astype(int)
        samples = np.interp(indices, np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


def session():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(urllib.request.Request(BASE + "/api/session"), timeout=5) as r:
        csrf = json.loads(r.read())["csrf_token"]
    token = [c.value for c in jar if c.name == "companion_session"][0]
    return opener, {
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": token,
        "Origin": BASE,
    }


def main() -> int:
    p = pyaudio.PyAudio()
    index = find_fifine(p)
    info = p.get_device_info_by_index(index)
    rate = int(info["defaultSampleRate"])
    channels = 1
    frames: list[bytes] = []
    stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                    input=True, input_device_index=index, frames_per_buffer=1024)
    try:
        print(f"RECORDING {SECONDS:.0f}s device={info['name']} rate={rate}", flush=True)
        deadline = time.time() + SECONDS
        while time.time() < deadline:
            frames.append(stream.read(1024, exception_on_overflow=False))
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
    pcm = resample_pcm16(b"".join(frames), rate, channels)

    opener, headers = session()
    chunk_bytes = 16000 * 2 // 4
    for start in range(0, len(pcm), chunk_bytes):
        piece = pcm[start:start + chunk_bytes]
        body = json.dumps({
            "pcm16_base64": base64.b64encode(piece).decode("ascii"),
            "sample_rate": 16000, "channels": 1, "session_id": "live-mic-20261020",
        }).encode("utf-8")
        req = urllib.request.Request(BASE + "/api/voice/audio", data=body, headers=dict(headers))
        with opener.open(req, timeout=60) as r:
            json.loads(r.read())
        time.sleep(0.05)
    t0 = time.time()
    body = json.dumps({"session_id": "live-mic-20261020"}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/voice/end", data=body, headers=dict(headers))
    with opener.open(req, timeout=300) as r:
        data = json.loads(r.read())
    elapsed = round(time.time() - t0, 2)
    responses = data.get("responses") or []
    reply = ""
    for item in responses:
        if isinstance(item, dict) and item.get("text"):
            reply = str(item["text"])
            break
    report = {
        "schema_version": 1,
        "device": str(info["name"]),
        "sample_rate": rate,
        "captured_seconds": SECONDS,
        "end_to_reply_s": elapsed,
        "transcript": str(data.get("transcript") or ""),
        "reply": reply,
        "response_count": len(responses),
        "limitation": "Direct PCM feed tests physical mic + ASR + brain + TTS; it bypasses the browser mic gate and player.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if reply else 1


if __name__ == "__main__":
    raise SystemExit(main())
