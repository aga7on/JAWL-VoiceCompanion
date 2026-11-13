"""Check whether part of the hybrid model runs on CPU during decode.

The brain is hybrid: 56 blocks, full attention only every 4th, the rest recurrent.
llama.cpp keeps some recurrent work on CPU. If decode is CPU-bound here, GPU
tuning cannot fix the throughput, and that is the real answer to "why 30 tok/s".

CPU time is read from psutil for the server process, which is exact and needs no
shell quoting.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"


def find_server() -> psutil.Process | None:
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (proc.info["name"] or "").lower() != "llama-server.exe":
                continue
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "8990" in cmdline:
                return psutil.Process(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def cpu_seconds(proc: psutil.Process) -> float:
    total = 0.0
    try:
        times = proc.cpu_times()
        total += times.user + times.system
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0
    try:
        for child in proc.children(recursive=True):
            try:
                ct = child.cpu_times()
                total += ct.user + ct.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return total


def main() -> int:
    proc = find_server()
    if proc is None:
        print("llama-server on 8990 not found")
        return 2
    print(f"brain pid: {proc.pid}")

    rss_mb = proc.memory_info().rss / (1024 * 1024)
    before = cpu_seconds(proc)
    print(f"cpu before: {before:.1f}s, RSS {rss_mb:.0f} MB")

    payload = json.dumps({
        "prompt": "Опиши по шагам, как работает вычислительная система.",
        "n_predict": 800,
        "temperature": 0.0,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{BRAIN}/completion", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    began = time.perf_counter()
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.loads(response.read().decode("utf-8"))
    wall = time.perf_counter() - began

    after = cpu_seconds(proc)
    timings = data.get("timings") or {}
    predicted_n = int(timings.get("predicted_n") or 0)
    predicted_ms = float(timings.get("predicted_ms") or 0.0)
    prompt_n = int(timings.get("prompt_n") or 0)
    prompt_ms = float(timings.get("prompt_ms") or 0.0)
    tok_s = predicted_n / (predicted_ms / 1000.0) if predicted_ms else 0.0
    prefill_s = prompt_n / (prompt_ms / 1000.0) if prompt_ms else 0.0

    cpu_delta = after - before
    cores = cpu_delta / wall if wall else 0.0

    print()
    print(f"decode : {predicted_n} tok in {predicted_ms/1000:.2f}s = {tok_s:.1f} tok/s")
    print(f"prefill: {prompt_n} tok at {prefill_s:.0f} tok/s")
    print(f"wall   : {wall:.2f}s")
    print(f"CPU time consumed: {cpu_delta:.1f}s  ->  {cores:.2f} cores busy on average")
    print()
    if cores >= 3.0:
        verdict = "CPU-BOUND: a large part of the graph runs on CPU, not GPU"
    elif cores >= 1.2:
        verdict = "MIXED: substantial CPU work alongside the GPU"
    else:
        verdict = "GPU-BOUND: CPU only orchestrates"
    print("VERDICT:", verdict)

    out = ROOT / "runtime" / "instances" / "brain_cpu_during_decode.json"
    out.write_text(json.dumps({
        "pid": proc.pid,
        "tok_s": round(tok_s, 1),
        "prefill_tok_s": round(prefill_s, 1),
        "wall_s": round(wall, 2),
        "cpu_seconds": round(cpu_delta, 2),
        "average_cores_busy": round(cores, 2),
        "verdict": verdict,
    }, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())