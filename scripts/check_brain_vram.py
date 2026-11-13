"""Check whether the model is actually resident in VRAM while serving.

A 5.2 GB Q4 model with -ngl 99 must occupy roughly that much VRAM. If the card
shows far less, the weights are not on the device and decode speed reflects CPU
work regardless of the flag. This probe starts a server, samples VRAM while it
serves, and reports the delta plus decode speed.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "runtime" / "sensenova-loop" / "build13" / "bin" / "llama-server.exe"


def vram_mb(gpu: int = 1) -> float:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
         "-i", str(gpu)],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return float(out.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0.0


def run(label: str, model: Path, gpu_layers: int, port: int) -> dict:
    before = vram_mb()
    cmd = [
        str(EXE), "--model", str(model), "--alias", label,
        "--host", "127.0.0.1", "--port", str(port),
        "--threads", "12", "--ctx-size", "4096", "--n-predict", "200",
        "--parallel", "1", "--gpu-layers", str(gpu_layers),
        "--reasoning", "off", "--no-webui",
    ]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(150):
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).status == 200:
                    break
            except Exception:  # noqa: BLE001 - startup polling
                time.sleep(2)
        loaded = vram_mb()
        body = json.dumps({
            "prompt": "Опиши по шагам, как работает вычислительная система.",
            "n_predict": 200, "temperature": 0.0, "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/completion", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=900) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        t = data.get("timings") or {}
        pn = int(t.get("predicted_n") or 0)
        pm = float(t.get("predicted_ms") or 0.0)
        tok_s = pn / (pm / 1000.0) if pm else 0.0
        delta = loaded - before
        print(f"{label:16} ngl={gpu_layers:3d}  VRAM +{delta:6.0f} MB  "
              f"({loaded:.0f} total)  decode={tok_s:6.1f} tok/s")
        return {"label": label, "ngl": gpu_layers, "vram_delta_mb": round(delta),
                "vram_total_mb": round(loaded), "decode_tok_s": round(tok_s, 1)}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(3)


def main() -> int:
    model = ROOT / "runtime" / "sensenova-loop" / "models" / \
        "SenseNova-Loop-9B-Preview-Q4_K_M-verified.gguf"
    print("=" * 88)
    print("  Is the model resident in VRAM?")
    print("=" * 88)
    print(f"baseline VRAM GPU1: {vram_mb():.0f} MB")
    print(f"model file: {model.stat().st_size / (1024**3):.2f} GB")
    print()
    results = [
        run("ngl=99", model, 99, 9011),
        run("ngl=0", model, 0, 9012),
    ]
    out = ROOT / "runtime" / "instances" / "brain_vram_check.json"
    out.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())