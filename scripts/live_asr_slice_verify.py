"""Live ASR slice verification against the real product path (ADR-044).

Starts the Companion with the canonical GigaAM transcriber configured (no
provider, no mock), feeds a real 16 kHz PCM16 WAV through the real HTTP voice
lane, and records what the product actually returns:

  POST /api/session                     -> session token + csrf
  POST /api/voice/audio   (2 chunks)    -> buffered by UtteranceBuffer
  POST /api/voice/end                   -> GigaAM final transcript
  GET  /api/voice/draft                 -> must report the streaming lane

Nothing here is a unit test: every number printed comes from the running server.
"""

from __future__ import annotations

import base64
import http.cookiejar
import io
import json
import socket
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
CRISPASR = Path(r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe")
GIGAAM = Path(r"G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf")
VOICEMEM_PY = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"
RESULT = ROOT / "runtime" / "live-asr-slice-adr044.json"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


MAX_CHUNK_BYTES = 32 * 1024  # the browser sends small chunks; MAX_BODY_BYTES is 64 KiB
TARGET_RATE = 16000  # the browser AudioWorklet capture rate


def _resample_to_16k(frames: bytes, rate: int, channels: int) -> bytes:
    """Linear-resample to 16 kHz mono the way the browser capture path delivers it."""
    import array

    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % (2 * channels)])
    if channels > 1:
        samples = array.array("h", [
            samples[index] for index in range(0, len(samples), channels)
        ])
    if rate == TARGET_RATE:
        return samples.tobytes()
    ratio = TARGET_RATE / rate
    out_length = int(len(samples) * ratio)
    out = array.array("h", bytes(2 * out_length))
    for index in range(out_length):
        position = index / ratio
        left = int(position)
        frac = position - left
        right = min(left + 1, len(samples) - 1)
        out[index] = int(samples[left] * (1 - frac) + samples[right] * frac)
    return out.tobytes()


def pcm16_chunks(wav_path: Path, chunks: int) -> tuple[list[bytes], int, int]:
    """Split a WAV into frame-aligned 16 kHz chunks that respect the HTTP limit."""
    with wave.open(str(wav_path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    frames = _resample_to_16k(frames, rate, channels)
    channels = 1
    rate = TARGET_RATE
    frame_bytes = 2 * channels
    per_chunk = max(frame_bytes, (len(frames) // chunks) // frame_bytes * frame_bytes)
    per_chunk = min(per_chunk, MAX_CHUNK_BYTES - MAX_CHUNK_BYTES % frame_bytes)
    out = []
    offset = 0
    while offset < len(frames):
        end = offset + per_chunk
        if end > len(frames):
            end = len(frames)
        end -= (end - offset) % frame_bytes
        if end == offset:
            break
        out.append(frames[offset:end])
        offset = end
    return out, rate, channels


def main() -> int:
    for path in (CRISPASR, GIGAAM):
        if not path.exists():
            print(f"missing resource: {path}", flush=True)
            return 1
    wavs = [
        ROOT / "runtime" / "voice-native-ru-clean-20260906.wav",
        ROOT / "runtime" / "voice-native-command-20260906.wav",
        ROOT / "runtime" / "bench" / "rumbench_ru" / "ref_ru.wav",
    ]
    wavs = [path for path in wavs if path.exists()]
    if not wavs:
        print("no fixture WAVs found", flush=True)
        return 1

    port = free_port()
    env = subprocess.os.environ.copy() if hasattr(subprocess, "os") else __import__("os").environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable, "-X", "utf8", "-m", "jawl_voicecompanion",
        "--host", "127.0.0.1", "--port", str(port),
        "--presentation-host", "127.0.0.1", "--presentation-port", str(free_port()),
        # The voice lane requires the VoiceMem sidecar (it owns the same audio
        # session), so the live slice runs the real daily shape, not a mock.
        "--voicemem-python", VOICEMEM_PY,
        "--streaming-asr",
        "--streaming-asr-exe", str(CRISPASR),
        "--streaming-asr-model", str(GIGAAM),
    ]
    print(f"starting Companion on {port} with canonical GigaAM transcriber", flush=True)
    process = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = f"http://127.0.0.1:{port}"
    results: list[dict] = []
    report = {
        "schema_version": 1,
        "profile": "live-asr-slice-adr044",
        "engine": "gigaam",
        "crispasr": str(CRISPASR),
        "model": str(GIGAAM),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "utterances": results,
    }

    def call(path: str, payload: dict | None = None, timeout: float = 120.0) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
        if data:
            request.add_header("Content-Type", "application/json")
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"raw": body[:300]}

    try:
        # Wait for health.
        deadline = time.time() + 60
        health = {}
        while time.time() < deadline:
            if process.poll() is not None:
                print("companion exited during startup", flush=True)
                break
            try:
                status, health = call("/api/health", timeout=3)
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        print(f"health: {health.get('status') or health}", flush=True)
        report["health"] = health

        status, session = call("/api/session")
        print(f"session: {status}", flush=True)
        csrf = session.get("csrf_token") or ""
        # The session itself rides a cookie (companion_session); only the CSRF
        # token has to be echoed in a header on every control POST.
        headers = {"X-Companion-CSRF": csrf}
        report["session_ok"] = bool(csrf)

        # Rebuild opener with default headers by wrapping each request.
        def call_authed(path: str, payload: dict | None = None, timeout: float = 180.0):
            # Every voice endpoint is POST-only: an empty object is a valid body.
            data = json.dumps(payload if payload is not None else {}).encode("utf-8")
            request = urllib.request.Request(base + path, data=data, method="POST")
            for key, value in headers.items():
                request.add_header(key, value)
            request.add_header("Content-Type", "application/json")
            try:
                with opener.open(request, timeout=timeout) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                try:
                    return exc.code, json.loads(body)
                except json.JSONDecodeError:
                    return exc.code, {"raw": body[:300]}

        # Draft lane must be explicit about its owner (streaming bridge is on).
        status, draft = call_authed("/api/voice/draft")
        print(f"draft: {status} {draft}", flush=True)
        report["draft_mode"] = draft.get("mode")

        for wav in wavs:
            chunks, rate, channels = pcm16_chunks(wav, 2)
            entry: dict = {"wav": str(wav.name), "sample_rate": rate, "channels": channels,
                           "bytes": sum(len(c) for c in chunks)}
            buffered_sizes = []
            for chunk in chunks:
                status, body = call_authed("/api/voice/audio", {
                    "pcm16_base64": base64.b64encode(chunk).decode("ascii"),
                    "sample_rate": rate,
                    "channels": channels,
                    "session_id": "live-slice",
                })
                buffered_sizes.append(body.get("buffer", {}).get("bytes"))
                entry["feed_status"] = status
            entry["buffered_bytes"] = buffered_sizes
            started = time.time()
            status, end = call_authed("/api/voice/end", {"session_id": "live-slice"})
            entry["end_seconds"] = round(time.time() - started, 3)
            entry["end_status"] = status
            entry["mode"] = end.get("mode")
            entry["transcript"] = end.get("transcript", "")
            entry["event_types"] = end.get("event_types", [])
            entry["response"] = (end.get("responses") or [{}])[0].get("text", "")[:200] if end.get("responses") else ""
            entry["error"] = end.get("error")
            results.append(entry)
            print(f"\n{wav.name}: {rate} Hz x{channels}, {entry['bytes']} bytes", flush=True)
            print(f"  feed: {entry['feed_status']} buffered={buffered_sizes}", flush=True)
            print(f"  end: {status} in {entry['end_seconds']} s, mode={entry['mode']}", flush=True)
            print(f"  transcript: {entry['transcript']!r}", flush=True)
            if entry.get("error"):
                print(f"  ERROR: {entry['error']}", flush=True)

        # VoiceMem enrichment must not be required for the transcript itself.
        def call_get(path: str, timeout: float = 30.0):
            request = urllib.request.Request(base + path, method="GET")
            for key, value in headers.items():
                request.add_header(key, value)
            try:
                with opener.open(request, timeout=timeout) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, {}

        status, status_body = call_get("/api/runtime/status")
        report["runtime_status"] = {key: status_body.get(key) for key in ("ok", "service", "configured", "status")}
        print(f"\nruntime status: {report['runtime_status']}", flush=True)
        status, doctor = call_get("/api/doctor")
        checks = {item.get("id"): item for item in doctor.get("checks", [])}
        report["doctor_asr"] = checks.get("asr")
        print(f"doctor asr: {report['doctor_asr']}", flush=True)
        transcript_count = sum(1 for entry in results if entry.get("transcript"))
        report["transcripts_ok"] = transcript_count
        report["utterances_total"] = len(results)
        report["status"] = "passed" if transcript_count == len(results) else "failed"
        print(f"\nRESULT: {transcript_count}/{len(results)} transcripts, status={report['status']}", flush=True)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"FAILED: {report['failure']}", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                out, err = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                out, err = process.communicate()
        else:
            out, err = process.communicate()
        tail = (err or b"").decode("utf-8", "replace")
        lines = [line for line in tail.splitlines() if line.strip()]
        report["server_stderr_tail"] = lines[-15:]
        RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nreport: {RESULT}", flush=True)
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())