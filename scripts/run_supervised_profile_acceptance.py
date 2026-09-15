"""Live acceptance for the opt-in native JAWL instance supervisor.

The test uses a unique disposable profile, starts the normal integrated
launcher with ``-EnableSupervisor``, observes the real JAWL startup, and then
verifies that intentional shutdown leaves no supervisor markers, profile
registry entry, or listening test port behind.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "runtime" / "instances"
REGISTRY = INSTANCES / "registry.json"
LAUNCHER = ROOT / "scripts" / "run_integrated_profile.ps1"
PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")


class AcceptanceFailure(RuntimeError):
    pass


def port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def registry_payload() -> dict:
    if not REGISTRY.is_file():
        return {"version": 1, "revision": 0, "profiles": {}, "runtime": {}}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def remove_disposable_state(profile: str) -> None:
    profile_path = (INSTANCES / profile).resolve()
    if INSTANCES.resolve() not in profile_path.parents:
        raise AcceptanceFailure("refusing cleanup outside the instances root")
    if profile_path.exists():
        shutil.rmtree(profile_path)
    payload = registry_payload()
    payload.setdefault("profiles", {}).pop(profile, None)
    payload.setdefault("runtime", {}).pop(profile, None)
    payload["revision"] = int(payload.get("revision", 0)) + 1
    temporary = REGISTRY.with_name(REGISTRY.name + f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, REGISTRY)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for live startup")
    parser.add_argument("--run-seconds", type=int, default=12)
    parser.add_argument("--console-port", type=int, default=8798)
    parser.add_argument("--control-port", type=int, default=2398)
    parser.add_argument("--presentation-port", type=int, default=8799)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live supervisor acceptance requires --live")
    if args.run_seconds < 5 or args.run_seconds > 600:
        parser.error("--run-seconds must be between 5 and 600")

    profile = "supervised-acceptance-" + uuid4().hex[:10]
    if not PROFILE_PATTERN.fullmatch(profile):
        raise AcceptanceFailure("generated profile name is invalid")
    report_path = (args.report or ROOT / "runtime" / (
        "supervised-profile-acceptance-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )).resolve()
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER),
        "-ProfileName", profile,
        "-JawlConsolePort", str(args.console_port),
        "-ControlPort", str(args.control_port),
        "-PresentationPort", str(args.presentation_port),
        "-NoBrowser", "-NoLive2D", "-EnableSupervisor",
        "-NativeAccessLevel", "3", "-RunSeconds", str(args.run_seconds),
        "-StartupTimeoutSeconds", "180", "-JawlChatTimeoutSeconds", "60",
    ]
    env = os.environ.copy()
    env.setdefault("LLM_API_URL", "http://127.0.0.1:11434/v1")
    env.setdefault("LLM_API_KEY_1", "local-loopback")
    env.setdefault("LLM_REASONING_EFFORT", "none")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.monotonic()
    output = ""
    exit_code: int | None = None
    cleanup_error = ""
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        exit_code = completed.returncode
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    except Exception as exc:  # noqa: BLE001 - report the live failure
        output = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            remove_disposable_state(profile)
        except Exception as exc:  # noqa: BLE001 - preserve primary evidence
            cleanup_error = f"{type(exc).__name__}: {exc}"

    supervisor_ready = "Integrated profile ready:" in output and "supervisor=" in output
    ports_clear = not any(
        port_is_listening(port)
        for port in (args.console_port, args.control_port, args.presentation_port)
    )
    markers_clear = not any(
        path.exists() for path in (INSTANCES / "supervisor.pid", INSTANCES / "supervisor.lock")
    )
    state_clear = profile not in registry_payload().get("profiles", {}) and not (INSTANCES / profile).exists()
    passed = bool(exit_code == 0 and supervisor_ready and ports_clear and markers_clear and state_clear and not cleanup_error)
    report = {
        "schema_version": 1,
        "test": "integrated_native_supervisor_start_and_intentional_stop",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "profile": profile,
        "command": command,
        "exit_code": exit_code,
        "supervisor_ready": supervisor_ready,
        "ports_clear": ports_clear,
        "supervisor_markers_clear": markers_clear,
        "registry_and_profile_clear": state_clear,
        "cleanup_error": cleanup_error,
        "output_tail": output[-6000:],
        "pass": passed,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": passed, "report": str(report_path), "profile": profile}, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
