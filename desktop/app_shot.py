"""Screenshot the single-window app for the vision check."""

import base64
import json
import urllib.request

import websocket


def main() -> int:
    targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5).read().decode())
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if "/app" in (t.get("url") or ""))
    ws = websocket.create_connection(ws_url, timeout=60)
    ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == 1:
            png = base64.b64decode(message["result"]["data"])
            out = r"G:\AI\JAWL-VoiceCompanion\runtime\browser-evidence\desktop-app.png"
            with open(out, "wb") as handle:
                handle.write(png)
            print(f"saved: {out} ({len(png)} bytes)")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())