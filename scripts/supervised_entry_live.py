"""Live verification of `python -m jawl_voicecompanion --supervise-workers`.

One executable entry (ADR-041 stage 2 slice): the Companion process itself
raises the local brain and TTS workers through RuntimeSupervisor, serves,
and tears everything down on exit. Everything below is measured against the
real processes.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
REPORT = ROOT / "runtime" / "supervised-entry-live-20260929.json"
VOICEMEM_PY = r"G:\AI\VoiceMem\.venv\Scripts\python.exe"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_get(url: str, timeout: float = 5) -> int:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status


def main() -> int:
    port = free_port()
    env = {**__import__("os").environ,
           "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [
        sys.executable, "-X", "utf8", "-m", "jawl_voicecompanion",
        "--host", "127.0.0.1", "--port", str(port),
        "--voicemem-python", VOICEMEM_PY,
        "--supervise-workers",
    ]
    print(f"starting supervised entry on control {port}", flush=True)
    process = subprocess.Popen(command, cwd=ROOT, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
    report: dict = {"schema_version": 1, "profile": "supervised-entry-live",
                    "command": command[-1:]}
    output_lines: list[str] = []

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output_lines.append(line.rstrip("\n"))

    import threading
    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    try:
        # Wait until the control server answers, then check the workers.
        deadline = time.time() + 300
        ready = False
        while time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError("entry process exited during startup")
            try:
                if http_get(f"http://127.0.0.1:{port}/api/health", timeout=2) == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(1)
        report["control_ready"] = ready
        if not ready:
            raise RuntimeError("control server did not become ready")

        def wait_healthy(url: str, label: str, budget: float = 240) -> bool:
            began = time.time()
            while time.time() - began < budget:
                try:
                    if http_get(url, timeout=2) == 200:
                        report[f"{label}_ready_seconds"] = round(time.time() - began, 1)
                        return True
                except Exception:
                    time.sleep(1)
            return False

        brain_ok = wait_healthy("http://127.0.0.1:8990/health", "brain")
        tts_ok = wait_healthy("http://127.0.0.1:9889/health", "tts")
        report["brain_healthy"] = brain_ok
        report["tts_healthy"] = tts_ok

        # A real LLM turn through the supervised brain.
        payload = {"model": "local-brain",
                   "messages": [{"role": "system", "content": "Ответь одним словом."},
                                {"role": "user", "content": "Работает?"}],
                   "max_tokens": 20, "response_format": {"type": "json_object"}}
        request = urllib.request.Request(
            "http://127.0.0.1:8990/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        began = time.perf_counter()
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
        report["llm_seconds"] = round(time.perf_counter() - began, 2)
        report["llm_reply"] = body["choices"][0]["message"]["content"][:100]
        print(f"llm turn: {report['llm_seconds']}s -> {report['llm_reply']!r}", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        thread.join(timeout=3)
        # Teardown proof: nothing the entry owned may keep listening. The job
        # object reaps workers asynchronously after the parent's handle closes,
        # so poll for a bounded window instead of a single instant check.
        for port_to_check, label in ((8990, "brain"), (9889, "tts")):
            deadline = time.time() + 30
            free = False
            while time.time() < deadline:
                with socket.socket() as sock:
                    sock.settimeout(0.5)
                    if sock.connect_ex(("127.0.0.1", port_to_check)) != 0:
                        free = True
                        break
                time.sleep(1)
            report[f"{label}_port_free_after_exit"] = free
    report["stdout_tail"] = output_lines[-12:]
    report["status"] = "passed" if (
        report.get("control_ready") and report.get("brain_healthy")
        and report.get("tts_healthy") and report.get("llm_seconds", 99) < 10
        and report.get("brain_port_free_after_exit") and report.get("tts_port_free_after_exit")
    ) else "failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("stdout_tail",)},
                     ensure_ascii=False, indent=2), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())