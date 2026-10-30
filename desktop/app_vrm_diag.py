"""Fetch the three-vrm module as text and try a static import with logging."""

import itertools
import json
import urllib.request

import websocket


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
                    return "EXC: " + str(details.get("exception", {}).get("description") or details.get("text"))[:400]
                return result.get("result", {}).get("value")

    # 1. what does the module's own import of 'three' resolve to?
    print("importmap present:", ev(
        "!!document.querySelector('script[type=importmap]')"))
    # 2. fetch the vrm module text and inspect its import statements
    print("vrm module first 200 chars:", ev(
        "(async()=>{const r = await fetch('/app/node_modules/@pixiv/three-vrm/lib/three-vrm.module.min.js'); const t = await r.text(); return t.slice(0,200);})()"))
    # 3. try importing with console capture
    print("import attempt with detail:", ev(
        "(async()=>{try {const m = await import('/app/node_modules/@pixiv/three-vrm/lib/three-vrm.module.min.js'); return 'OK ' + Object.keys(m).slice(0,8).join(',');} catch(e) {return 'ERR name=' + e.name + ' msg=' + e.message;}})()"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())