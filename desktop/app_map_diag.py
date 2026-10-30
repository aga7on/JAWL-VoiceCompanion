"""Verify importmap resolution: does import('three') work on the app page?"""

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
                    return "EXC: " + str(details.get("exception", {}).get("description") or details.get("text"))[:300]
                return result.get("result", {}).get("value")

    # importmap on the page: what does it map?
    print("importmap json:", ev(
        "document.querySelector('script[type=importmap]')?.textContent"))
    # does bare 'three' resolve?
    print("import('three'):", ev(
        "(async()=>{try{const m = await import('three'); return 'OK ' + Object.keys(m).length;}catch(e){return 'ERR ' + e.message;}})()"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())