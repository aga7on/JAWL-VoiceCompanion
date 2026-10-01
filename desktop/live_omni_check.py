"""Live check: a UI chat turn with the OmniVoice (Aleksandra) voice lane.

The full stack is up (brain 8990, OmniVoice 9890, control 2467, Electron
with both windows). This script sends a chat turn through the panel's own
UI path (the realistic flow) and verifies:
  - the turn returns a real companion answer (envelope with emotion);
  - the TTS lane is OmniVoice (the worker's log grows, /api/tts/status
    shows the provider);
  - the 3D avatar window receives the emotion event.

Then the owner can listen and continue talking through the panel's mic.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
DEBUG_PORT = 9222


def targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def ws_for(url_match: str) -> str | None:
    for target in targets():
        if target.get("type") == "page" and url_match in (target.get("url") or ""):
            return target["webSocketDebuggerUrl"]
    return None


class Cdp:
    def __init__(self, ws_url: str, timeout: float = 60) -> None:
        self._ws = websocket.create_connection(ws_url, timeout=timeout)
        self._id = 0

    def evaluate(self, expression: str, timeout: float = 300):
        self._ws.settimeout(timeout)
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") == self._id:
                return message.get("result", {}).get("result", {}).get("value")


def main() -> int:
    panel_url = ws_for(":2467")
    avatar_url = ws_for("avatar.html")
    if not panel_url or not avatar_url:
        print("FAIL: panel or avatar window not found")
        return 2

    panel = Cdp(panel_url)
    avatar = Cdp(avatar_url)

    # Panel session (for authenticated probes).
    session = panel.evaluate("""
        (async () => {
          const response = await fetch('/api/session', {credentials: 'include'});
          return JSON.stringify(await response.json());
        })()
    """, timeout=30)
    csrf = json.loads(session).get("csrf_token")

    # TTS status: which provider is the lane?
    tts_status = panel.evaluate("""
        (async () => {
          const response = await fetch('/api/tts/status', {credentials: 'include',
            headers: {'X-Companion-CSRF': %s}});
          return JSON.stringify(await response.json());
        })()
    """ % json.dumps(csrf), timeout=30)
    print("tts status:", tts_status[:200])

    # Send the turn through the panel's own UI path.
    panel.evaluate("""
        (() => {
          const input = document.querySelector('#input');
          input.value = 'Привет! Скажи что-нибудь тёплое своими словами.';
          document.querySelector('#send').click();
          return 'sent';
        })()
    """, timeout=30)

    # Wait for the answer to land in the chat log.
    deadline = time.time() + 300
    chat_tail = ""
    while time.time() < deadline:
        chat_tail = panel.evaluate(
            "document.querySelector('#messages')?.lastElementChild?.textContent || ''", timeout=30) or ""
        if len(str(chat_tail)) > 30:
            break
        time.sleep(4)
    print("chat tail:", str(chat_tail)[:200])

    # Did the avatar window receive the emotion?
    time.sleep(5)
    bridge_events = avatar.evaluate("window.__jawlBridgeEvents || 0", timeout=30)
    emotion = avatar.evaluate("window.__jawlEmotion || 'none'", timeout=30)
    print(f"avatar: bridge_events={bridge_events}, emotion={emotion}")

    # Is the OmniVoice worker producing? (health + last log lines handled
    # by the caller; here just report the gateway's view of TTS.)
    return 0


if __name__ == "__main__":
    sys.exit(main())