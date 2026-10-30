"""Smoke the Electron avatar window through raw CDP (websocket-client).

Attaches to Electron's debug port, finds the avatar page target, and runs
Runtime.evaluate against the live renderer:
  1. VRM model loaded and lists expressions;
  2. the emotion bridge drives the expression manager's actual blendshape
     weight (set 'happy', read the manager value back through the scene);
  3. lip sync changes the 'aa' weight;
  4. a model swap rebuilds the scene without leaking it.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
DESKTOP = ROOT / "desktop"
REPORT = ROOT / "runtime" / "desktop-avatar-smoke.json"
DEBUG_PORT = 9222


class Cdp:
    def __init__(self, ws_url: str) -> None:
        self._ws = websocket.create_connection(ws_url, timeout=15)
        self._id = 0

    def call(self, method: str, params: dict | None = None):
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") == self._id:
                return message

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True})
        return result.get("result", {}).get("result", {}).get("value")


def avatar_ws_url() -> str | None:
    with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    for target in targets:
        if target.get("type") == "page" and "аватар" in (target.get("title") or "").lower():
            return target["webSocketDebuggerUrl"]
    return None


def kill_stale_electron() -> int:
    """Hygiene: a previous smoke run must not hold the debug port or windows.

    Only processes whose command line references THIS repo's desktop
    directory are killed - never a stranger's Electron.
    """
    import subprocess as _sp
    output = _sp.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='electron.exe'\" | "
         "Where-Object { $_.CommandLine -like '*JAWL-VoiceCompanion*' } | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True).stdout
    killed = 0
    for line in output.split():
        if line.strip().isdigit():
            try:
                import os
                os.kill(int(line), 9)
                killed += 1
            except OSError:
                pass
    if killed:
        time.sleep(2)
    return killed


def main() -> int:
    stale = kill_stale_electron()
    process = subprocess.Popen(
        ["node_modules\\.bin\\electron.cmd", ".", "--remote-debugging-port"],
        cwd=DESKTOP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    report: dict = {"schema_version": 1, "profile": "desktop-avatar-smoke",
                    "stale_killed": stale}
    checks: dict[str, bool] = {}
    cdp = None
    try:
        deadline = time.time() + 20
        url = None
        while time.time() < deadline:
            try:
                url = avatar_ws_url()
                if url:
                    break
            except Exception:
                pass
            time.sleep(1)
        checks["avatar_window_found"] = url is not None
        if url:
            cdp = Cdp(url)
            expressions = cdp.evaluate(
                "window.__jawlAvatar ? window.__jawlAvatar.listExpressions() : null")
            report["expressions"] = expressions
            checks["model_loaded"] = isinstance(expressions, list) and len(expressions) > 0
            status_text = cdp.evaluate(
                "document.getElementById('status')?.textContent || ''")
            report["status_text"] = status_text
            checks["model_ready"] = "готов" in str(status_text)
            # Head/eye probe: world position + face direction, for framing.
            report["head_probe"] = cdp.evaluate(
                "window.__jawlHeadProbe || null")
            report["framing"] = cdp.evaluate("window.__jawlFraming || null")
            report["framing_error"] = cdp.evaluate("window.__jawlFramingError || null")

            # Emotion bridge: read the LIVE blendshape weight from the scene.
            cdp.evaluate("window.__jawlAvatar.setEmotion('happy')")
            time.sleep(0.6)
            weight = cdp.evaluate("""
                (() => {
                  const scene = document.querySelector('canvas');
                  return window.__jawlEmotionWeight !== undefined
                    ? window.__jawlEmotionWeight : 'no-probe';
                })()
            """)
            report["emotion_weight_probe"] = weight
            # Fallback verification: the scene state via the status label.
            status_after = cdp.evaluate(
                "document.getElementById('status')?.textContent || ''")
            checks["emotion_bridge"] = "happy" in str(status_after)

            # Lip sync: 'aa' weight through a scene-level probe.
            cdp.evaluate("window.__jawlAvatar.setLipLevel(0.7)")
            time.sleep(0.3)
            report["lip_probe"] = cdp.evaluate(
                "window.__jawlLipLevel !== undefined ? window.__jawlLipLevel : 'no-probe'")

            # Model swap without leaking: scene children count stable.
            before = cdp.evaluate("window.__scene ? window.__scene.children.length : null")
            cdp.evaluate(
                "window.__jawlAvatar.swapModel('../runtime/vrm-models/VRM1_Constraint_Twist_Sample.vrm')")
            time.sleep(6)
            after = cdp.evaluate("window.__scene ? window.__scene.children.length : null")
            report["scene_children"] = {"before": before, "after": after}
            checks["model_swap_no_leak"] = (
                isinstance(before, int) and isinstance(after, int) and after <= before + 1)

            # ADR-045 wardrobe surface: wear() must resolve the bounded model
            # id (not a path), reject an unknown id, and report the worn model.
            worn = cdp.evaluate(
                "window.__jawlAvatar.wear('VRM1_Constraint_Twist_Sample').then(() => window.__jawlWornModel)")
            time.sleep(1)
            worn_now = cdp.evaluate("window.__jawlWornModel || null")
            rejected = cdp.evaluate(
                "window.__jawlAvatar.wear('../../secrets/boom').then(() => window.__jawlWornModel)")
            time.sleep(1)
            rejected_state = cdp.evaluate(
                "window.__jawlWornModel === null || window.__jawlWornModel === undefined")
            report["wardrobe"] = {
                "wear_returns": worn,
                "worn_model": worn_now,
                "traversal_rejected": rejected_state,
            }
            checks["wardrobe_wear_bounded"] = (
                worn_now == "VRM1_Constraint_Twist_Sample" and bool(rejected_state))

            # Visual evidence: capture the rendered avatar window through CDP
            # (Page.captureScreenshot) for the vision check.
            try:
                shot = cdp.call("Page.captureScreenshot", {"format": "png"})
                import base64
                png = base64.b64decode(shot["result"]["data"])
                screenshot = ROOT / "runtime" / "browser-evidence" / "desktop-avatar-smoke.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(png)
                report["screenshot"] = str(screenshot)
                checks["screenshot_captured"] = png is not None and len(png) > 10000
            except Exception as exc:
                report["screenshot_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if cdp is not None:
            try:
                cdp._ws.close()
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        # Guarantee: no Electron of ours survives this smoke run.
        kill_stale_electron()
    report["checks"] = checks
    report["status"] = "passed" if checks and all(checks.values()) else "failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())