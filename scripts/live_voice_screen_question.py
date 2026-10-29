"""Live integrated test: voice question about the screen content.

Synthesizes 'what is on my screen' via TTS, feeds it as a PCM16 voice turn,
and measures ASR + brain reply. Verifies D4+D2 integration: the companion
answers sensory questions through the live voice pipeline.
"""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jawl_voicecompanion.screen_adapter import ScreenCaptureAdapter  # noqa: E402

BASE = "http://127.0.0.1:2367"
OUT = Path(__file__).resolve().parents[1] / "runtime" / "live-voice-screen-question.json"

QUESTION = "Посмотри на мой экран и скажи коротко, что на нём открыто?"


def session():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    resp = opener.open(urllib.request.Request(BASE + "/api/session"), timeout=5)
    csrf = json.loads(resp.read())["csrf_token"]
    token = [c.value for c in jar if c.name == "companion_session"][0]
    headers = {
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": token,
        "Origin": "http://127.0.0.1:2367",
    }
    return opener, headers


def to_pcm16_16k_mono(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"unsupported width {width}")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        count = int(len(samples) * 16000 / sr)
        idx = np.linspace(0, len(samples) - 1, count).astype(int)
        samples = np.interp(idx, np.arange(len(samples)), samples)
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


def main() -> int:
    opener, headers = session()
    # 1. Synthesize the question
    body = json.dumps({"text": QUESTION, "voice": "main_ru"}).encode("utf-8")
    with opener.open(urllib.request.Request(BASE + "/api/tts/synthesize", data=body, headers=dict(headers)), timeout=120) as r:
        wav = r.read()
    pcm = to_pcm16_16k_mono(wav)
    # 2. Feed as voice turn
    chunk = 16000 * 2 // 4
    for start in range(0, len(pcm), chunk):
        piece = pcm[start : start + chunk]
        payload = json.dumps({
            "pcm16_base64": base64.b64encode(piece).decode("ascii"),
            "sample_rate": 16000, "channels": 1, "session_id": "live-voice-screen",
        }).encode("utf-8")
        with opener.open(urllib.request.Request(BASE + "/api/voice/audio", data=payload, headers=dict(headers)), timeout=60) as r:
            json.loads(r.read())
        time.sleep(0.04)
    t0 = time.time()
    payload = json.dumps({"session_id": "live-voice-screen"}).encode("utf-8")
    with opener.open(urllib.request.Request(BASE + "/api/voice/end", data=payload, headers=dict(headers)), timeout=300) as r:
        data = json.loads(r.read())
    elapsed = round(time.time() - t0, 2)
    transcript = str(data.get("transcript") or "")
    reply = ""
    for item in data.get("responses") or []:
        if isinstance(item, dict) and item.get("text"):
            reply = str(item["text"])
            break
    report = {
        "question": QUESTION,
        "asr_transcript": transcript[:200],
        "reply": reply[:600],
        "end_to_reply_s": elapsed,
        "ok": bool(reply) and "недоступен" not in reply,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ASR:", transcript[:120])
    print("REPLY:", reply[:400])
    print("end->reply:", elapsed, "s")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
