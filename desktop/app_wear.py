"""Wear AvatarSample_A in the live app window."""

import itertools
import json
import sys
import urllib.request

import websocket


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=180)
    counter = itertools.count(1)

    def ev(expr, timeout=120):
        ws.settimeout(timeout)
        i = next(counter)
        ws.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == i:
                return message.get("result", {}).get("result", {})

    result = ev(
        "window.__jawlScene.wear('AvatarSample_A').then(() => window.__jawlScene.wornModel)")
    print("worn:", result.get("value"))
    status = ev("document.getElementById('avatar-status')?.textContent")
    print("status:", status.get("value"))
    return 0


if __name__ == "__main__":
    sys.exit(main())