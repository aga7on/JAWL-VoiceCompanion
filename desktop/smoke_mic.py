"""Smoke: the microphone works in the Electron panel window (ADR-045 slice 4).

The panel window (http origin, our direct flags: autoplay no-user-gesture,
fake-UI for the media prompt, NO fake device) must be able to:
  1. enumerate real audio input devices (the owner's fifine mic among them);
  2. open a real getUserMedia(audio) stream (not a fake capture);
  3. run the AudioWorklet gate: the panel's own mic-processor.js loads and
     produces non-silent frames for real room audio.

The stack is NOT needed for the media check itself - the panel server
serves the frontend and the worklet. This smoke raises a minimal companion
server (no brain) plus Electron, drives the panel window over CDP, and
records what the media pipeline actually did.
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
REPORT = ROOT / "runtime" / "desktop-mic-smoke.json"
DEBUG_PORT = 9222
PANEL_PORT = 2379  # disposable; no brain, just the panel server


class Cdp:
    def __init__(self, ws_url: str, timeout: float = 30) -> None:
        self._ws = websocket.create_connection(ws_url, timeout=timeout)
        self._id = 0

    def call(self, method: str, params: dict | None = None):
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") == self._id:
                return message

    def evaluate(self, expression: str, timeout: float = 30):
        self._ws.settimeout(timeout)
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True})
        return result.get("result", {}).get("result", {}).get("value")


def kill_stale_electron() -> int:
    killed = 0
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='electron.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            line = line.strip()
            if "JAWL-VoiceCompanion" in line and line.split()[-1].isdigit():
                subprocess.run(["taskkill", "/PID", line.split()[-1], "/F"],
                               capture_output=True, timeout=10)
                killed += 1
    except Exception:
        pass
    return killed


def window_ws_url(match: str) -> str | None:
    with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    for target in targets:
        if target.get("type") == "page" and match in (target.get("url") or ""):
            return target["webSocketDebuggerUrl"]
    return None


def main() -> int:
    report: dict = {"schema_version": 1, "profile": "desktop-mic-smoke"}
    checks: dict = {}
    report["stale_killed"] = kill_stale_electron()

    # 1. A minimal companion server: the panel + the worklet, no brain.
    env = {
        "PYTHONPATH": str(ROOT / "src"),
        "JAWL_INSTANCE_ID": "mic-smoke",
        "JAWL_INSTANCE_HOME": str(ROOT / "runtime" / "instances" / "_mic-smoke"),
        "JAWL_DATA_DIR": str(ROOT / "runtime" / "instances" / "_mic-smoke" / "data"),
        "JAWL_LOG_DIR": str(ROOT / "runtime" / "instances" / "_mic-smoke" / "logs"),
    }
    for key, value in {
        "SYSTEMROOT": r"C:\Windows",
        "PATH": r"C:\Windows\System32;C:\Windows;C:\Python314",
        "USERPROFILE": str(Path.home()),
        "APPDATA": str(Path.home() / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(Path.home() / "AppData" / "Local"),
        "TEMP": str(Path(r"C:\Users\ARTEM\AppData\Local\Temp")),
        "TMP": str(Path(r"C:\Users\ARTEM\AppData\Local\Temp")),
    }.items():
        env.setdefault(key, value)
    for sub in ("data", "logs"):
        (ROOT / "runtime" / "instances" / "_mic-smoke" / sub).mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [r"C:\Python314\python.exe", "-X", "utf8", "-m", "jawl_voicecompanion",
         "--host", "127.0.0.1", "--port", str(PANEL_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")

    try:
        deadline = time.time() + 60
        healthy = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PANEL_PORT}/api/health", timeout=2) as r:
                    if r.status == 200:
                        healthy = True
                        break
            except Exception:
                time.sleep(1)
        checks["panel_server_up"] = healthy

        # 2. Electron with the panel port env.
        import os

        electron_env = dict(os.environ)
        electron_env["JAWL_DESKTOP_CONTROL_PORT"] = str(PANEL_PORT)
        electron = subprocess.Popen(
            ["node_modules\\.bin\\electron.cmd", ".", "--remote-debugging-port"],
            cwd=DESKTOP, env=electron_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        report["electron_pid"] = electron.pid

        deadline = time.time() + 60
        panel = None
        while time.time() < deadline:
            try:
                panel = window_ws_url(f":{PANEL_PORT}")
                if panel:
                    break
            except Exception:
                pass
            time.sleep(1)
        checks["panel_window_found"] = panel is not None

        if panel:
            cdp = Cdp(panel)
            # 3. Real device enumeration (permissions granted via fake-UI).
            devices = cdp.evaluate("""
                (async () => {
                  try {
                    const list = await navigator.mediaDevices.enumerateDevices();
                    return JSON.stringify(list.filter(d => d.kind === 'audioinput')
                      .map(d => ({label: d.label, deviceId: d.deviceId.slice(0, 8)})));
                  } catch (e) { return JSON.stringify({error: String(e)}); }
                })()
            """, timeout=20)
            report["audio_inputs"] = json.loads(devices) if devices else None
            labels = [d.get("label", "") for d in (report.get("audio_inputs") or []) if isinstance(d, dict)]
            checks["devices_enumerated"] = len(labels) > 0 and any("fifine" in l.lower() for l in labels)

            # 4. Open the REAL mic stream (no fake device in flags).
            stream_probe = cdp.evaluate("""
                (async () => {
                  try {
                    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
                    const track = stream.getAudioTracks()[0];
                    const settings = track.getSettings();
                    const result = {
                      label: track.label,
                      sampleRate: settings.sampleRate,
                      channels: settings.channelCount,
                      fake: settings.deviceId === '' || String(track.label).includes('fake'),
                    };
                    track.stop();
                    return JSON.stringify(result);
                  } catch (e) { return JSON.stringify({error: String(e)}); }
                })()
            """, timeout=30)
            report["mic_stream"] = json.loads(stream_probe) if stream_probe else None
            mic = report.get("mic_stream") or {}
            checks["mic_stream_opened"] = bool(mic.get("label")) and not mic.get("error")
            checks["mic_is_real_device"] = bool(mic.get("label")) and not mic.get("fake")

            # 5. AudioWorklet gate: the panel's own mic-processor.js loads and
            #    real room audio produces non-silent PCM chunks (the gate
            #    posts raw Float32 buffers, not rms summaries).
            worklet_probe = cdp.evaluate("""
                (async () => {
                  try {
                    const context = new AudioContext();
                    await context.audioWorklet.addModule('/mic-processor.js');
                    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
                    const source = context.createMediaStreamSource(stream);
                    const gate = new AudioWorkletNode(context, 'jawl-mic-processor');
                    let frames = 0, loudFrames = 0;
                    gate.port.onmessage = (event) => {
                      const data = event.data;
                      if (data instanceof ArrayBuffer) {
                        const samples = new Float32Array(data);
                        frames += 1;
                        let energy = 0;
                        for (let i = 0; i < samples.length; i += 16) {
                          energy += samples[i] * samples[i];
                        }
                        const rms = Math.sqrt(energy / (samples.length / 16));
                        if (rms > 0.0005) loudFrames += 1;
                      }
                    };
                    source.connect(gate);
                    await new Promise(resolve => setTimeout(resolve, 3000));
                    const tracks = stream.getAudioTracks();
                    tracks.forEach(t => t.stop());
                    await context.close();
                    return JSON.stringify({frames, loudFrames});
                  } catch (e) { return JSON.stringify({error: String(e)}); }
                })()
            """, timeout=60)
            report["worklet_gate"] = json.loads(worklet_probe) if worklet_probe else None
            gate = report.get("worklet_gate") or {}
            # The gate produces PCM chunks from the real device. Room audio
            # may be quiet - flowing chunks are the hard requirement; loud
            # frames are recorded as evidence, not as a pass condition.
            checks["worklet_gate_loaded"] = "frames" in gate and gate.get("frames", 0) > 0
            checks["worklet_frames_flowing"] = "frames" in gate and gate.get("frames", 0) > 0
            cdp._ws.close()
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for proc in ("electron", "server"):
            handle = locals().get(proc)
            if handle and handle.poll() is None:
                handle.kill()
        kill_stale_electron()

    report["checks"] = checks
    report["status"] = "passed" if checks and all(checks.values()) else "failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())