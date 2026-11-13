"""Decide whether the GPU is actually doing the work.

Decode measured 36 tok/s while consuming 11.6 CPU cores. Two explanations remain:
the GPU is doing most of the work and CPU handles overhead, or the recurrent part
of this hybrid architecture falls back to CPU and dominates.

The test is a controlled comparison: the same prompt with all layers on GPU
(-ngl 99) versus none (-ngl 0). If the GPU run is not dramatically faster, the
GPU is not carrying the model.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "runtime" / "sensenova-loop" / "build13" / "bin" / "llama-server.exe"
MODEL = ROOT / "runtime" / "sensenova-loop" / "models" / "SenseNova-Loop-9B-Preview-Q4_K_M-verified.gguf"
PROMPT = "Опиши по шагам, как работает вычислительная система."
N_PREDICT = 200


def run_case(label: str, port: int, gpu_layers: int) -> dict:
    cmd = [
        str(EXE), "--model", str(MODEL), "--alias", f"probe{port}",
        "--host", "127.0.0.1", "--port", str(port),
        "--threads", "12", "--ctx-size", "4096", "--n-predict", str(N_PREDICT),
        "--parallel", "1", "--gpu-layers", str(gpu_layers),
        "--reasoning", "off", "--no-webui",
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        health = f"http://127.0.0.1:{port}/health"
        deadline = time.time() + 240
        ready = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health, timeout=2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:  # noqa: BLE001 - startup polling
                time.sleep(2)
        if not ready:
            return {"label": label, "error": "server did not become ready"}

        payload = json.dumps({
            "prompt": PROMPT, "n_predict": N_PREDICT,
            "temperature": 0.0, "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/completion", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            data = json.loads(response.read().decode("utf-8"))
        t = data.get("timings") or {}
        predicted_n = int(t.get("predicted_n") or 0)
        predicted_ms = float(t.get("predicted_ms") or 0.0)
        prompt_n = int(t.get("prompt_n") or 0)
        prompt_ms = float(t.get("prompt_ms") or 0.0)
        result = {
            "label": label,
            "gpu_layers": gpu_layers,
            "decode_tok_s": round(predicted_n / (predicted_ms / 1000.0), 1) if predicted_ms else 0.0,
            "prefill_tok_s": round(prompt_n / (prompt_ms / 1000.0), 1) if prompt_ms else 0.0,
        }
        print(f"{label:14} ngl={gpu_layers:3d}  decode={result['decode_tok_s']:6.1f} tok/s  "
              f"prefill={result['prefill_tok_s']:7.1f} tok/s")
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    print("=" * 78)
    print("  GPU vs CPU: is the GPU carrying the model?")
    print("=" * 78)
    results = []
    for label, port, ngl in (("gpu_all", 8996, 99), ("cpu_only", 8997, 0)):
        results.append(run_case(label, port, ngl))
        time.sleep(3)

    gpu = next((r for r in results if r.get("label") == "gpu_all"), {})
    cpu = next((r for r in results if r.get("label") == "cpu_only"), {})
    print()
    if gpu.get("decode_tok_s") and cpu.get("decode_tok_s"):
        speedup = gpu["decode_tok_s"] / cpu["decode_tok_s"]
        print(f"GPU speedup over pure CPU: {speedup:.2f}x")
        if speedup < 1.6:
            print("  VERDICT: GPU barely helps. The model is running mostly on CPU;")
            print("           the recurrent layers of this hybrid architecture are")
            print("           not offloaded, so --gpu-layers 99 is misleading.")
        elif speedup < 3.0:
            print("  VERDICT: partial offload. GPU handles part, CPU still dominates.")
        else:
            print("  VERDICT: GPU is doing the real work; CPU time is overhead.")

    out = ROOT / "runtime" / "instances" / "brain_gpu_vs_cpu.json"
    out.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())