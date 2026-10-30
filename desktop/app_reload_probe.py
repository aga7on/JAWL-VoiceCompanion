"""Reload the app page and capture load errors (module/script failures)."""

import itertools
import json
import time
import urllib.request

import websocket


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=30)
    counter = itertools.count(1)

    def send(method, params=None):
        ws.send(json.dumps({"id": next(counter), "method": method, "params": params or {}}))

    def ev(expr, timeout=30):
        ws.settimeout(timeout)
        i = next(counter)
        ws.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == i:
                return message.get("result", {}).get("result", {})

    send("Runtime.enable")
    send("Page.enable")
    time.sleep(1)
    # Collect console errors through the event stream after reload.
    errors = []
    send("Page.reload")
    deadline = time.time() + 10
    ws.settimeout(2)
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message.get("method") == "Runtime.consoleAPICalled":
            args = message["params"].get("args", [])
            text = " ".join(str(a.get("value", "")) for a in args)
            if message["params"].get("type") in ("error", "warning"):
                errors.append(f'{message["params"]["type"]}: {text[:200]}')
        if message.get("method") == "Runtime.exceptionThrown":
            detail = message["params"]["exceptionDetails"]
            errors.append(f'exception: {str(detail.get("text", ""))[:200]} {str(detail.get("exception", {}).get("description", ""))[:200]}')

    print("=== errors/warnings during load ===")
    for line in errors[:12]:
        print(line)
    if not errors:
        print("(none)")
    print("scene:", ev("window.__jawlScene ? 1 : 0").get("value"))
    print("status:", ev("document.getElementById('avatar-status')?.textContent").get("value"))
    print("app.js loaded:", ev("typeof API !== 'undefined' || document.querySelector('#conn-status')?.textContent").get("value"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())