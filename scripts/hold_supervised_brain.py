"""Standalone supervised brain holder (ADR-041 stage 2).

Raises one llama-server worker (the local brain) through RuntimeSupervisor and
holds it alive until terminated. Used by the local-brain wrapper when the JAWL
agent must find a live endpoint at its FIRST heartbeat - the in-process
`--supervise-workers` path raises the brain only with the Companion entry,
which starts after the agent. The holder's Job Object
(KILL_ON_JOB_CLOSE) guarantees no orphan workers if this process dies.

Usage:
    python -X utf8 scripts/hold_supervised_brain.py --seconds N [--port 8990]
        [--llm-exe PATH] [--model PATH] [--alias NAME]

Prints `READY` once the worker answers /health, then serves the hold window
(default: until terminated). Exits non-zero if the worker fails its budget.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec  # noqa: E402

REPORT = ROOT / "runtime" / "supervised-brain-holder.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Hold a supervised local brain worker")
    parser.add_argument("--port", type=int, default=8990)
    parser.add_argument("--llm-exe", default=r"G:\AI\llamacpp-prism\build-fa\bin\llama-server.exe")
    parser.add_argument("--model", default=r"G:\AI\models\Ternary-Bonsai-2-27B-Abliterated-Hikari\Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf")
    parser.add_argument("--alias", default="local-bonsai2")
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--ctx-size", type=int, default=16384)
    parser.add_argument("--gpu-layers", default="99")
    parser.add_argument("--device", default="CUDA1")
    parser.add_argument("--seconds", type=float, default=0.0, help="0 = hold until terminated")
    parser.add_argument("--startup-timeout", type=float, default=240.0)
    args = parser.parse_args()

    def probe() -> bool:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=2) as response:
            return response.status == 200

    spec = WorkerSpec(
        name="brain",
        command=[args.llm_exe, "--model", args.model, "--alias", args.alias,
                 "--host", "127.0.0.1", "--port", str(args.port),
                 "--threads", str(args.threads), "--ctx-size", str(args.ctx_size),
                 "--parallel", "1", "--gpu-layers", args.gpu_layers, "--device", args.device],
        probe=probe,
        startup_timeout_seconds=args.startup_timeout,
        max_restarts=1,
        order=0,
    )
    supervisor = RuntimeSupervisor([spec])
    began = time.perf_counter()
    report = supervisor.start()
    if not report.ok:
        REPORT.write_text(json.dumps({"ok": False, "workers": report.workers},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"FAILED: {report.workers}", flush=True)
        return 2
    print(f"READY port={args.port} pid={report.workers['brain']['pid']} "
          f"startup={time.perf_counter() - began:.1f}s", flush=True)
    try:
        if args.seconds > 0:
            deadline = time.time() + args.seconds
            while time.time() < deadline:
                time.sleep(1.0)
                if not supervisor.health().ok:
                    print("BRAIN DIED", flush=True)
                    return 3
        else:
            while True:
                time.sleep(5.0)
                if not supervisor.health().ok:
                    print("BRAIN DIED", flush=True)
                    return 3
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())