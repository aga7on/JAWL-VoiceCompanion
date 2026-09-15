"""Live provider-outage recovery on the proven unattended Goal path.

This harness is deliberately operator-driven at the outage boundary. JAWL
creates and owns a disposable Goal, performs one real sandbox write, and keeps
the Goal active. The operator then stops only the disposable provider endpoint
and restores the same endpoint. The harness restarts JAWL, verifies the file
through native HostOSReader, reconciles an uncertain ledger entry when needed,
and proves exactly one real write before cleanup.

It never kills a process and never touches a path outside the selected profile
sandbox. This is stronger evidence than a long chat prompt: the tested path is
the same Goal/Heartbeat path used for unattended work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import psutil
import requests

try:
    from run_goal_reconciliation_live import (
        AcceptanceFailure,
        bootstrap,
        control_request,
        native_action,
    )
    from run_provider_failure_native_recovery import wait_http, wait_provider_inference
    from run_unattended_goal_soak import set_unattended
except ModuleNotFoundError:
    from scripts.run_goal_reconciliation_live import (
        AcceptanceFailure,
        bootstrap,
        control_request,
        native_action,
    )
    from scripts.run_provider_failure_native_recovery import wait_http, wait_provider_inference
    from scripts.run_unattended_goal_soak import set_unattended


UNCERTAIN_STATUSES = {"in_flight", "needs_reconciliation", "unknown"}


def relay_command_matches(command_line: str, port: int) -> bool:
    """Accept only the repository relay bound to the requested disposable port."""
    return bool(
        re.search(r"(?:^|[\\/ ])opencode_header_relay\.py(?:[ \"']|$)", command_line, re.I)
        and re.search(rf"(?:^|[ \"'])--port[ \"']+{port}(?:[ \"']|$)", command_line, re.I)
    )


def stop_exact_disposable_provider(provider_url: str) -> dict[str, Any]:
    """Stop one verified loopback relay, never an arbitrary listener."""
    parsed = urlsplit(provider_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port in {None, 11434}:
        raise AcceptanceFailure("automatic provider stop requires a non-baseline loopback relay")
    listeners = {
        connection.pid
        for connection in psutil.net_connections(kind="tcp")
        if connection.status == psutil.CONN_LISTEN
        and connection.laddr
        and connection.laddr.port == parsed.port
        and connection.pid
    }
    if len(listeners) != 1:
        raise AcceptanceFailure(
            f"expected exactly one disposable listener on {parsed.port}, found {len(listeners)}"
        )
    process_id = next(iter(listeners))
    process = psutil.Process(process_id)
    command_line = " ".join(process.cmdline())
    if not relay_command_matches(command_line, parsed.port):
        raise AcceptanceFailure(f"refusing to stop unexpected provider PID {process_id}")
    process.terminate()
    try:
        process.wait(timeout=8)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)
    return {"pid": process_id, "port": parsed.port, "command": command_line[:500]}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def successful_marker_writes(path: Path, marker: str) -> list[dict[str, Any]]:
    """Return successful non-idempotent writer pairs for exactly *marker*."""
    entries = read_jsonl(path)
    started = {
        (str(item.get("plan_id") or ""), str(item.get("action_id") or "")): item
        for item in entries
        if item.get("event") == "action_started"
        and item.get("tool_name") == "HostOSWriter.write_file"
        and isinstance(item.get("parameters"), dict)
        and item["parameters"].get("content") == marker
    }
    successful: list[dict[str, Any]] = []
    for item in entries:
        key = (str(item.get("plan_id") or ""), str(item.get("action_id") or ""))
        if (
            item.get("event") == "action_finished"
            and item.get("tool_name") == "HostOSWriter.write_file"
            and item.get("is_success") is True
            and key in started
            and "idempotent no-op" not in str(item.get("message") or "").casefold()
        ):
            successful.append({"started": started[key], "finished": item})
    return successful


def marker_write_evidence(path: Path, marker: str) -> dict[str, Any] | None:
    """Return one successful real writer outcome for exactly *marker*."""
    matches = successful_marker_writes(path, marker)
    return matches[0]["finished"] if matches else None


def goal_action(goal: dict[str, Any], action_id: str, tool: str) -> dict[str, Any] | None:
    ledger = goal.get("task_ledger")
    batch = ledger.get("last_action_batch") if isinstance(ledger, dict) else None
    if not isinstance(batch, list):
        return None
    return next(
        (
            item for item in batch
            if isinstance(item, dict)
            and str(item.get("action_id") or "") == action_id
            and str(item.get("tool") or "") == tool
        ),
        None,
    )


def poll_goal(port_file: Path, goal_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = control_request(port_file, "goal.get", {"goal_id": goal_id}, timeout=8)
            if last.get("status") in {"complete", "blocked", "cancelled", "failed"}:
                return last
        except (AcceptanceFailure, RuntimeError, OSError, ValueError):
            pass
        time.sleep(1.0)
    return last


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for a real disposable Goal")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--provider-url", default="http://127.0.0.1:11435")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--outage-timeout", type=float, default=240.0)
    parser.add_argument("--recovery-timeout", type=float, default=300.0)
    parser.add_argument(
        "--auto-stop-provider",
        action="store_true",
        help="after the durable checkpoint, stop only a verified disposable loopback relay",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("provider recovery requires --live")
    if not 30 <= args.outage_timeout <= 900 or not 30 <= args.recovery_timeout <= 900:
        parser.error("invalid recovery timing bounds")

    root = Path(__file__).resolve().parents[1]
    profile = (root / "runtime" / "instances" / args.profile).resolve()
    sandbox = profile / "sandbox"
    journal = profile / "data" / "agent" / "action_journal.jsonl"
    port_file = profile / "data" / "interfaces" / "host" / "terminal" / "terminal.port"
    base = args.url.rstrip("/")
    provider = args.provider_url.rstrip("/")
    if profile.name != args.profile or not sandbox.is_dir():
        raise SystemExit("selected profile sandbox is missing or unsafe")
    if not port_file.is_file() or not journal.name.endswith(".jsonl"):
        raise SystemExit("selected profile native control/journal paths are missing")

    session_id = "unattended-provider-recovery-" + uuid4().hex[:10]
    marker = "UNATTENDED_PROVIDER_RECOVERY_" + uuid4().hex[:12]
    relative_file = f"sandbox/provider-recovery-{session_id}.txt"
    disk_file = sandbox / Path(relative_file).relative_to("sandbox")
    expected_sha = hashlib.sha256(marker.encode("utf-8")).hexdigest()
    report_path = args.report or root / "runtime" / (
        "unattended-provider-recovery-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "test": "unattended_provider_failure_after_durable_write",
        "profile": args.profile,
        "base_url": base,
        "provider_url": provider,
        "session_id": session_id,
        "marker": marker,
        "relative_file": relative_file,
        "expected_sha256": expected_sha,
        "goal": {},
        "outage": {},
        "restart": {},
        "postcondition": {},
        "journal": {},
        "cleanup": {},
        "unattended": {"enabled": False, "revoked": False},
        "pass": False,
        "failure": None,
    }

    def persist() -> Path:
        target = report_path if report_path.is_absolute() else root / report_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    session: requests.Session | None = None
    headers: dict[str, str] = {}
    goal_id = ""
    write = None
    automatic_stop: dict[str, Any] | None = None
    try:
        if not wait_provider_inference(provider, args.recovery_timeout):
            raise AcceptanceFailure("provider was not inference-ready before the recovery run")
        session, headers = bootstrap(base, args.recovery_timeout)
        restart = session.post(
            base + "/api/jawl/restart",
            headers=headers,
            json={"wait_for_memory": True},
            timeout=args.recovery_timeout,
        )
        if restart.status_code != 200 or restart.json().get("ok") is not True:
            raise AcceptanceFailure("JAWL preflight restart failed")
        time.sleep(15)

        policy = control_request(port_file, "hostos.policy.get", {}, timeout=30)
        report["policy"] = {
            "access_level": policy.get("access_level"),
            "access_name": policy.get("access_name"),
            "authority": policy.get("authority"),
        }
        if policy.get("access_level") != 3 or policy.get("access_name") != "ROOT":
            raise AcceptanceFailure(
                "provider recovery requires disposable profile access level 3/ROOT; "
                f"got {policy.get('access_name')} ({policy.get('access_level')})"
            )

        report["unattended"]["before"] = set_unattended(
            port_file, enabled=True, ttl_seconds=900, timeout=30
        )
        report["unattended"]["enabled"] = True
        goal = control_request(
            port_file,
            "goal.create",
            {
                "objective": (
                    "Perform a disposable provider-recovery checkpoint in the profile sandbox. "
                    f"First and only first action: call HostOSWriter.write_file on {relative_file} "
                    f"with exactly this text: {marker}. The write must be durable before the "
                    "Goal advances. Do not read, delete, send messages, or complete the Goal "
                    "in this first cycle; leave the Goal active for the next cycle."
                ),
                "verification_policy": "none",
                "wake": True,
            },
        )
        goal_id = str(goal.get("goal_id") or "")
        report["goal"]["created"] = goal
        if not goal_id or goal.get("status") != "active":
            raise AcceptanceFailure("provider-recovery Goal was not active")

        deadline = time.monotonic() + args.outage_timeout
        while time.monotonic() < deadline:
            write = marker_write_evidence(journal, marker)
            current = control_request(port_file, "goal.get", {"goal_id": goal_id}, timeout=8)
            if write is not None and current.get("status") == "active":
                report["goal"]["ready"] = current
                break
            if current.get("status") in {"complete", "blocked", "failed", "cancelled"}:
                raise AcceptanceFailure(
                    "Goal reached a terminal state before the provider-outage boundary"
                )
            time.sleep(0.5)
        else:
            raise AcceptanceFailure("durable write was not observed while Goal remained active")

        action_id = str(write.get("action_id") or "")
        plan_id = str(write.get("plan_id") or "")
        report["goal"]["write_action"] = {"action_id": action_id, "plan_id": plan_id}
        if args.auto_stop_provider:
            automatic_stop = stop_exact_disposable_provider(provider)
        print(json.dumps({
            "PROVIDER_FAILURE_READY": True,
            "provider_url": provider,
            "goal_id": goal_id,
            "marker": marker,
            "provider_stopped_automatically": args.auto_stop_provider,
            "instruction": "stop only the disposable provider now; restore the same endpoint afterwards",
        }, ensure_ascii=False), flush=True)

        outage_deadline = time.monotonic() + args.outage_timeout
        provider_down = False
        while time.monotonic() < outage_deadline:
            if not wait_http(provider + "/api/tags", 2):
                provider_down = True
                break
            time.sleep(1)
        report["outage"] = {
            "provider_failure_observed": provider_down,
            "automatic_stop": automatic_stop,
            "goal_before_restore": control_request(port_file, "goal.get", {"goal_id": goal_id}, timeout=8),
        }
        if not provider_down:
            raise AcceptanceFailure("provider outage was not observed before timeout")

        if not wait_provider_inference(provider, args.recovery_timeout):
            raise AcceptanceFailure("provider endpoint was not restored after the outage")
        report["outage"]["provider_restored"] = True

        restart = session.post(
            base + "/api/jawl/restart",
            headers=headers,
            json={"wait_for_memory": True},
            timeout=args.recovery_timeout,
        )
        restart_body = restart.json()
        report["restart"] = {"status": restart.status_code, "body": restart_body}
        if restart.status_code != 200 or restart_body.get("ok") is not True:
            raise AcceptanceFailure("JAWL did not restart after provider restoration")
        time.sleep(10)
        recovered = control_request(port_file, "goal.get", {"goal_id": goal_id}, timeout=30)
        report["restart"]["goal"] = recovered
        if recovered.get("status") != "active":
            raise AcceptanceFailure("restarted JAWL did not preserve the active recovery Goal")

        status, payload = native_action(
            base, headers, "HostOSReader.read_file", {"filepath": relative_file}, 60
        )
        disk_match = disk_file.is_file() and disk_file.read_text(encoding="utf-8") == marker
        disk_sha = hashlib.sha256(disk_file.read_bytes()).hexdigest() if disk_file.is_file() else ""
        report["postcondition"] = {
            "http_status": status,
            "native": payload.get("native") is True,
            "is_success": isinstance(payload.get("result"), dict) and payload["result"].get("is_success") is True,
            "file_exists": disk_file.is_file(),
            "disk_content_match": disk_match,
            "disk_sha256": disk_sha,
            "sha_matches": disk_sha == expected_sha,
            "reader_exposes_sha": expected_sha in str((payload.get("result") or {}).get("message") or ""),
        }
        if not disk_match or disk_sha != expected_sha:
            raise AcceptanceFailure("native readback did not prove the durable marker")

        recovered_action = goal_action(recovered, action_id, "HostOSWriter.write_file")
        report["goal"]["recovered_action"] = recovered_action
        if isinstance(recovered_action, dict) and recovered_action.get("status") in UNCERTAIN_STATUSES:
            ledger = control_request(
                port_file,
                "goal.ledger.update",
                {"patch": {
                    "phase": "reconciled",
                    "reconcile_actions": [{
                        "action_id": action_id,
                        "tool": "HostOSWriter.write_file",
                        "status": "confirmed",
                        "evidence": f"Independent native readback SHA-256: {disk_sha}",
                    }],
                    "checkpoint_summary": "Provider outage recovery postcondition confirmed.",
                }},
            )
            report["goal"]["ledger_reconciled"] = ledger
        completed = control_request(
            port_file,
            "goal.update",
            {"goal_id": goal_id, "status": "complete", "summary": "Provider outage recovery postcondition verified."},
        )
        report["goal"]["completed"] = completed
        if completed.get("status") != "complete":
            raise AcceptanceFailure("recovered Goal did not complete after reconciliation")

        actual_writes = successful_marker_writes(journal, marker)
        report["journal"] = {
            "path": str(journal),
            "actual_successful_writes": len(actual_writes),
            "target_plan_id": plan_id,
            "target_action_id": action_id,
        }
        if len(actual_writes) != 1:
            raise AcceptanceFailure("provider recovery did not prove exactly one real write")
    except (AcceptanceFailure, RuntimeError, OSError, ValueError, psutil.Error, requests.RequestException, json.JSONDecodeError) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if session is not None and headers and disk_file.exists():
            try:
                status, payload = native_action(
                    base, headers, "HostOSWriter.delete_file", {"filepath": relative_file}, 60
                )
                report["cleanup"] = {
                    "status": status,
                    "native": payload.get("native") is True,
                    "file_absent": not disk_file.exists(),
                }
            except Exception as exc:  # preserve the primary failure
                report["cleanup"] = {"file_absent": not disk_file.exists(), "error": f"{type(exc).__name__}: {exc}"}
        else:
            report["cleanup"] = {"file_absent": not disk_file.exists(), "delete_skipped": True}
        if report["unattended"].get("enabled"):
            try:
                report["unattended"]["after"] = set_unattended(
                    port_file, enabled=False, ttl_seconds=0, timeout=30
                )
                report["unattended"]["revoked"] = True
            except Exception as exc:
                report["unattended"]["revoke_error"] = f"{type(exc).__name__}: {exc}"
        report["acceptance"] = {
            "provider_failure_observed": report.get("outage", {}).get("provider_failure_observed") is True,
            "provider_restored": report.get("outage", {}).get("provider_restored") is True,
            "restart_goal_active": report.get("restart", {}).get("goal", {}).get("status") == "active",
            "postcondition_verified": report.get("postcondition", {}).get("sha_matches") is True,
            "exactly_one_actual_write": report.get("journal", {}).get("actual_successful_writes") == 1,
            "goal_completed": report.get("goal", {}).get("completed", {}).get("status") == "complete",
            "cleanup_complete": report.get("cleanup", {}).get("file_absent") is True,
            "unattended_revoked": report["unattended"].get("revoked") is True,
        }
        report["pass"] = report["failure"] is None and all(report["acceptance"].values())
        if not report["pass"] and report["failure"] is None:
            report["failure"] = "; ".join(key for key, value in report["acceptance"].items() if not value)
        target = persist()
        print(json.dumps({"report": str(target), "pass": report["pass"], "failure": report["failure"]}, ensure_ascii=False))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
