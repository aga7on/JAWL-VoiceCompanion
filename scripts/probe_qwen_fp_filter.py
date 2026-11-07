"""Test Qwen on SSDLite FP crop from frame 4."""

import base64
import json
import subprocess
import time
from pathlib import Path
from PIL import Image
import requests

ROOT = Path(__file__).resolve().parents[1]
SERVER_BIN = ROOT / "runtime" / "bin" / "llama-server" / "llama-server.exe"
MODEL_PATH = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "Qwen3.5-0.8B-Q4_K_M.gguf"
MMPROJ_PATH = ROOT / "runtime" / "vlm-cpu-bench" / "models" / "qwen3.5-0.8b" / "mmproj-F16.gguf"
FRAME_PATH = ROOT / "runtime" / "instances" / "daily" / "data" / "sensory" / "youtube_watch" / "gt_frames_180s" / "frame_0004.jpg"

PORT = 8994
URL = f"http://127.0.0.1:{PORT}"

# Crop the false positive bbox [0.255, 0.4758, 0.7214, 0.729]
img = Image.open(FRAME_PATH).convert("RGB")
w, h = img.size
bbox = [0.255, 0.4758, 0.7214, 0.729]
crop = img.crop((int(bbox[1] * w), int(bbox[0] * h), int(bbox[3] * w), int(bbox[2] * h)))
crop_path = ROOT / "runtime" / "instances" / "daily" / "data" / "sensory" / "youtube_watch" / "test_fp_crop.jpg"
crop.save(crop_path, quality=95)

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

    with open(crop_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    sys_prompt = (
        "Ты — верификатор детекций. Определи, есть ли на изображении реальный человек (персонаж).\n"
        "Если на изображении фон, мебель, предмет, надпись или декорация без человека, укажи is_person: false.\n"
        "Верни строго JSON:\n"
        '{"is_person": false, "reason": "текст или фон", "confidence": 0.95}'
    )

    payload = {
        "model": "qwen3.5-0.8b",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Есть ли человек на этом фрагменте? Верни JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ],
        "max_tokens": 100,
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
        with open("runtime/instances/daily/data/sensory/youtube_watch/qwen_fp_crop_test.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
