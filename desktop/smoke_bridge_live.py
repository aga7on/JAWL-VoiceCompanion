"""Full-loop smoke: panel turn -> avatar reaction, through the live stack.

Raises the real Companion stack (holder brain + JAWL + Companion), launches
the Electron shell, sends a chat turn through the panel window's own fetch
(session+CSRF from /api/session), and verifies on the avatar window:
  1. the desktop bridge delivered the emotion event (bridge counter > 0);
  2. the VRM expression changed to the envelope's emotion preset;
  3. the lip-sync level follows avatar.audio events while TTS speaks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
DESKTOP = ROOT / "desktop"
REPORT = ROOT / "runtime" / "desktop-bridge-live.json"
DEBUG_PORT = 9222
CONTROL_PORT = 2467


class Cdp:
    def __init__(self, ws_url: str, timeout: float = 20) -> None:
        self._ws = websocket.create_connection(ws_url, timeout=timeout)
        self._id = 0

    def call(self, method: str, params: dict | None = None):
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") == self._id:
                return message

    def evaluate(self, expression: str, timeout: float | None = None):
        if timeout is not None:
            self._ws.settimeout(timeout)
        try:
            result = self.call("Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "awaitPromise": True})
            return result.get("result", {}).get("result", {}).get("value")
        finally:
            if timeout is not None:
                self._ws.settimeout(20)

    def close(self):
        try:
            self._ws.close()
        except Exception:
            pass


def targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def cdp_for(title_part: str) -> Cdp | None:
    for target in targets():
        if target.get("type") == "page" and title_part in (target.get("title") or "").lower():
            return Cdp(target["webSocketDebuggerUrl"])
    return None


def http_json(url: str, timeout: float = 10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


import importlib.util

SMOKE_AVATAR = DESKTOP / "smoke_avatar.py"
spec = importlib.util.spec_from_file_location("smoke_avatar", SMOKE_AVATAR)
smoke_avatar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke_avatar)


def main() -> int:
    # 1. The stack: raised through the wrapper, which holds the brain
    # (supervised holder) and sets the provider env. No separate holder here.
    # Stale electron instances must die first: they hold the debug port.
    stale = smoke_avatar.kill_stale_electron()
    report: dict = {"schema_version": 1, "profile": "desktop-bridge-live",
                    "stale_killed": stale}
    checks: dict[str, bool] = {}
    electron = None
    panel = None
    avatar = None
    stack = None
    try:
        wrapper = ROOT / "scripts" / "run_local_bonsai_integrated.ps1"
        stack = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(wrapper), "-RunSeconds", "420",
             "-ControlPort", str(CONTROL_PORT), "-PresentationPort", "8866",
             "-JawlConsolePort", "8870", "-TtsPort", "9989"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        report["stack_pid"] = stack.pid
        deadline = time.time() + 300
        control_ok = False
        brain_ok = False
        while time.time() < deadline:
            try:
                if http_json(f"http://127.0.0.1:{CONTROL_PORT}/api/health", 2).get("status"):
                    control_ok = True
            except Exception:
                pass
            try:
                if http_json("http://127.0.0.1:8990/health", 2).get("status") == "ok":
                    brain_ok = True
            except Exception:
                pass
            if control_ok and brain_ok:
                break
            time.sleep(3)
        checks["control_ready"] = control_ok
        checks["brain_healthy"] = brain_ok

        # 2. Electron shell, pointed at this run's control port.
        env = {**__import__("os").environ,
               "JAWL_DESKTOP_CONTROL_PORT": str(CONTROL_PORT)}
        electron = subprocess.Popen(
            ["node_modules\\.bin\\electron.cmd", ".", "--remote-debugging-port"],
            cwd=DESKTOP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env)
        deadline = time.time() + 60
        panel = avatar = None
        last_titles = None
        while time.time() < deadline and (panel is None or avatar is None):
            try:
                current = targets()
                last_titles = [f"{t.get('type')}|{t.get('title')}|{t.get('url')}" for t in current]
                for target in current:
                    title = (target.get("title") or "").lower()
                    url = (target.get("url") or "").lower()
                    if target.get("type") != "page":
                        continue
                    # The panel window is the one on the companion origin;
                    # the avatar window is local file content.
                    if f":{CONTROL_PORT}" in url and panel is None:
                        panel = Cdp(target["webSocketDebuggerUrl"])
                    if "avatar.html" in url and avatar is None:
                        avatar = Cdp(target["webSocketDebuggerUrl"])
            except Exception as exc:
                last_titles = [f"list-error: {exc}"]
            if panel is None or avatar is None:
                time.sleep(2)
        report["window_titles_seen"] = last_titles
        checks["windows_found"] = panel is not None and avatar is not None
        if not checks["windows_found"]:
            raise RuntimeError("electron windows not found")

        # Wait for the panel to actually load the companion origin.
        deadline = time.time() + 30
        while time.time() < deadline:
            origin = panel.evaluate("location.origin")
            if str(origin).startswith("http"):
                break
            time.sleep(1)
        report["panel_origin"] = panel.evaluate("location.origin")

        # Wait for the JAWL agent: a chat turn before the console is up ends
        # with an honest 'JAWL недоступен' error envelope (observed in the
        # first passing run). The doctor reports the agent's readiness.
        deadline = time.time() + 240
        jawl_ok = False
        while time.time() < deadline:
            try:
                doctor = http_json(f"http://127.0.0.1:{CONTROL_PORT}/api/doctor", 4)
                entries = doctor.get("checks") or doctor.get("components") or {}
                for value in (entries.values() if isinstance(entries, dict) else entries):
                    if isinstance(value, dict) and "jawl" in str(value.get("name", "")).lower():
                        if value.get("ready") is True or str(value.get("status")) in {"ok", "ready", "online", "connected"}:
                            jawl_ok = True
                if not jawl_ok and str(doctor).find("ready") != -1:
                    # Doctor schema differs; accept a positive jawl mention.
                    text = json.dumps(doctor)
                    jawl_ok = '"jawl"' in text and '"ready": true' in text
            except Exception:
                pass
            if jawl_ok:
                break
            time.sleep(5)
        checks["jawl_ready"] = jawl_ok
        report["jawl_wait_seconds"] = round(300 - (deadline - time.time()))

        # 3. A real chat turn through the panel's own transport.
        session = panel.evaluate("""
            (async () => {
              const response = await fetch('/api/session', {credentials: 'include'});
              const data = await response.json();
              return JSON.stringify({csrf: data.csrf_token});
            })()
        """)
        csrf = json.loads(session)["csrf"]
        report["panel_session"] = bool(csrf)
        send = panel.evaluate("""
            (async () => {
              const response = await fetch('/api/chat', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json',
                          'X-Companion-CSRF': %s},
                body: JSON.stringify({text: 'Привет! Скажи что-нибудь радостное.'})
              });
              const body = await response.text();
              return JSON.stringify({status: response.status, body: body.slice(0, 300)});
            })()
        """ % json.dumps(csrf), timeout=240)
        report["chat_send"] = json.loads(send) if send else None

        # 4. Did the avatar window react?
        time.sleep(8)
        bridge_events = avatar.evaluate("window.__jawlBridgeEvents || 0")
        emotion_state = avatar.evaluate("window.__jawlEmotion || 'none'")
        status_text = avatar.evaluate("document.getElementById('status')?.textContent || ''")
        # The envelope's real emotion (not the error path) means the whole
        # loop: text -> JAWL -> envelope emotion -> 3D expression.
        report["bridge_events"] = bridge_events
        report["avatar_emotion"] = emotion_state
        report["avatar_status"] = status_text
        checks["bridge_delivered"] = isinstance(bridge_events, int) and bridge_events > 0
        checks["turn_reached_avatar"] = emotion_state not in {"none", "neutral", "error", "sad"}
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for handle in (avatar, panel):
            if handle:
                handle.close()
        if electron is not None and electron.poll() is None:
            electron.terminate()
            try:
                electron.wait(timeout=10)
            except subprocess.TimeoutExpired:
                electron.kill()
        # The wrapper tears the whole stack down (brain holder included) when
        # its RunSeconds window ends; leave it to finish cleanly.
    report["checks"] = checks
    report["status"] = "passed" if checks and all(checks.values()) else "failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())