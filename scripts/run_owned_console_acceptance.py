"""Opt-in isolated owned-console probe; never starts the native agent/models."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jawl_voicecompanion.supervisor import RuntimeSupervisor, WorkerSpec
from run_llm_cancel_acceptance import child_environment, PINNED_PYTHON, PINNED_SOURCE


def probe(report: dict) -> None:
    if sys.platform != "win32":
        raise RuntimeError("this probe requires exact Windows Job ownership")
    run_root = ROOT / "runtime/instances" / ("admission-probe-" + uuid4().hex[:12])
    run_root.mkdir()
    env = child_environment(run_root)
    home = Path(env["JAWL_INSTANCE_HOME"])
    home.mkdir()
    for key in ("DATA", "CONFIG", "LOG", "CACHE", "PROMPT", "SANDBOX"):
        path = home / key.lower()
        path.mkdir()
        env["JAWL_" + key + "_DIR"] = str(path)
    env.update(CONSOLE_TOKEN="local-admission-probe",
               JAWL_CACHE_DIR=str(home / "cache"),
               JAWL_INSTANCES_ROOT=str(ROOT / "runtime/instances"),
               PYTHONPATH=str(PINNED_SOURCE))
    if source_root := os.environ.get("JAWL_SOURCE_ROOT"):
        env["JAWL_SOURCE_ROOT"] = source_root
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({})).open
    report.update(port=port, run_root=str(run_root))
    log = run_root / "console.log"
    command = [str(PINNED_PYTHON), "-B", str(ROOT / "scripts/run_owned_jawl_console.py"),
               "--host", "127.0.0.1", "--port", str(port), "--no-browser", "--keep-agent"]
    launch = ("import subprocess,sys; from pathlib import Path; f=Path(" + repr(str(log)) + ").open('xb'); "
              "p=subprocess.run(" + repr(command) + ",stdout=f,stderr=subprocess.STDOUT); "
              "f.close();sys.exit(p.returncode)")
    observed = {}

    def request(path, body=None, auth=True):
        headers = {"X-Console-Token": "local-admission-probe"} if auth else {}
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            with opener(Request(base + path, data=data, headers=headers), timeout=.5) as response:
                return response.status, json.loads(response.read(16384))
        except HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read(16384))

    def health():
        status, cap = request("/api/companion/admission-capabilities")
        if status != 200 or cap.get("feature") != "http-turn-admission-v1":
            return False
        observed.update(cap)
        return supervisor.owns_pid(cap["process_id"])

    supervisor = RuntimeSupervisor([WorkerSpec(
        "console", [str(PINNED_PYTHON), "-B", "-c", launch], health,
        cwd=str(home), env=env, startup_timeout_seconds=20, max_restarts=0, stop_timeout_seconds=1,
    )])
    owned = None
    try:
        started = time.perf_counter()
        startup = supervisor.start()
        report.update(startup_seconds=round(time.perf_counter() - started, 3), startup_ok=startup.ok)
        if not startup.ok:
            raise AssertionError("owned console failed startup; inspect isolated console.log")
        owned = supervisor._states["console"].process  # exact owned Popen handle, not PID-only exit evidence
        report.update(launcher_pid=owned.pid, listener_pid=observed["process_id"], capabilities=observed,
                      exact_job_proof=supervisor.owns_pid(observed["process_id"]))
        denied, _ = request("/api/companion/admission-capabilities", auth=False)
        cancelled, cancel = request("/api/companion/cancel", {"turn_id": "probe-cancelled"})
        rejected, turn = request("/api/companion/turn", {"turn_id": "probe-cancelled", "text": "never dispatch"})
        assert denied == 401 and cancelled == 200 and cancel.get("local_dispatch_prevented") is True
        assert rejected == 409 and turn.get("error") == "turn_cancelled"
        report.update(status="passed", checks={"native_auth": denied, "cancel_before_turn": cancelled,
                                              "tombstone_reject": rejected})
    finally:
        try:
            supervisor.stop()
        except Exception as exc:
            report.update(status="failed", cleanup_error=type(exc).__name__)
        report["observed_launcher_exit_code"] = owned.poll() if owned is not None else None
        deadline = time.monotonic() + 2
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    pass
            except OSError:
                report["listener_gone"] = True
                break
            if time.monotonic() >= deadline:
                report.update(listener_gone=False, status="failed")
                break
            time.sleep(.02)

    brain_env = dict(env)
    brain_env["JAWL_BRAIN_BOOTSTRAP_ONLY"] = "1"
    brain_process = subprocess.Popen(
        [str(PINNED_PYTHON), "-B", str(ROOT / "scripts/run_owned_jawl_brain.py")],
        cwd=str(home), env=brain_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        brain_output, _ = brain_process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        brain_process.kill()
        brain_output, _ = brain_process.communicate(timeout=3)
    report["brain_bootstrap"] = {
        "pid": brain_process.pid,
        "exit_code": brain_process.returncode,
        "initialized": "Owned brain entrypoint initialized." in brain_output,
        "probe_complete": "Owned brain bootstrap probe complete." in brain_output,
        "main_import_skipped": "Traceback" not in brain_output,
    }
    receipt = json.loads((Path(brain_env["JAWL_LOG_DIR"]) / "owned-brain-startup.json").read_text(encoding="utf-8"))
    report["brain_bootstrap"]["startup_receipt"] = receipt
    # Windows venv python.exe is a redirector: Popen may retain its PID while
    # the actual interpreter (which writes the receipt) is its direct child.
    report["brain_bootstrap"]["runtime_pid"] = receipt["pid"]
    report["brain_bootstrap"]["venv_redirector_observed"] = receipt["parent_pid"] == brain_process.pid
    report["brain_bootstrap"]["identity_verified"] = bool(
        (receipt["pid"] == brain_process.pid or receipt["parent_pid"] == brain_process.pid)
        and receipt["bootstrap_only"] is True
        and receipt["hooks"] == {"delivery_guard": True, "goal_wakeup_backoff": True}
        and Path(receipt["instance_home"]).resolve() == home.resolve()
    )
    if not (brain_process.returncode == 0 and report["brain_bootstrap"]["initialized"]
            and report["brain_bootstrap"]["probe_complete"]
            and report["brain_bootstrap"]["main_import_skipped"]):
        report.update(status="failed")
        raise AssertionError("owned brain child bootstrap did not complete")
    if not report["brain_bootstrap"]["identity_verified"]:
        raise AssertionError("owned brain bootstrap receipt identity did not match")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-console-probe", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.allow_console_probe:
        parser.error("pass --allow-console-probe; no native agent/model is started")
    report = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "actual owned launcher+pinned console HTTP; no agent/model/device"}
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output)
        output.flush()
        try:
            probe(report)
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__, detail=str(exc)[:200])
        report.update(ended_at=datetime.now(timezone.utc).isoformat(),
                      exit_code=0 if report["status"] == "passed" else 1)
        output.seek(0)
        json.dump(report, output, indent=2)
        output.truncate()
    print(json.dumps(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
