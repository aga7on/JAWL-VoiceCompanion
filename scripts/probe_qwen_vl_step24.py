"""Quick probe for Qwen3.5-0.8B VL via llama-server."""

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


def main():
    print(f"Server binary: {SERVER_BIN.exists()}")
    print(f"Model path: {MODEL_PATH.exists()}")
    print(f"MMPROJ path: {MMPROJ_PATH.exists()}")
    print(f"Frame path: {FRAME_PATH.exists()}")

    cmd = [
        str(SERVER_BIN),
        "-m", str(MODEL_PATH),
        "--mmproj", str(MMPROJ_PATH),
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "-c", "2048",
        "-ngl", "0",
        "-t", "8",
        "-tb", "8",
        "--reasoning", "off",
    ]

    print("Launching llama-server on CUDA1...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    deadline = time.time() + 60
    healthy = False
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                _, err = proc.communicate()
                print("Server failed to start:", err.decode("utf-8", errors="replace"))
                return
            try:
                r = requests.get(f"{URL}/health", timeout=1)
                if r.status_code == 200:
                    healthy = True
                    break
            except Exception:
                time.sleep(0.5)

        if not healthy:
            print("Server did not become healthy in 60s")
            return

        print("Server is healthy! Preparing request with test frame...")
        with open(FRAME_PATH, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")

        system_prompt = (
            "Ты — визуальный анализатор сцены для когнитивного ядра SceneState.\n"
            "Проанализируй изображение. Определи видимых персонажей, их отличительные признаки (одежда, волосы, аксессуары, очки), "
            "предметы и действия. Не угадывай имена персонажей.\n"
            "Верни строго JSON следующего формата:\n"
            "{\n"
            '  "characters": [\n'
            "    {\n"
            '      "local_id": "c1",\n'
            '      "appearance": "парень в очках, темно-синяя форма",\n'
            '      "action": "стоит и слушает",\n'
            '      "confidence": 0.85\n'
            "    }\n"
            "  ],\n"
            '  "scene": "школьный класс",\n'
            '  "uncertain": []\n'
            "}"
        )

        user_content = [
            {"type": "text", "text": "Опиши сцену по формату JSON."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
        ]

        payload = {
            "model": "qwen3.5-0.8b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 160,
            "temperature": 0.1,
            "stream": False,
        }

        print("Sending visual prompt to Qwen3.5-0.8B...")
        t0 = time.perf_counter()
        resp = requests.post(f"{URL}/chat/completions", json=payload, timeout=60)
        dt = (time.perf_counter() - t0) * 1000.0

        print(f"\nResponse status: {resp.status_code} in {dt:.1f} ms")
        if resp.status_code == 200:
            data = resp.json()
            msg = data["choices"][0]["message"]
            out_file = ROOT / "runtime" / "instances" / "daily" / "data" / "sensory" / "youtube_watch" / "qwen_probe_sample.json"
            out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Content received (written to qwen_probe_sample.json):")
            print(msg.get("content", ""))
            usage = data.get("usage", {})
            print("\nUsage:", usage)
        else:
            print("Error:", resp.text)

    finally:
        print("\nStopping llama-server process...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        print("Cleaned up.")


if __name__ == "__main__":
    main()
