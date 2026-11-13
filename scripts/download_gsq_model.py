"""Download the GSQ-RCO quantized model, bypassing a broken proxy variable.

NO_PROXY contains "[::1]", and httpx parses the bracket form as a host:port pair,
raising InvalidURL("Invalid port: ':1]'"). Clearing the proxy variables for this
process only is safe: the download goes straight to huggingface.co.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

for name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
             "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy", "NODE_USE_ENV_PROXY"):
    os.environ.pop(name, None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime" / "jawl-daily-venv" / "Lib" / "site-packages"))

REPO = "lavendercomputing/SenseNova-Loop-9B-Preview-GSQ-RCO-GGUF"
FILES = [
    "quant/SenseNova-Loop-9B-Preview-GSQ-RCO-IQ3_M.gguf",
    "quant/SenseNova-Loop-9B-Preview-GSQ-RCO-IQ3_S.gguf",
]
TARGET = ROOT / "runtime" / "models" / "sensenova-gsq"


def main() -> int:
    from huggingface_hub import hf_hub_download

    TARGET.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        began = time.perf_counter()
        print(f"downloading {filename} ...", flush=True)
        try:
            path = hf_hub_download(
                repo_id=REPO, filename=filename, local_dir=str(TARGET),
            )
        except Exception as exc:  # noqa: BLE001 - report, do not crash the batch
            print(f"  FAILED: {type(exc).__name__}: {exc}", flush=True)
            continue
        size_gb = Path(path).stat().st_size / (1024 ** 3)
        print(f"  ok {path} ({size_gb:.2f} GB) in {time.perf_counter() - began:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())