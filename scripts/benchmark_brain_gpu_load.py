"""Sample GPU clocks and power while the brain is decoding.

Idle sampling is misleading: the card sits in P8 at 405 MHz. A throughput
problem can be a clock/power problem rather than a kernel problem, so this
probe records what the GPU actually does under sustained decode load.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = "http://127.0.0.1:8990"
QUERY = (
    "index,pstate,clocks.current.memory,clocks.current.sm,"
    "power.draw,power.limit,utilization.gpu,temperature.gpu"
)


def sample() -> list[dict]:
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    rows = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        try:
            rows.append({
                "index": int(parts[0]),
                "pstate": parts[1],
                "mem_mhz": float(parts[2]),
                "sm_mhz": float(parts[3]),
                "power_w": float(parts[4]),
                "limit_w": float(parts[5]),
                "util_pct": float(parts[6]),
                "temp_c": float(parts[7]),
            })
        except ValueError:
            continue
    return rows


def main() -> int:
    samples: list[list[dict]] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            try:
                samples.append(sample())
            except Exception:  # noqa: BLE001 - diagnostics
                pass
            time.sleep(0.5)

    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()

    print("idle baseline:")
    for row in sample():
        print(f"  GPU{row['index']} {row['pstate']} sm={row['sm_mhz']:.0f}MHz "
              f"mem={row['mem_mhz']:.0f}MHz power={row['power_w']:.0f}W")

    print()
    print("starting sustained decode (n=600)...")
    payload = json.dumps({
        "prompt": "Опиши подробно и по шагам, что делает вычислительная система.",
        "n_predict": 600,
        "temperature": 0.0,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{BRAIN}/completion",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    began = time.perf_counter()
    with urllib.request.urlopen(request, timeout=900) as response:
        data = json.loads(response.read().decode("utf-8"))
    wall = time.perf_counter() - began
    stop.set()
    thread.join(timeout=2)

    timings = data.get("timings") or {}
    predicted_n = int(timings.get("predicted_n") or 0)
    predicted_ms = float(timings.get("predicted_ms") or 0.0)
    tok_s = predicted_n / (predicted_ms / 1000.0) if predicted_ms else 0.0
    print(f"decode: {predicted_n} tokens in {predicted_ms/1000:.2f}s = {tok_s:.1f} tok/s")
    print()

    for index in (0, 1):
        rows = [s[index] for s in samples if len(s) > index]
        if not rows:
            continue
        mem = [r["mem_mhz"] for r in rows]
        sm = [r["sm_mhz"] for r in rows]
        power = [r["power_w"] for r in rows]
        util = [r["util_pct"] for r in rows]
        states = sorted({r["pstate"] for r in rows})
        print(f"GPU{index} under load: pstate={states} "
              f"sm={min(sm):.0f}-{max(sm):.0f}MHz mem={min(mem):.0f}-{max(mem):.0f}MHz")
        print(f"         power={min(power):.0f}-{max(power):.0f}W "
              f"util={min(util):.0f}-{max(util):.0f}%")

    out = ROOT / "runtime" / "instances" / "brain_gpu_load.json"
    out.write_text(json.dumps({"tok_s": tok_s, "samples": samples[-40:]}, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())