"""Test inference speed with image-min-tokens 1024."""

import base64
import json
import time
from pathlib import Path
import requests

FRAME_PATH = Path("runtime/instances/daily/data/sensory/youtube_watch/gt_frames_180s/frame_0019.jpg")

with open(FRAME_PATH, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

payload = {
    "model": "qwen3.5-0.8b",
    "messages": [
        {"role": "system", "content": "Опиши сцену строго в JSON: {\"characters\": [{\"bbox\": [ymin, xmin, ymax, xmax], \"appearance\": \"...\"}]}"},
        {"role": "user", "content": [
            {"type": "text", "text": "Найди персонажей и определи их bbox."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        ]}
    ],
    "max_tokens": 150,
    "temperature": 0.1,
}

t0 = time.perf_counter()
res = requests.post("http://127.0.0.1:8995/chat/completions", json=payload, timeout=30)
dt = (time.perf_counter() - t0) * 1000.0
print(f"Status: {res.status_code} in {dt:.1f}ms")
if res.status_code == 200:
    data = res.json()
    print("Content:", data["choices"][0]["message"]["content"])
    print("Usage:", data.get("usage"))
    print("Timings:", data.get("timings"))
