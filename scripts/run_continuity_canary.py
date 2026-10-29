"""Owned live regression: tool feedback, registered background Goal, AV context."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec
from jawl_voicecompanion.perception_packet import attach_packet, make_packet
from run_owned_gateway_acceptance import logged_command


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    profile = "continuity-canary-" + uuid4().hex[:8]
    home = ROOT / "runtime" / "instances" / profile
    out = ROOT / "runtime" / "continuity-audit-20261029" / profile
    out.mkdir(parents=True)
    console, control, presentation = free_port(), free_port(), free_port()
    token = uuid4().hex
    env = {key: os.environ[key] for key in (
        "PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
        "HOMEDRIVE", "HOMEPATH",
    ) if key in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", NO_PROXY="*",
               LLM_API_URL="http://127.0.0.1:8045/v1", LLM_API_KEY_1="local-loopback",
               LLM_MAX_OUTPUT_TOKENS="4096", CONSOLE_TOKEN=token)
    env["JAWL_ACCEPTANCE_CONTEXT_DIAGNOSTICS"] = "1"
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts/run_integrated_profile.ps1"), "-ProfileName", profile,
               "-JawlConsolePort", str(console), "-ControlPort", str(control), "-PresentationPort", str(presentation),
               "-NoBrowser", "-NoLive2D", "-AllowBusyStartup", "-RunSeconds", "0",
               "-JawlModelOverride", "gemini-3.8-flash", "-NativeAccessLevel", "0",
               "-NativeContextWindowTokens", "1048576", "-StartupTimeoutSeconds", "180"]

    def request(path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = Request(f"http://127.0.0.1:{console}" + path, data=body,
                      headers={"X-Console-Token": token, "Content-Type": "application/json"})
        with urlopen(req, timeout=10) as r:
            return json.load(r)

    def ready():
        try:
            with urlopen(f"http://127.0.0.1:{control}/api/health", timeout=2) as r:
                return json.load(r).get("status") in {"ok", "ready", "degraded"}
        except Exception:
            return False

    owner = RuntimeSupervisor([WorkerSpec(name="launcher", command=logged_command(out / "launcher.log", command),
                              env=env, cwd=str(ROOT), probe=ready, startup_timeout_seconds=240,
                              max_restarts=0, stop_timeout_seconds=15)])
    report = {"profile": profile, "scope": "real Gemini/native JAWL, isolated sandbox; no sensor quality/audio/device acceptance", "pass": False}
    journal = home / "data/agent/action_journal.jsonl"

    def events():
        if not journal.exists():
            return []
        rows = []
        for line in journal.read_text("utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        return rows

    def send(text):
        turn = "canary-" + uuid4().hex
        request("/api/companion/turn", {"turn_id": turn, "text": text})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            rows = [r for r in events() if r.get("companion_turn_id") == turn]
            finals = [r for r in rows if r.get("event") == "action_finished" and r.get("tool_name") == "HostTerminalMessages.send_message_to_terminal"]
            if finals:
                return turn, rows
            time.sleep(.5)
        raise TimeoutError("correlated terminal response not observed")

    try:
        print("starting", profile, flush=True)
        if not owner.start().ok:
            raise RuntimeError("owned canary failed startup")
        print("ready", flush=True)
        sandbox = home / "sandbox"
        sandbox.mkdir(exist_ok=True)
        marker = "AV_FEEDBACK_" + uuid4().hex
        (sandbox / "seed.txt").write_text(marker, encoding="utf-8")
        packet = make_packet({"channels": {"screen": {"text": "Two cars on a road", "age_ms": 500, "ttl_ms": 5000}}})
        first, rows = send(attach_packet(
            "Read seed.txt in your sandbox. Its contents are unknown to you. Copy the exact string into copied.txt, "
            "then read copied.txt and report the exact string only after verifying it. Execute the native tools; "
            "a promise to do this is not a result. Stay in your own sandbox.", packet))
        text = (sandbox / "copied.txt").read_text("utf-8") if (sandbox / "copied.txt").exists() else ""
        report["immediate"] = {"turn_id": first, "copied_exact": text.strip() == marker,
                               "successful_tools": [r.get("tool_name") for r in rows if r.get("event") == "action_finished" and r.get("is_success")]}
        if text.strip() != marker:
            raise AssertionError("immediate task did not copy the unknown marker")
        print("immediate native work passed", flush=True)
        second, rows = send(
            "Background assignment: copy the exact contents of seed.txt into background-result.txt in your sandbox, "
            "then read the result and complete the assignment only after verification. Register this as durable "
            "continuing work now, briefly acknowledge the registration, then continue by heartbeat without waiting "
            "for another user message. Stay in your sandbox.")
        goal_file = home / "data/agent/goals.json"
        deadline = time.monotonic() + 300
        store = {}
        while time.monotonic() < deadline:
            if goal_file.exists():
                store = json.loads(goal_file.read_text("utf-8"))
                records = store.get("goals", store.get("records", []))
                if any(r.get("status") == "complete" for r in records):
                    break
            time.sleep(.5)
        result = sandbox / "background-result.txt"
        records = store.get("goals", store.get("records", []))
        report["background"] = {"turn_id": second, "goal_store_created": goal_file.exists(),
                                "goal_completed": any(r.get("status") == "complete" for r in records),
                                "copied_exact": result.exists() and result.read_text("utf-8").strip() == marker,
                                "goal_store": store}
        log = (home / "logs/agent.log").read_text("utf-8")
        report["react_step_2_observed"] = "[ReAct] Step 2/" in log
        report["heartbeat_cycles"] = log.count("Reason: HEARTBEAT")
        report["perception_section_observed"] = "[Perception]:" in log
        history = (home / "data/interfaces/host/terminal/history.json").read_text("utf-8")
        report["history_sensor_packets_removed"] = "<va_perception>" not in history
        report["pass"] = bool(report["background"]["copied_exact"] and report["background"]["goal_completed"]
                              and report["react_step_2_observed"] and report["heartbeat_cycles"] > 0
                              and report["perception_section_observed"] and report["history_sensor_packets_removed"])
        if not report["pass"]:
            raise AssertionError("durable background continuation did not pass")
        print("background heartbeat continuation passed", flush=True)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(report["error"], flush=True)
    finally:
        owner.stop()
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("report", str(out / "report.json"), "pass", report["pass"], flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
