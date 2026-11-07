"""Test llama-server launch with file redirection vs pipe."""

import subprocess
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
SERVER_BIN = ROOT / "runtime" / "bin" / "llama-server" / "llama-server.exe"
MODEL_PATH = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "Qwen3.5-0.8B-Q4_K_M.gguf"
MMPROJ_PATH = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "mmproj-F16.gguf"
LOG_PATH = ROOT / "runtime" / "instances" / "daily" / "data" / "sensory" / "youtube_watch" / "llama_test.log"

cmd = [
    str(SERVER_BIN),
    "-m", str(MODEL_PATH),
    "--mmproj", str(MMPROJ_PATH),
    "--host", "127.0.0.1",
    "--port", "8995",
    "-c", "4096",
    "-np", "1",
    "-ngl", "99",
    "-dev", "CUDA1",
    "-fa", "on",
    "--reasoning", "off",
    "--image-min-tokens", "1024",
]

with open(LOG_PATH, "w", encoding="utf-8") as f_log:
    p = subprocess.Popen(cmd, stdout=f_log, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        ready = False
        while time.time() - t0 < 30:
            try:
                r = requests.get("http://127.0.0.1:8995/health", timeout=1)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)
        print("Ready:", ready, "Elapsed:", round(time.time() - t0, 2), "s")
    finally:
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()
