"""CDP probe for the single-window app: scene state, errors, wardrobe."""

import json
import sys
import urllib.request

import websocket


def targets():
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    ws_url = None
    for target in targets():
        if "/app" in (target.get("url") or ""):
            ws_url = target["webSocketDebuggerUrl"]
            break
    if not ws_url:
        print("APP WINDOW NOT FOUND")
        return 2
    ws = websocket.create_connection(ws_url, timeout=30)
    counter = [0]

    def evaluate(expression, timeout=30):
        ws.settimeout(timeout)
        counter[0] += 1
        ws.send(json.dumps({"id": counter[0], "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == counter[0]:
                result = message.get("result", {}).get("result", {})
                return result.get("value")

    scene = evaluate("window.__jawlScene ? {emotion: window.__jawlScene.currentEmotion, worn: window.__jawlScene.wornModel} : null")
    print("scene:", json.dumps(scene, ensure_ascii=False))
    status = evaluate("document.getElementById('avatar-status')?.textContent")
    print("avatar status:", status)
    canvas_ok = evaluate("!!document.getElementById('avatar-canvas') && document.getElementById('avatar-canvas').width > 0")
    print("canvas live:", canvas_ok)
    wardrobe = evaluate("document.getElementById('wardrobe-grid')?.children?.length")
    print("wardrobe tiles:", wardrobe)
    chat = evaluate("!!document.getElementById('chat-log') && !!document.querySelector('#chat-send')")
    print("chat composer:", chat)
    settings = evaluate("document.getElementById('settings-list')?.children?.length")
    print("settings rows:", settings)
    errors = evaluate("(window.__appErrors || []).join('; ').slice(0, 300)")
    print("errors:", errors or "none")
    title = evaluate("document.title")
    print("title:", title)
    return 0


if __name__ == "__main__":
    sys.exit(main())