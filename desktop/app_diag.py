"""Deep diagnosis of the app page: why does the scene never finish loading?"""

import itertools
import json
import time
import urllib.request

import websocket


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=60)
    counter = itertools.count(1)

    def ev(expr, timeout=45):
        ws.settimeout(timeout)
        i = next(counter)
        ws.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == i:
                return message.get("result", {}).get("result", {}).get("value")

    print("1. csrf:", ev("window.__jcsrf ? 'set' : 'null'"))
    print("2. jawlScene type:", ev("typeof window.__jawlScene"))
    print("3. module script tag:", ev(
        "Array.from(document.scripts).filter(s=>s.type==='module').map(s=>s.src).join(',')"))
    print("4. fetch wardrobe from page:", ev(
        "(async()=>{const r = await fetch('/api/avatar/wardrobe',{credentials:'include',headers:{'X-Companion-CSRF':window.__jcsrf||''}}); return r.status + ' ' + (await r.text()).slice(0,120);})()"))
    print("5. fetch model head:", ev(
        "(async()=>{const r = await fetch('/api/avatar/model/VRM1_Constraint_Twist_Sample.vrm',{credentials:'include',headers:{'X-Companion-CSRF':window.__jcsrf||''}}); return r.status + ' type=' + r.headers.get('content-type') + ' len=' + r.headers.get('content-length');})()"))
    print("6. three module fetch:", ev(
        "(async()=>{const r = await fetch('/app/node_modules/three/build/three.module.js'); return r.status + ' len=' + r.headers.get('content-length');})()"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())