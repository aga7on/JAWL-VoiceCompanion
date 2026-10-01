"""Capture the browser console + network for the failing vrm import."""

import itertools
import json
import time
import urllib.request

import websocket


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=90)
    counter = itertools.count(1)

    def send(method, params=None):
        ws.send(json.dumps({"id": next(counter), "method": method, "params": params or {}}))

    def ev(expr, timeout=60):
        ws.settimeout(timeout)
        i = next(counter)
        ws.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == i:
                return message.get("result", {}).get("result", {}).get("value")

    send("Network.enable")
    send("Runtime.enable")
    time.sleep(0.5)
    # trigger the import and collect events
    send("Runtime.evaluate", {
        "expression": "import('/app/node_modules/@pixiv/three-vrm/lib/three-vrm.module.min.js').catch(e => console.error('IMPORTFAIL', e))",
        "awaitPromise": False})
    deadline = time.time() + 8
    ws.settimeout(2)
    events = []
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        method = message.get("method", "")
        params = message.get("params", {})
        if method == "Network.loadingFailed":
            events.append(f"loadingFailed: {params.get('errorText')} blocked={params.get('blockedReason')} type={params.get('type')}")
        if method == "Network.responseReceived":
            url = params.get("response", {}).get("url", "")
            if "node_modules" in url or "app-scene" in url:
                events.append(f"response: {url[-70:]} status={params.get('response', {}).get('status')} mime={params.get('response', {}).get('mimeType')}")
        if method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            text = " ".join(str(a.get("value", "")) for a in params.get("args", []))
            events.append(f"console.error: {text[:250]}")
    for line in events[:15]:
        print(line)
    if not events:
        print("(no events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())