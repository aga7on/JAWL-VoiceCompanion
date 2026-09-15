"""Live fault-boundary acceptance for JAWL Goal Ledger reconciliation.

This harness owns only a disposable profile selected by ``--profile``. It
creates a Goal without waking the heartbeat, sends one real Companion turn,
waits for the native journal's ``action_started`` record, kills only the
profile-owned JAWL process tree, restarts it through the Companion control
plane, and verifies that the durable ledger requires reconciliation. The
postcondition is then read through native HostOS and acknowledged through the
native operator control protocol. No Companion-local executor is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import threading
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from uuid import uuid4

import psutil
import requests


class AcceptanceFailure(RuntimeError):
    """A live connected assertion failed."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def read_goals(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AcceptanceFailure(f"goal store is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("goals"), list):
        raise AcceptanceFailure("goal store has an invalid shape")
    return value


def _process_command(process: psutil.Process) -> str:
    try:
        return " ".join(process.cmdline()).replace("/", "\\").casefold()
    except (psutil.Error, OSError):
        return ""


def _belongs_to_profile(process: psutil.Process, profile: Path) -> bool:
    """Require the selected profile in the process ancestry before killing it."""

    profile_token = profile.name.casefold()
    profile_path = str(profile.resolve()).replace("/", "\\").casefold()
    try:
        ancestry = [process, *process.parents()]
    except (psutil.Error, OSError):
        ancestry = [process]
    for item in ancestry:
        command = _process_command(item)
        if profile_path in command or f"profilename {profile_token}" in command:
            return True
        try:
            cwd = (item.cwd() or "").replace("/", "\\").casefold()
        except (psutil.Error, OSError):
            cwd = ""
        if profile_path in cwd:
            return True
    return False


def profile_processes(profile: Path, source: Path) -> list[psutil.Process]:
    """Find only JAWL processes owned by the selected integrated profile.

    ``agent.pid`` is useful during normal operation, but it is not a safe sole
    authority at a crash boundary: two JAWL launchers can race while cleaning
    the same pid file.  The fallback discovers the pinned source process and
    proves ownership through the profile launcher ancestry.
    """

    source_token = str(source.resolve()).replace("/", "\\").casefold()
    candidates: dict[int, psutil.Process] = {}
    pid_path = profile / "data" / "agent" / "agent.pid"
    if pid_path.is_file():
        try:
            candidates[int(pid_path.read_text(encoding="utf-8").strip())] = psutil.Process(
                int(pid_path.read_text(encoding="utf-8").strip())
            )
        except (OSError, ValueError, psutil.Error):
            pass
    for process in psutil.process_iter(["pid", "cmdline"]):
        command = _process_command(process)
        if source_token in command and _belongs_to_profile(process, profile):
            candidates[process.pid] = process

    checked: dict[int, psutil.Process] = {}
    for root in candidates.values():
        try:
            roots = [root, *root.children(recursive=True)]
        except (psutil.Error, OSError):
            continue
        for process in roots:
            command = _process_command(process)
            if source_token not in command or not _belongs_to_profile(process, profile):
                continue
            checked[process.pid] = process
    if not checked:
        raise AcceptanceFailure("profile JAWL process is unavailable or not owned by the selected profile")
    return list(checked.values())


def kill_owned_jawl(processes: list[psutil.Process]) -> list[int]:
    killed: list[int] = []
    for process in sorted(processes, key=lambda item: item.pid, reverse=True):
        try:
            process.kill()
            killed.append(process.pid)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as exc:
            raise AcceptanceFailure(f"could not kill owned JAWL pid {process.pid}") from exc
    _, alive = psutil.wait_procs(processes, timeout=10)
    if alive:
        raise AcceptanceFailure(
            "owned JAWL process tree did not terminate: "
            + ",".join(str(item.pid) for item in alive)
        )
    return killed


def control_request(port_file: Path, action: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    try:
        port = int(port_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        raise AcceptanceFailure("native terminal port file is unavailable") from exc
    request_id = uuid4().hex
    envelope = {
        "type": "control",
        "id": request_id,
        "action": action,
        "params": params,
    }
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as client:
        client.sendall(b"JAWL_CONTROL\n")
        client.sendall((json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8"))
        client.settimeout(timeout)
        data = bytearray()
        while b"\n" not in data and len(data) <= 65536:
            chunk = client.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
    if len(data) > 65536:
        raise AcceptanceFailure("native control response exceeded the bound")
    try:
        response = json.loads(bytes(data).splitlines()[0].decode("utf-8"))
    except (IndexError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure("native control response was invalid") from exc
    if not isinstance(response, dict) or response.get("id") != request_id:
        raise AcceptanceFailure("native control response id mismatch")
    if response.get("ok") is not True:
        raise RuntimeError(str(response.get("error") or "native control rejected the request"))
    result = response.get("result")
    if not isinstance(result, dict):
        raise AcceptanceFailure("native control result was not an object")
    return result


def bootstrap(base: str, timeout: float) -> tuple[requests.Session, dict[str, str]]:
    session = requests.Session()
    response = session.get(base + "/api/session", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    csrf = payload.get("csrf_token")
    cookie = SimpleCookie(response.headers.get("Set-Cookie", "")).get("companion_session")
    if not isinstance(csrf, str) or not csrf or cookie is None:
        raise AcceptanceFailure("Companion session bootstrap was incomplete")
    return session, {
        "Origin": base,
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": cookie.value,
    }


def native_action(base: str, headers: dict[str, str], skill: str, arguments: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any]]:
    response = requests.post(
        base + "/api/hostos/execute",
        headers=headers,
        json={"request": {"skill": skill, "arguments": arguments}},
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AcceptanceFailure(f"{skill} returned non-JSON HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise AcceptanceFailure(f"{skill} returned a non-object envelope")
    return response.status_code, payload


def stream_turn(session: requests.Session, base: str, headers: dict[str, str], text: str, turn: dict[str, Any], timeout: float) -> None:
    try:
        with session.post(
            base + "/api/chat/stream",
            headers=headers,
            json={"text": text, "session_id": "goal-reconcile-" + uuid4().hex[:10]},
            stream=True,
            timeout=timeout,
        ) as response:
            turn["status"] = response.status_code
            turn["events"] = [line.decode("utf-8", "replace") for line in response.iter_lines() if line]
    except Exception as exc:  # the interrupted turn is expected to end here
        turn["error"] = f"{type(exc).__name__}: {exc}"
    turn["done"] = True


def wait_health(base: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last = "offline"
    while time.monotonic() < deadline:
        try:
            payload = requests.get(base + "/api/health", timeout=5).json()
            last = str(payload.get("components", {}).get("jawl") or "offline")
            if last in {"connected", "online"}:
                return last
        except requests.RequestException:
            pass
        time.sleep(2)
    return last


def wait_native_goal(port_file: Path, goal_id: str, timeout: float) -> dict[str, Any]:
    """Use the authenticated native control plane as the recovery liveness probe.

    Companion health is an aggregate view and can remain ``offline`` while the
    JAWL terminal is already accepting authenticated control requests during
    its restart transition.  The goal record is the relevant recovery
    authority for this acceptance, so prefer that direct signal and retain the
    aggregate health value only as diagnostic evidence.
    """

    deadline = time.monotonic() + timeout
    last_error = "native control unavailable"
    while time.monotonic() < deadline:
        try:
            goal = control_request(port_file, "goal.get", {"goal_id": goal_id}, timeout=5)
            if goal.get("goal_id") == goal_id:
                return goal
            last_error = "native control returned a different goal"
        except (AcceptanceFailure, RuntimeError, OSError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise AcceptanceFailure(f"JAWL native control did not recover: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for killing a disposable JAWL")
    parser.add_argument("--url", default="http://127.0.0.1:2377")
    parser.add_argument("--profile", default="restart-infer")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--fault-timeout", type=float, default=180.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live goal reconciliation requires --live")
    if not (30 <= args.timeout <= 900 and 10 <= args.fault_timeout <= 600):
        parser.error("invalid timeout bounds")

    repo = Path(__file__).resolve().parents[1]
    profile = (repo / "runtime" / "instances" / args.profile).resolve()
    source = (repo / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2").resolve()
    base = args.url.rstrip("/")
    journal = profile / "data" / "agent" / "action_journal.jsonl"
    goals = profile / "data" / "agent" / "goals.json"
    port_file = profile / "data" / "interfaces" / "host" / "terminal" / "terminal.port"
    sandbox = profile / "sandbox"
    session_id = "goal-reconcile-" + uuid4().hex[:10]
    marker = "GOAL_RECONCILIATION_OK_" + uuid4().hex[:12]
    relative_file = f"sandbox/goal-reconciliation-{session_id}.txt"
    disk_file = sandbox / Path(relative_file).relative_to("sandbox")
    report_path = args.report or repo / "runtime" / (
        "goal-reconciliation-live-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "test": "live_goal_ledger_reconciliation_at_native_crash_boundary",
        "profile": args.profile,
        "base_url": base,
        "session_id": session_id,
        "marker": marker,
        "relative_file": relative_file,
        "goal": {},
        "turn_a": {},
        "fault_injection": {},
        "restart": {},
        "ledger_after_restart": {},
        "operator_reconciliation": {},
        "cleanup": {},
        "pass": False,
        "failure": None,
    }
    session: requests.Session | None = None
    headers: dict[str, str] = {}
    try:
        if profile.name != args.profile or not sandbox.is_dir():
            raise AcceptanceFailure("profile sandbox is missing or unsafe")
        if not source.is_dir() or not goals.parent.is_dir():
            raise AcceptanceFailure("profile/source paths are missing")
        # A fresh profile has no native journal until the first action.  Touch
        # only the selected disposable profile so the streaming tailer can
        # establish its offset before the real turn starts.
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.touch(exist_ok=True)
        session, headers = bootstrap(base, args.timeout)
        owned_jawl = profile_processes(profile, source)
        report["fault_injection"]["owned_jawl_pids_before_turn"] = sorted(
            process.pid for process in owned_jawl
        )
        goal = control_request(
            port_file,
            "goal.create",
            {
                "objective": "Verify one native file action across a process interruption; reconcile its postcondition before completion.",
                "verification_policy": "none",
                "wake": False,
            },
        )
        goal_id = str(goal.get("goal_id") or "")
        if not goal_id or goal.get("status") != "active":
            raise AcceptanceFailure("native goal.create did not return an active goal")
        report["goal"]["created"] = goal

        turn: dict[str, Any] = {"events": [], "done": False}
        prompt = (
            f"Use HostOSWriter.write_file to create {relative_file} with exactly this text: {marker}. "
            "This is the only native action in this turn. Do not call any other tool and do not "
            "verify or delete the file; stop immediately after dispatching the write."
        )
        worker = threading.Thread(
            target=stream_turn,
            args=(session, base, headers, prompt, turn, args.timeout),
            daemon=True,
        )
        worker.start()
        action_id = ""
        plan_id = ""
        started_at = time.monotonic()
        # Reopen the file on every short poll.  Windows may keep a text stream
        # at EOF after another process appends to the file; reopening avoids a
        # false negative at the crash boundary while keeping the poll bounded.
        while time.monotonic() - started_at < args.fault_timeout:
            for entry in read_jsonl(journal):
                parameters = entry.get("parameters")
                if (
                    entry.get("event") == "action_started"
                    and entry.get("tool_name") == "HostOSWriter.write_file"
                    and isinstance(parameters, dict)
                    and parameters.get("content") == marker
                ):
                    action_id = str(entry.get("action_id") or "")
                    plan_id = str(entry.get("plan_id") or "")
                    break
            if action_id or turn.get("done"):
                break
            time.sleep(0.001)
        if not action_id:
            raise AcceptanceFailure("did not observe the target action_started journal entry")
        killed = kill_owned_jawl(owned_jawl)
        report["fault_injection"] = {
            "action_started": True,
            "action_id": action_id,
            "plan_id": plan_id,
            "killed_pids": killed,
            "owned_jawl_pids_before_turn": sorted(process.pid for process in owned_jawl),
        }
        worker.join(timeout=30)
        report["turn_a"] = turn

        restart_response = session.post(
            base + "/api/jawl/restart",
            headers=headers,
            json={"wait_for_memory": True},
            timeout=args.timeout,
        )
        report["restart"] = {"status": restart_response.status_code, "body": restart_response.json()}
        if restart_response.status_code != 200 or restart_response.json().get("ok") is not True:
            raise AcceptanceFailure("Companion native restart did not succeed")
        recovered_goal = wait_native_goal(port_file, goal_id, args.timeout)
        report["restart"]["native_goal_recovered"] = {
            "goal_id": recovered_goal.get("goal_id"),
            "status": recovered_goal.get("status"),
            "last_cycle_status": recovered_goal.get("last_cycle_status"),
        }
        # Prevent the autonomous heartbeat from starting a second recovery plan
        # while the operator-side postcondition probe is being asserted.  This
        # is a test-only durable wait, not a production behavior change.
        report["restart"]["pause"] = control_request(
            port_file,
            "goal.wakeup",
            {
                "wake_after_seconds": 600,
                "summary": "Acceptance harness pauses autonomous heartbeat before operator reconciliation.",
            },
        )
        health = wait_health(base, min(args.timeout, 30.0))
        report["restart"]["health_after"] = health
        if report["restart"].get("native_goal_recovered", {}).get("goal_id") != goal_id:
            raise AcceptanceFailure("native recovery probe returned the wrong goal")

        restored = next(
            item for item in read_goals(goals)["goals"] if item.get("goal_id") == goal_id
        )
        ledger = restored.get("task_ledger") if isinstance(restored.get("task_ledger"), dict) else {}
        batch = ledger.get("last_action_batch") if isinstance(ledger.get("last_action_batch"), list) else []
        restored_action = next(
            (
                item
                for item in batch
                if item.get("action_id") == action_id
                and item.get("tool") == "HostOSWriter.write_file"
            ),
            None,
        )
        report["ledger_after_restart"] = {
            "status": restored.get("status"),
            "last_cycle_status": restored.get("last_cycle_status"),
            "current_phase": ledger.get("current_phase"),
            "action": restored_action,
            "actions": batch,
        }
        if restored.get("status") != "active" or not isinstance(restored_action, dict) or restored_action.get("status") != "needs_reconciliation":
            raise AcceptanceFailure("restart did not restore the action as needs_reconciliation")

        before_complete = control_request(
            port_file,
            "goal.update",
            {"goal_id": goal_id, "status": "complete", "summary": "unsafe premature completion probe"},
        )
        report["operator_reconciliation"]["premature_completion_response"] = before_complete
        raise AssertionError("goal.update unexpectedly allowed completion before reconciliation")
    except RuntimeError as exc:
        # The expected guard response is transported as a native control error;
        # retain it and continue with the postcondition probe below.
        if "reconciliation" not in str(exc).casefold():
            report["failure"] = f"{type(exc).__name__}: {exc}"
    except AssertionError as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    except (AcceptanceFailure, OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"

    # A guard failure is expected and the remaining steps are intentionally
    # separated so the report distinguishes recovery from completion.
    try:
        if report["failure"] is None and session is not None:
            status, payload = native_action(
                base, headers, "HostOSReader.read_file", {"filepath": relative_file}, args.timeout
            )
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            file_exists = disk_file.is_file()
            disk_sha = hashlib.sha256(disk_file.read_bytes()).hexdigest() if file_exists else ""
            postcondition = {
                "http_status": status,
                "native": payload.get("native") is True,
                "is_success": result.get("is_success") is True,
                "file_exists": file_exists,
                "disk_sha256": disk_sha,
                "marker_present": file_exists and marker in disk_file.read_text(encoding="utf-8"),
            }
            report["operator_reconciliation"]["postcondition"] = postcondition
            writer_outcome = "confirmed" if postcondition["marker_present"] else "not_applied"
            writer_evidence = (
                f"Native HostOSReader.read_file postcondition: {writer_outcome}; "
                f"marker={postcondition['marker_present']}; sha256={disk_sha or 'absent'}"
            )
            journal_entries = read_jsonl(journal)
            original_plan_started = {
                (str(entry.get("action_id") or ""), str(entry.get("tool_name") or ""))
                for entry in journal_entries
                if entry.get("event") == "action_started"
                and str(entry.get("plan_id") or "") == str(report["fault_injection"].get("plan_id") or "")
            }
            reconciliation_actions: list[dict[str, str]] = [
                {
                    "action_id": action_id,
                    "tool": "HostOSWriter.write_file",
                    "status": writer_outcome,
                    "evidence": writer_evidence,
                }
            ]
            for item in report["ledger_after_restart"].get("actions", []):
                if not isinstance(item, dict):
                    continue
                item_key = (str(item.get("action_id") or ""), str(item.get("tool") or ""))
                if item_key == (action_id, "HostOSWriter.write_file") or item.get("status") not in {"in_flight", "needs_reconciliation", "unknown"}:
                    continue
                if item_key in original_plan_started:
                    raise AcceptanceFailure(
                        "an additional uncertain action was dispatched before the crash; "
                        f"independent postcondition is required for {item_key[1]}[{item_key[0]}]"
                    )
                reconciliation_actions.append(
                    {
                        "action_id": item_key[0],
                        "tool": item_key[1],
                        "status": "not_applied",
                        "evidence": (
                            "No action_started record exists for this action in the original "
                            f"plan {report['fault_injection'].get('plan_id') or 'unknown'}; "
                            "the crash occurred before native dispatch."
                        ),
                    }
                )
            report["operator_reconciliation"]["reconciliation_actions"] = reconciliation_actions
            reconciled = control_request(
                port_file,
                "goal.ledger.update",
                {
                    "patch": {
                        "phase": "reconciled",
                        "reconcile_actions": reconciliation_actions,
                        "checkpoint_summary": writer_evidence,
                    }
                },
            )
            report["operator_reconciliation"]["ledger_patch"] = reconciled
            completed = control_request(
                port_file,
                "goal.update",
                {"goal_id": goal_id, "status": "complete", "summary": "Native postcondition reconciled before completion."},
            )
            report["operator_reconciliation"]["completed_goal"] = completed
            report["operator_reconciliation"]["pass"] = (
                completed.get("status") == "complete"
                and bool(reconciled.get("task_ledger", {}).get("last_action_batch"))
            )
            if disk_file.is_file():
                delete_status, delete_payload = native_action(
                    base, headers, "HostOSWriter.delete_file", {"filepath": relative_file}, args.timeout
                )
                report["cleanup"] = {
                    "delete_status": delete_status,
                    "delete_native": delete_payload.get("native") is True,
                    "file_absent": not disk_file.exists(),
                }
            else:
                report["cleanup"] = {"file_absent": True, "delete_skipped": True}
    except (AcceptanceFailure, RuntimeError, OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
        report["failure"] = report["failure"] or f"{type(exc).__name__}: {exc}"

    report["pass"] = bool(
        report["failure"] is None
        and report.get("fault_injection", {}).get("action_started") is True
        and report.get("ledger_after_restart", {}).get("action", {}).get("status") == "needs_reconciliation"
        and report.get("operator_reconciliation", {}).get("pass") is True
        and report.get("cleanup", {}).get("file_absent") is True
    )
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(report_path), "pass": report["pass"], "failure": report["failure"], "ledger_after_restart": report["ledger_after_restart"]}, ensure_ascii=False))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
