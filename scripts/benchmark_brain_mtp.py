"""Benchmark MTP speculative decoding on the GSQ-RCO quants.

The GSQ-RCO GGUFs carry an MTP draft head at block 56 that the current
Q4_K_M file lacks. This harness starts llama-server with --spec-type
draft-mtp, runs one controlled prompt, and reports decode speed plus
the speculative acceptance telemetry, so it can be compared against
the non-speculative baseline of the same file.
"""

from __future__ import annotations

import argparse
import json
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


def run_case(label: str, model: Path, port: int, spec: list[str]) -> dict:
    cmd = [
        str(EXE), "--model", str(model), "--alias", label,
        "--host", "127.0.0.1", "--port", str(port),
        "--threads", "12", "--ctx-size", "4096", "--n-predict", str(N_PREDICT),
        "--parallel", "1", "--gpu-layers", "99",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--flash-attn", "on",
        "--reasoning", "off", "--no-webui", *spec,
    ]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_ready(port):
            return {"label": label, "error": "server did not become ready"}

        body = json.dumps({
            "prompt": PROMPT, "n_predict": N_PREDICT,
            "temperature": 0.0, "stream": False,
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
        accept = data.get("tokens_predicted") or {}
        result = {
            "label": label,
            "spec": " ".join(spec) or "none",
            "decode_tok_s": round(pn / (pm / 1000.0), 1) if pm else 0.0,
        }
        print(f"{label:22} {result['decode_tok_s']:6.1f} tok/s   spec: {result['spec'] or 'none'}")
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
    parser.add_argument("--model", required=True, help="path to the GSQ-RCO GGUF")
    parser.add_argument("--port", type=int, default=9101)
    args = parser.parse_args()

    model = (ROOT / args.model).resolve()
    if not model.exists():
        print(f"missing model: {model}")
        return 1

    print("=" * 88)
    print(f"  MTP speculative decoding: {model.name}")
    print("=" * 88)
    results = [
        run_case("baseline", model, args.port, []),
        run_case("mtp", model, args.port + 1, ["--spec-type", "draft-mtp"]),
    ]

    out = ROOT / "runtime" / "instances" / "brain_mtp_compare.json"
    out.write_text(json.dumps({"model": model.name, "results": results}, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())