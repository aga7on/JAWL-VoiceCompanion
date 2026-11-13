"""Compare brain throughput across model files and runtime configurations.

Purpose: measure, not assume. Several candidate improvements exist at once
(newer llama.cpp, IQ3_S/IQ3_M quants with an MTP head). This harness runs the
same prompt against one or more servers and reports prefill and decode for each,
so the comparison is like-for-like.

Usage:
    python -X utf8 scripts/compare_brain_models.py \
        --model "label=path/to/a.gguf" --model "label2=path/to/b.gguf"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "runtime" / "sensenova-loop" / "build13" / "bin" / "llama-server.exe"
PROMPT = "Опиши по шагам, как работает вычислительная система."
N_PREDICT = 200


def wait_ready(port: int, timeout_s: float = 300.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001 - startup polling
            time.sleep(2)
    return False


def measure(label: str, model: Path, port: int, extra: list[str]) -> dict:
    cmd = [
        str(EXE), "--model", str(model), "--alias", label,
        "--host", "127.0.0.1", "--port", str(port),
        "--threads", "12", "--ctx-size", "4096", "--n-predict", str(N_PREDICT),
        "--parallel", "1", "--gpu-layers", "99",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--flash-attn", "on",
        "--reasoning", "off", "--no-webui", *extra,
    ]
    # Pin to one device: with two GPUs, llama.cpp splits layers across both
    # and the PCIe traffic dominates the measurement.
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = env.get("BRAIN_GPU", "1")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        if not wait_ready(port):
            return {"label": label, "error": "server did not become ready"}
        payload = json.dumps({
            "prompt": PROMPT, "n_predict": N_PREDICT,
            "temperature": 0.0, "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/completion", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        began = time.perf_counter()
        with urllib.request.urlopen(request, timeout=900) as response:
            data = json.loads(response.read().decode("utf-8"))
        wall = time.perf_counter() - began
        t = data.get("timings") or {}
        predicted_n = int(t.get("predicted_n") or 0)
        predicted_ms = float(t.get("predicted_ms") or 0.0)
        prompt_n = int(t.get("prompt_n") or 0)
        prompt_ms = float(t.get("prompt_ms") or 0.0)
        result = {
            "label": label,
            "model": model.name,
            "file_gb": round(model.stat().st_size / (1024 ** 3), 2),
            "decode_tok_s": round(predicted_n / (predicted_ms / 1000.0), 1) if predicted_ms else 0.0,
            "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
            "wall_s": round(wall, 2),
        }
        print(f"{label:17} {result['file_gb']:5.2f} GB  decode={result['decode_tok_s']:6.1f} tok/s  "
              f"prefill={result['prefill_tok_s']:7.1f} tok/s")
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True,
                        help="label=path/to/model.gguf (repeatable)")
    parser.add_argument("--extra", action="append", default=[],
                        help="extra llama-server argument (repeatable)")
    parser.add_argument("--report", default="runtime/instances/brain_model_compare.json")
    parser.add_argument("--port", type=int, default=8998)
    args = parser.parse_args()

    specs = []
    for item in args.model:
        label, _, path = item.partition("=")
        specs.append((label, (ROOT / path).resolve()))

    print("=" * 92)
    print("  Brain model comparison")
    print("=" * 92)
    results = []
    for index, (label, path) in enumerate(specs):
        if not path.exists():
            print(f"{label:17} MISSING {path}")
            continue
        results.append(measure(label, path, args.port + index, args.extra))

    out = ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())