"""Test Qwen3.5-0.8B bounding box generation on frame 19."""

import base64
import json
import subprocess
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
SERVER_BIN = ROOT / "runtime" / "bin" / "llama-server" / "llama-server.exe"
MODEL_PATH = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "Qwen3.5-0.8B-Q4_K_M.gguf"
MMPROJ_PATH = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "mmproj-F16.gguf"
FRAME_PATH = ROOT / "runtime" / "instances" / "daily" / "data" / "sensory" / "youtube_watch" / "gt_frames_180s" / "frame_0019.jpg"

PORT = 8994
URL = f"http://127.0.0.1:{PORT}"

cmd = [
    str(SERVER_BIN),
    "-m", str(MODEL_PATH),
    "--mmproj", str(MMPROJ_PATH),
    "--host", "127.0.0.1",
    "--port", str(PORT),
    "-c", "2048",
    "-ngl", "99",
    "-dev", "CUDA1",
    "-fa", "on",
    "--reasoning", "off",
]

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if requests.get(f"{URL}/health", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)

    with open(FRAME_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    # Prompt testing bounding box output
    sys_prompt = (
        "Ты — визуальный анализатор и детектор. Найди всех видимых людей на изображении.\n"
        "Для каждого человека укажи bounding box в нормализованных координатах [ymin, xmin, ymax, xmax] от 0.0 до 1.0, "
        "краткое описание внешности, действие и оценку уверенности (0.0-1.0).\n"
        "Верни строго JSON:\n"
        "{\n"
        '  "characters": [\n'
        "    {\n"
        '      "local_id": "c1",\n'
        '      "bbox": [0.12, 0.32, 0.88, 0.68],\n'
        '      "appearance": "девушка со светлыми волосами, школьная форма",\n'
        '      "action": "стоит и говорит",\n'
        '      "confidence": 0.90\n'
        "    }\n"
        "  ],\n"
        '  "scene": "описание сцены"\n'
        "}"
    )

    payload = {
        "model": "qwen3.5-0.8b",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Найди людей и определи их bbox [ymin, xmin, ymax, xmax] и описание. Верни строго JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ],
        "max_tokens": 200,
        "temperature": 0.1,
    }

    t0 = time.perf_counter()
    resp = requests.post(f"{URL}/chat/completions", json=payload, timeout=30)
    dt = (time.perf_counter() - t0) * 1000.0

    print(f"Status: {resp.status_code} in {dt:.1f}ms")
    if resp.status_code == 200:
        data = resp.json()
        print("Raw response:")
        print(data["choices"][0]["message"]["content"])
        with open("runtime/instances/daily/data/sensory/youtube_watch/qwen_bbox_test.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
