"""Measure the ASR stage of the interactive loop against the ADR-044 SLO.

Stage timing only: this drives the real Companion voice endpoints with real audio
and reports where time goes (session bootstrap, per-chunk feed, final utterance).
It does not claim JAWL/TTS latency, which needs the full stack.

Reports cold (first utterance after start) and warm (repeated) numbers so the
"first phrase after idle is slow" question gets a measured answer.
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
CRISPASR = r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe"
GIGAAM = r"G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf"
VOICEMEM_PY = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"
REPORT = ROOT / "runtime" / "asr-latency-adr044.json"
WARM_RUNS = 5


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


def main() -> int:
    wav = ROOT / "runtime" / "voice-native-ru-clean-20260906.wav"
    if not wav.exists():
        print(f"missing fixture: {wav}", flush=True)
        return 1
    with wave.open(str(wav), "rb") as handle:
        pcm = resample_16k(handle.readframes(handle.getnframes()),
                           handle.getframerate(), handle.getnchannels())
    chunk_frames = 3200  # 200 ms at 16 kHz
    chunks = [pcm[i:i + chunk_frames * 2] for i in range(0, len(pcm), chunk_frames * 2)]
    audio_seconds = len(pcm) / 2 / 16000

    port = free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "jawl_voicecompanion",
         "--host", "127.0.0.1", "--port", str(port),
         "--presentation-host", "127.0.0.1", "--presentation-port", str(free_port()),
         "--voicemem-python", VOICEMEM_PY,
         "--streaming-asr", "--streaming-asr-exe", CRISPASR, "--streaming-asr-model", GIGAAM],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = f"http://127.0.0.1:{port}"
    report = {
        "schema_version": 1,
        "profile": "asr-latency-adr044",
        "audio_seconds": round(audio_seconds, 2),
        "chunk_ms": 200,
        "chunks_per_utterance": len(chunks),
        "warm_runs": WARM_RUNS,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        # session bootstrap
        started = time.perf_counter()
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
        report["session_bootstrap_seconds"] = round(time.perf_counter() - started, 3)
        headers = {"X-Companion-CSRF": csrf, "Content-Type": "application/json"}

        def post(path: str, payload: dict, timeout: float = 120.0) -> tuple[int, dict, float]:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(base + path, data=data, method="POST")
            for key, value in headers.items():
                request.add_header(key, value)
            began = time.perf_counter()
            try:
                with opener.open(request, timeout=timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    return response.status, body, time.perf_counter() - began
            except urllib.error.HTTPError as exc:
                return exc.code, {"error": exc.read().decode("utf-8", "replace")[:200]}, time.perf_counter() - began

        def utterance(tag: str) -> dict:
            feed_times = []
            for chunk in chunks:
                status, body, elapsed = post("/api/voice/audio", {
                    "pcm16_base64": base64.b64encode(chunk).decode("ascii"),
                    "sample_rate": 16000, "channels": 1, "session_id": "latency",
                })
                if status != 200:
                    return {"tag": tag, "error": f"feed {status}: {body.get('error')}"}
                feed_times.append(elapsed)
            status, body, end_seconds = post("/api/voice/end", {"session_id": "latency"})
            return {
                "tag": tag,
                "feeds": len(feed_times),
                "feed_p50_seconds": round(statistics.median(feed_times), 4),
                "feed_max_seconds": round(max(feed_times), 4),
                "final_seconds": round(end_seconds, 3),
                "end_status": status,
                "transcript_chars": len(str(body.get("transcript") or "")),
                "transcript": str(body.get("transcript") or "")[:120],
            }

        cold = utterance("cold")
        report["cold"] = cold
        warm = [utterance(f"warm-{index + 1}") for index in range(WARM_RUNS)]
        report["warm"] = warm
        finals = [run["final_seconds"] for run in warm if "final_seconds" in run]
        feeds = [run["feed_p50_seconds"] for run in warm if "feed_p50_seconds" in run]
        if finals:
            report["warm_final_p50_seconds"] = round(statistics.median(finals), 3)
            report["warm_final_p95_seconds"] = round(
                sorted(finals)[min(len(finals) - 1, int(0.95 * len(finals)))], 3
            )
            report["warm_final_max_seconds"] = round(max(finals), 3)
        if feeds:
            report["warm_feed_p50_seconds"] = round(statistics.median(feeds), 4)
        # SLO check: the final utterance must not dominate the turn budget.
        budget = 6.0
        report["slo_warm_turn_budget_seconds"] = budget
        report["slo_asr_share_ok"] = (
            report.get("warm_final_max_seconds", 99) < budget / 2
        )
        report["status"] = "passed" if report.get("slo_asr_share_ok") else "failed"
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())