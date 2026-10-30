"""Live WAV voice series: synth questions via TTS, feed as PCM16, measure.

Pipeline per turn: synthesize a question WAV with OmniVoice (Aleksandra),
convert to 16 kHz mono PCM16, stream chunks to /api/voice/audio, finalize
with /api/voice/end, and measure voice/end -> user-facing reply latency.
"""
from __future__ import annotations

import base64
import http.cookiejar
import io
import json
import statistics
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

BASE = "http://127.0.0.1:2367"
OUT = Path(__file__).resolve().parents[1] / "runtime" / "live-voice-series5.json"

QUESTIONS = [
    "Привет, как у тебя дела?",
    "Какая сегодня погода по ощущениям?",
    "Расскажи короткий анекдот.",
    "Что ты думаешь о нашей работе?",
    "Подведи итог сегодняшнего дня одной фразой.",
]


def opener_with_session():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    resp = opener.open(urllib.request.Request(BASE + "/api/session"), timeout=5)
    csrf = json.loads(resp.read())["csrf_token"]
    session = [c.value for c in jar if c.name == "companion_session"][0]
    headers = {
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": session,
        "Origin": "http://127.0.0.1:2367",
    }
    return opener, headers


def synth_question(opener, headers, text: str) -> bytes:
    body = json.dumps({"text": text, "voice": "main_ru"}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/tts/synthesize", data=body, headers=dict(headers))
    with opener.open(req, timeout=120) as r:
        return r.read()


def to_pcm16_16k_mono(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    else:
        raise ValueError(f"unsupported sample width {width}")
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        count = int(len(samples) * 16000 / sr)
        indices = np.linspace(0, len(samples) - 1, count).astype(int)
        samples = np.interp(indices, np.arange(len(samples)), samples)
    return (np.clip(samples, -32768, 32767)).astype("<i2").tobytes()


def main() -> int:
    opener, headers = opener_with_session()
    turns = []
    failures = []
    for index, question in enumerate(QUESTIONS, start=1):
        try:
            wav = synth_question(opener, headers, question)
            pcm = to_pcm16_16k_mono(wav)
        except Exception as exc:  # noqa: BLE001
            failures.append({"turn": index, "stage": "tts", "error": str(exc)[:200]})
            turns.append({"turn": index, "ok": False, "question": question})
            continue
        # Feed in ~250 ms chunks
        chunk_bytes = 16000 * 2 // 4
        fed = 0
        for start in range(0, len(pcm), chunk_bytes):
            piece = pcm[start : start + chunk_bytes]
            body = json.dumps({
                "pcm16_base64": base64.b64encode(piece).decode("ascii"),
                "sample_rate": 16000,
                "channels": 1,
                "session_id": f"live-voice-{index}",
            }).encode("utf-8")
            req = urllib.request.Request(BASE + "/api/voice/audio", data=body, headers=dict(headers))
            with opener.open(req, timeout=60) as r:
                json.loads(r.read())
            fed += 1
            time.sleep(0.05)
        t0 = time.time()
        body = json.dumps({"session_id": f"live-voice-{index}"}).encode("utf-8")
        req = urllib.request.Request(BASE + "/api/voice/end", data=body, headers=dict(headers))
        with opener.open(req, timeout=300) as r:
            data = json.loads(r.read())
        elapsed = round(time.time() - t0, 2)
        responses = data.get("responses") or []
        text = ""
        for item in responses:
            if isinstance(item, dict) and item.get("text"):
                text = str(item["text"])
                break
        transcript = str(data.get("transcript") or "")
        ok = bool(text) and "недоступен" not in text
        entry = {
            "turn": index,
            "ok": ok,
            "question": question,
            "transcript": transcript[:200],
            "reply": text[:300],
            "end_to_reply_s": elapsed,
            "chunks": fed,
        }
        if not ok:
            failures.append({"turn": index, "reply": text[:200], "raw": str(data)[:300]})
        turns.append(entry)
        print(f"[{index}/{len(QUESTIONS)}] {'OK ' if ok else 'FAIL'} end->reply {elapsed:5.1f}s | ASR: {transcript[:60]} | {text[:80]}")

    latencies = [t["end_to_reply_s"] for t in turns if t.get("ok")]
    report = {
        "schema_version": 1,
        "total": len(turns),
        "ok": len(latencies),
        "failed": len(failures),
        "failures": failures[:10],
        "end_to_reply": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
        },
        "turns": turns,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== VOICE SERIES SUMMARY ===")
    print(f"ok/total: {report['ok']}/{report['total']}")
    print(f"end->reply p50: {report['end_to_reply']['p50']} s")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
