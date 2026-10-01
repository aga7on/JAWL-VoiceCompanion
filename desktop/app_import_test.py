"""Try importing the scene modules directly on the app page."""

import itertools
import json
import urllib.request

import websocket

MODULES = [
    "/app/node_modules/three/build/three.module.js",
    "/app/node_modules/@pixiv/three-vrm/lib/three-vrm.module.min.js",
    "/app-scene.js",
]


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=90)
    counter = itertools.count(1)

    def ev(expr, timeout=60):
        ws.settimeout(timeout)
        i = next(counter)
        ws.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == i:
                result = message.get("result", {})
                details = result.get("exceptionDetails")
                if details:
                    return "EXC: " + str(details.get("exception", {}).get("description") or details.get("text"))[:220]
                return result.get("result", {}).get("value")

    for module in MODULES:
        expression = (
            "import(%r).then(m => 'ok ' + Object.keys(m).length + ' exports')"
            ".catch(e => 'ERR ' + String(e).slice(0, 180))"
        ) % module
        print(f"{module}:", ev(expression))
    print("jawlScene after import:", ev("typeof window.__jawlScene"))
    print("status:", ev("document.getElementById('avatar-status')?.textContent"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())