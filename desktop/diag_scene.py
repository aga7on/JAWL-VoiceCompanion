"""Check which avatar-scene.js version the renderer actually runs."""

import json
import subprocess
import time
import urllib.request

import websocket


def main():
    process = subprocess.Popen(
        ["node_modules\\.bin\\electron.cmd", ".", "--remote-debugging-port"],
        cwd=".", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(12)
    try:
        url = None
        deadline = time.time() + 20
        while time.time() < deadline and url is None:
            try:
                with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                url = next((target["webSocketDebuggerUrl"] for target in targets
                            if "аватар" in (target.get("title") or "").lower()), None)
            except Exception:
                pass
            if url is None:
                time.sleep(1)
        if url is None:
            print("avatar target not found; targets:")
            for target in targets:
                print(" ", target.get("type"), target.get("title"))
            return
        ws = websocket.create_connection(url, timeout=15)

        def evaluate(expression):
            ws.send(json.dumps({"id": evaluate.n, "method": "Runtime.evaluate",
                                "params": {"expression": expression, "returnByValue": True}}))
            while True:
                message = json.loads(ws.recv())
                if message.get("id") == evaluate.n:
                    evaluate.n += 1
                    return message.get("result", {}).get("result", {}).get("value")

        evaluate.n = 1
        for delay in (2, 5, 10):
            time.sleep(delay)
            print(f"[{delay}s] version:", evaluate("window.__jawlSceneVersion"))
            print(f"[{delay}s] framing:", evaluate("window.__jawlFraming"))
            print(f"[{delay}s] head:", evaluate("window.__jawlHeadProbe"))
        print("module src:", evaluate("document.querySelector('script[type=module]')?.src"))
        print("contexts:", evaluate("typeof window.__jawlSceneVersion"))
        ws.close()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()