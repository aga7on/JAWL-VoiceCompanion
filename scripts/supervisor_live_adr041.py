"""Live verification: RuntimeSupervisor owns the real stack (ADR-041 stage 2).

Starts the actual local workers (Hikari brain on llama-server, TeraTTS) through
the product supervisor - not the PowerShell launcher - and proves:
  start -> health -> restart one worker (new pid, healthy again) -> stop.
Every number below comes from real processes.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec  # noqa: E402

LLAMA = r"G:\AI\llamacpp-prism\build-fa\bin\llama-server.exe"
HIKARI = r"G:\AI\models\Ternary-Bonsai-2-27B-Abliterated-Hikari\Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf"
TERA_PY = r"G:\AI\tts_env\Scripts\python.exe"
TERA_RELEASE = r"G:\AI\tts_models\TeraSpace__TeraTTSv2"
REPORT = ROOT / "runtime" / "supervisor-live-20260929.json"


def probe(port: int, path: str = "/health"):
    def check() -> bool:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status == 200
    return check


def main() -> int:
    specs = [
        WorkerSpec(
            name="brain",
            command=[LLAMA, "--model", HIKARI, "--alias", "bonsai2",
                     "--host", "127.0.0.1", "--port", "8990",
                     "--threads", "12", "--ctx-size", "16384", "--parallel", "1",
                     "--gpu-layers", "99", "--device", "CUDA1"],
            probe=probe(8990),
            startup_timeout_seconds=240,
            max_restarts=1,
            order=0,
        ),
        WorkerSpec(
            name="tts",
            command=[TERA_PY, "scripts/teratts_server.py",
                     "--release-dir", TERA_RELEASE, "--voice", "ru_f1",
                     "--model", "distilled", "--threads", "24",
                     "--host", "127.0.0.1", "--port", "9889"],
            probe=probe(9889),
            startup_timeout_seconds=240,
            max_restarts=1,
            order=1,
        ),
    ]
    supervisor = RuntimeSupervisor(specs)
    report: dict = {"schema_version": 1, "profile": "supervisor-live-adr041-s2"}

    began = time.perf_counter()
    started = supervisor.start()
    report["start_seconds"] = round(time.perf_counter() - began, 1)
    report["start_ok"] = started.ok
    report["start_workers"] = started.workers
    print(f"start: ok={started.ok} in {report['start_seconds']}s", flush=True)
    for name, summary in started.workers.items():
        print(f"  {name}: pid={summary['pid']} healthy={summary['healthy']} restarts={summary['restarts_used']}", flush=True)
    if not started.ok:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 1

    health = supervisor.health()
    report["health_ok"] = health.ok

    # Real LLM turn through the supervised brain.
    payload = {
        "model": "bonsai2",
        "messages": [{"role": "user", "content": "Ответь одним словом: работает?"}],
        "max_tokens": 30,
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8990/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    llm_began = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    report["llm_seconds"] = round(time.perf_counter() - llm_began, 2)
    report["llm_reply"] = body["choices"][0]["message"]["content"][:120]
    print(f"llm turn: {report['llm_seconds']}s -> {report['llm_reply']!r}", flush=True)

    # Restart one worker: new pid, healthy again.
    before_pid = started.workers["tts"]["pid"]
    restart_began = time.perf_counter()
    restarted = supervisor.restart("tts")
    report["restart_seconds"] = round(time.perf_counter() - restart_began, 1)
    report["restart_ok"] = restarted.ok
    report["tts_pid_before"] = before_pid
    report["tts_pid_after"] = restarted.workers["tts"]["pid"]
    print(f"restart tts: ok={restarted.ok} in {report['restart_seconds']}s "
          f"({before_pid} -> {report['tts_pid_after']})", flush=True)

    stopped = supervisor.stop()
    report["stop_workers"] = stopped.workers
    report["status"] = "passed" if (
        started.ok and restarted.ok and report["llm_seconds"] < 10
        and not stopped.workers["brain"]["running"]
        and not stopped.workers["tts"]["running"]
    ) else "failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RESULT: {report['status']}", flush=True)
    print(f"report: {REPORT}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())