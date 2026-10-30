"""Submit the Qwen-Image-2.1 concept workflow to ComfyUI and wait for output.

Usage: python -X utf8 run_concept.py [prompt-text-file] [seed]
Writes generated PNGs info to stdout; files land in ComfyUI output dir.
"""

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

COMFY = "http://127.0.0.1:8189"
WORKFLOW = Path(__file__).parent / "concept_workflow.json"
OUTPUT = Path(r"G:\AI\JAWL-VoiceCompanion\runtime\browser-evidence")


def post(path: str, payload: dict):
    req = urllib.request.Request(
        COMFY + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    prompt = None
    seed = 42
    if len(sys.argv) > 1:
        prompt = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    if len(sys.argv) > 2:
        seed = int(sys.argv[2])

    graph = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    if prompt:
        graph["6"]["inputs"]["text"] = prompt
    graph["3"]["inputs"]["seed"] = seed

    client_id = str(uuid.uuid4())
    result = post("/prompt", {"prompt": graph, "client_id": client_id})
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        print("SUBMIT_FAIL:", json.dumps(result)[:400])
        return 1
    print("submitted:", prompt_id)

    # poll history for completion
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(4)
        with urllib.request.urlopen(f"{COMFY}/history/{prompt_id}", timeout=15) as response:
            history = json.loads(response.read().decode("utf-8"))
        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            status = history[prompt_id].get("status", {})
            print("status:", json.dumps(status)[:200])
            for node_id, node_out in outputs.items():
                for image in node_out.get("images", []):
                    sub = image.get("subfolder", "")
                    name = image.get("filename")
                    view = image.get("type", "output")
                    url = f"{COMFY}/view?filename={name}&subfolder={sub}&type={view}"
                    with urllib.request.urlopen(url, timeout=60) as img:
                        data = img.read()
                    dest = OUTPUT / f"qwen21_{seed}_{name}"
                    dest.write_bytes(data)
                    print("saved:", dest, len(data), "bytes")
            return 0
    print("TIMEOUT waiting for generation")
    return 2


if __name__ == "__main__":
    sys.exit(main())
