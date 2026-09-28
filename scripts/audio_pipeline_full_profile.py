"""Full audio pipeline profile: Companion + TeraTTS worker + mock brain.

Runs scripts/run_audio_pipeline_profile.py against a real Companion instance with
the canonical GigaAM transcriber and a real TeraTTSv2 worker, so the measured
stage times cover the whole text->speech chain that the SLO applies to.

Stage numbers come from the profile script itself; this wrapper only arranges the
stack, enforces the SLO threshold and records what happened.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
CRISPASR = r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe"
GIGAAM = r"G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf"
VOICEMEM_PY = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"
TERA_PY = r"G:\AI\tts_env\Scripts\python.exe"
TERA_RELEASE = r"G:\AI\tts_models\TeraSpace__TeraTTSv2"
WAV = ROOT / "runtime" / "voice-native-ru-clean-20260906.wav"
REPORT = ROOT / "runtime" / "audio-pipeline-full-adr044.json"
SLO_END_SECONDS = 6.0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def port_open(port: int, timeout: float = 0.5) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    tts_port = 9889
    port = free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    tts = None
    companion = None
    result: dict = {"schema_version": 1, "profile": "audio-pipeline-full-adr044",
                    "slo_end_seconds": SLO_END_SECONDS, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        if not port_open(tts_port):
            print(f"starting TeraTTS worker on {tts_port}", flush=True)
            tts = subprocess.Popen(
                [TERA_PY, "scripts/teratts_server.py", "--release-dir", TERA_RELEASE,
                 "--voice", "ru_f1", "--model", "distilled", "--threads", "24",
                 "--host", "127.0.0.1", "--port", str(tts_port)],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            deadline = time.time() + 240
            while time.time() < deadline:
                if tts.poll() is not None:
                    raise RuntimeError("TeraTTS worker exited during startup")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{tts_port}/health", timeout=2) as response:
                        if json.loads(response.read(4096).decode("utf-8")).get("status") == "ok":
                            break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError("TeraTTS worker did not become healthy")
        result["tts_worker_started_here"] = tts is not None
        print("TeraTTS healthy", flush=True)

        print(f"starting Companion on {port}", flush=True)
        companion = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "jawl_voicecompanion",
             "--host", "127.0.0.1", "--port", str(port),
             "--presentation-host", "127.0.0.1", "--presentation-port", str(free_port()),
             "--voicemem-python", VOICEMEM_PY,
             "--tts-provider", "tera", "--tts-url", f"http://127.0.0.1:{tts_port}",
             "--streaming-asr", "--streaming-asr-exe", CRISPASR, "--streaming-asr-model", GIGAAM],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.time() + 90
        ready = False
        while time.time() < deadline:
            if companion.poll() is not None:
                raise RuntimeError("Companion exited during startup")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3):
                    ready = True
                    break
            except Exception:
                time.sleep(1)
        if not ready:
            raise RuntimeError("Companion did not become reachable")
        print("Companion reachable", flush=True)

        command = [sys.executable, "-X", "utf8", "scripts/run_audio_pipeline_profile.py",
                   "--url", f"http://127.0.0.1:{port}", "--wav", str(WAV),
                   "--max-end-seconds", str(SLO_END_SECONDS),
                   # The profile is fail-closed: it refuses to touch a live stack
                   # without this explicit acknowledgement.
                   "--live",
                   "--report", str(REPORT)]
        print("running pipeline profile", flush=True)
        completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=900)
        tail = (completed.stdout or "").strip().splitlines()
        print("\n".join(tail[-20:]), flush=True)
        if completed.stderr:
            print("stderr tail:", completed.stderr[-500:], flush=True)
        result["profile_exit"] = completed.returncode
        if REPORT.exists():
            result["profile_report"] = json.loads(REPORT.read_text(encoding="utf-8"))
        result["status"] = "passed" if completed.returncode == 0 else "failed"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "failed"
        result["failure"] = f"{type(exc).__name__}: {str(exc)[:250]}"
        print(f"FAILED: {result['failure']}", flush=True)
    finally:
        for process, label in ((companion, "companion"), (tts, "tts")):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        (ROOT / "runtime" / "audio-pipeline-full-adr044-wrapper.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrapper report: {ROOT / 'runtime' / 'audio-pipeline-full-adr044-wrapper.json'}", flush=True)
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())