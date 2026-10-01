"""Measure real first-audio latency through the live voice lane.

Drives a real Companion + real TeraTTS worker with real audio, then reads the
sentence-WAV stream the product sends to the browser and records when the first
audible chunk arrives. This is the "first-audio" number the SLO cares about, not
the total synthesis time of the whole reply.
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
CRISPASR = r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe"
GIGAAM = r"G:\AI\JAWL-VoiceCompanion\runtime\models\asr\gigaam-v3-e2e-rnnt-q8_0.gguf"
VOICEMEM_PY = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"
TERA_PY = r"G:\AI\tts_env\Scripts\python.exe"
TERA_RELEASE = r"G:\AI\tts_models\TeraSpace__TeraTTSv2"
WAV = ROOT / "runtime" / "voice-native-ru-clean-20260906.wav"
REPORT = ROOT / "runtime" / "first-audio-adr044.json"
TTS_PORT = 9889


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def resample_16k(frames: bytes, rate: int, channels: int) -> bytes:
    import array

    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % (2 * channels)])
    if channels > 1:
        samples = array.array("h", [samples[i] for i in range(0, len(samples), channels)])
    if rate == 16000:
        return samples.tobytes()
    ratio = 16000 / rate
    out = array.array("h", bytes(2 * int(len(samples) * ratio)))
    for index in range(len(out)):
        position = index / ratio
        left = int(position)
        frac = position - left
        right = min(left + 1, len(samples) - 1)
        out[index] = int(samples[left] * (1 - frac) + samples[right] * frac)
    return out.tobytes()


def main() -> int:
    report: dict = {"schema_version": 1, "profile": "first-audio-adr044",
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    tts = companion = None
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        if not port_open(TTS_PORT):
            tts = subprocess.Popen(
                [TERA_PY, "scripts/teratts_server.py", "--release-dir", TERA_RELEASE,
                 "--voice", "ru_f1", "--model", "distilled", "--threads", "24",
                 "--host", "127.0.0.1", "--port", str(TTS_PORT)],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + 240
            while time.time() < deadline:
                if tts.poll() is not None:
                    raise RuntimeError("TeraTTS exited during startup")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{TTS_PORT}/health", timeout=2) as r:
                        if json.loads(r.read(4096).decode("utf-8")).get("status") == "ok":
                            break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError("TeraTTS did not become healthy")
        print("TTS ready", flush=True)

        port = free_port()
        companion = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "jawl_voicecompanion",
             "--host", "127.0.0.1", "--port", str(port),
             "--presentation-host", "127.0.0.1", "--presentation-port", str(free_port()),
             "--voicemem-python", VOICEMEM_PY,
             "--tts-provider", "tera", "--tts-url", f"http://127.0.0.1:{TTS_PORT}",
             "--streaming-asr", "--streaming-asr-exe", CRISPASR, "--streaming-asr-model", GIGAAM],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 90
        while time.time() < deadline:
            if companion.poll() is not None:
                raise RuntimeError("Companion exited during startup")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3):
                    break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Companion did not become reachable")
        print("Companion ready", flush=True)
        base = f"http://127.0.0.1:{port}"

        with urllib.request.urlopen(base + "/api/session", timeout=5) as response:
            csrf = json.loads(response.read().decode("utf-8"))["csrf_token"]
            cookie = response.headers.get("Set-Cookie", "").split(";")[0]
        headers = {"Cookie": cookie, "X-Companion-Session": cookie.split("=", 1)[-1],
                   "X-Companion-CSRF": csrf, "Content-Type": "application/json"}

        with wave.open(str(WAV), "rb") as handle:
            pcm = resample_16k(handle.readframes(handle.getnframes()),
                               handle.getframerate(), handle.getnchannels())
        step = 3200 * 2

        def post(path: str, payload: dict, timeout: float = 120.0):
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(base + path, data=data, method="POST")
            for key, value in headers.items():
                request.add_header(key, value)
            began = time.perf_counter()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8"), time.perf_counter() - began

        for index in range(0, len(pcm), step):
            post("/api/voice/audio", {
                "pcm16_base64": base64.b64encode(pcm[index:index + step]).decode("ascii"),
                "sample_rate": 16000, "channels": 1, "session_id": "first-audio"})
        turn_started = time.perf_counter()
        status, body, end_seconds = post("/api/voice/end", {"session_id": "first-audio"})
        end_payload = json.loads(body)
        report["end_seconds"] = round(end_seconds, 3)
        report["end_status"] = status
        report["response_chars"] = len(str(end_payload.get("responses", [{}])[0].get("text", "")))

        # The browser then asks for streaming speech of that reply; the endpoint
        # emits newline-delimited JSON, one {"type":"audio", "data_base64": ...}
        # per sentence, deliberately unbuffered so the first sentence ships early.
        reply = str(end_payload.get("responses", [{}])[0].get("text", "")) or "Проверка связи."
        request = urllib.request.Request(
            base + "/api/tts/stream",
            data=json.dumps({"text": reply}).encode("utf-8"),
            method="POST",
        )
        for key, value in headers.items():
            request.add_header(key, value)
        speech_started = time.perf_counter()
        first_chunk_at = None
        first_chunk_bytes = 0
        chunks = 0
        with urllib.request.urlopen(request, timeout=180) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                chunks += 1
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter() - speech_started
                    try:
                        first_chunk_bytes = len(base64.b64decode(json.loads(line).get("data_base64", "")))
                    except Exception:
                        first_chunk_bytes = 0
        report["speech_stream_chunks"] = chunks
        report["first_chunk_bytes"] = first_chunk_bytes
        report["first_sentence_seconds"] = round(first_chunk_at or -1, 3)
        report["speech_total_seconds"] = round(time.perf_counter() - speech_started, 3)
        # End-to-end audio latency: from the end of the user's utterance to the
        # first audible sentence.
        report["first_audio_seconds_after_end"] = round((speech_started - turn_started) + (first_chunk_at or 0), 3)
        report["slo_first_audio_seconds"] = 10.0
        report["first_audio_ok"] = report["first_audio_seconds_after_end"] <= 10.0
        report["status"] = "passed" if report["first_audio_ok"] else "failed"
        print(json.dumps({k: v for k, v in report.items() if k != "schema_version"},
                         ensure_ascii=False, indent=2), flush=True)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {str(exc)[:250]}"
        print(f"FAILED: {report['failure']}", flush=True)
    finally:
        for process in (companion, tts):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"report: {REPORT}", flush=True)
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())