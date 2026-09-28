"""Fault injection: a broken GigaAM must fail loudly, never silently.

ADR-044's core claim is that a transcriber failure is reported explicitly
(unavailable/failed) instead of being masked by a second engine. This drives the
real Companion with a deliberately broken crispasr path and checks what the voice
lane actually returns - and that no transcript is invented.
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
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
WAV = ROOT / "runtime" / "voice-native-ru-clean-20260906.wav"
VOICEMEM_PY = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"
BOGUS_EXE = r"G:\AI\crispasr\does-not-exist\crispasr.exe"
REAL_MODEL = r"G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf"
REPORT = ROOT / "runtime" / "asr-fault-injection-adr044.json"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


def run_case(label: str, exe: str, model: str) -> dict:
    port = free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "jawl_voicecompanion",
         "--host", "127.0.0.1", "--port", str(port),
         "--presentation-host", "127.0.0.1", "--presentation-port", str(free_port()),
         "--voicemem-python", VOICEMEM_PY,
         "--streaming-asr", "--streaming-asr-exe", exe, "--streaming-asr-model", model],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = f"http://127.0.0.1:{port}"
    case: dict = {"case": label, "exe": exe}
    try:
        deadline = time.time() + 90
        csrf = ""
        while time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError("companion exited during startup")
            try:
                with opener.open(base + "/api/session", timeout=3) as response:
                    csrf = json.loads(response.read().decode("utf-8")).get("csrf_token", "")
                if csrf:
                    break
            except Exception:
                time.sleep(0.5)
        headers = {"X-Companion-CSRF": csrf, "Content-Type": "application/json"}

        def post(path: str, payload: dict, timeout: float = 120.0):
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(base + path, data=data, method="POST")
            for key, value in headers.items():
                request.add_header(key, value)
            began = time.perf_counter()
            try:
                with opener.open(request, timeout=timeout) as response:
                    return response.status, json.loads(response.read().decode("utf-8")), time.perf_counter() - began
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = {"raw": body[:200]}
                return exc.code, parsed, time.perf_counter() - began

        with wave.open(str(WAV), "rb") as handle:
            pcm = resample_16k(handle.readframes(handle.getnframes()),
                               handle.getframerate(), handle.getnchannels())
        step = 3200 * 2
        for index in range(0, len(pcm), step):
            status, body, _ = post("/api/voice/audio", {
                "pcm16_base64": base64.b64encode(pcm[index:index + step]).decode("ascii"),
                "sample_rate": 16000, "channels": 1, "session_id": "fault"})
            case["feed_status"] = status
        status, body, seconds = post("/api/voice/end", {"session_id": "fault"})
        case["end_status"] = status
        case["end_seconds"] = round(seconds, 3)
        case["end_ok"] = body.get("ok")
        case["transcript"] = body.get("transcript")
        case["error"] = body.get("error")
        case["event_types"] = body.get("event_types")
        # A silent fallback would look like ok=true with an invented transcript.
        case["invented_transcript"] = bool(body.get("transcript"))
        case["failed_loudly"] = body.get("ok") is False and bool(body.get("error"))
    except Exception as exc:  # noqa: BLE001
        case["probe_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return case


def main() -> int:
    report: dict = {"schema_version": 1, "profile": "asr-fault-injection-adr044",
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    broken = run_case("broken-crispasr", BOGUS_EXE, REAL_MODEL)
    print(json.dumps(broken, ensure_ascii=False, indent=2), flush=True)
    report["broken_crispasr"] = broken
    report["status"] = "passed" if broken.get("failed_loudly") and not broken.get("invented_transcript") else "failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nverdict: {report['status']} (failed_loudly={broken.get('failed_loudly')}, "
          f"invented_transcript={broken.get('invented_transcript')})", flush=True)
    print(f"report: {REPORT}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())