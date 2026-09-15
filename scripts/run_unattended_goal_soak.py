"""Live unattended Goal/Heartbeat soak on a disposable integrated profile.

The harness creates bounded sandbox-only goals through JAWL's native control
socket and then steps out of the execution path. JAWL's Heartbeat/ReAct loop
must perform the native write and finish the goal without a per-action prompt.
The harness independently verifies the durable journal, the file postcondition,
resource samples, and recoverable cleanup. It can run a short smoke or the
production acceptance duration (up to eight hours).

This is intentionally separate from the crash-boundary harness: it does not
kill processes, does not restart the profile, and never touches a path outside
the selected disposable profile sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import psutil
import requests

try:
    from run_goal_reconciliation_live import (
        AcceptanceFailure,
        bootstrap,
        control_request,
        native_action,
        read_jsonl,
    )
except ModuleNotFoundError:  # importable from the repository test runner
    from scripts.run_goal_reconciliation_live import (
        AcceptanceFailure,
        bootstrap,
        control_request,
        native_action,
        read_jsonl,
    )


MAX_DURATION_SECONDS = 8 * 60 * 60
EXPECTED_TOOLS = {
    "HostOSWriter.write_file",
    "HostOSReader.read_file",
}
TERMINAL_PHASES = {"done", "complete", "completed"}
FORBIDDEN_GOAL_ACTIONS = (
    "GoalSkills.update_goal",
    "execute_skill",
    "set_current_goal",
)


def terminal_ledger_evidence(goal: dict[str, Any]) -> dict[str, Any]:
    """Project the bounded proof required for a completed unattended Goal."""

    ledger = goal.get("task_ledger") if isinstance(goal, dict) else None
    ledger = ledger if isinstance(ledger, dict) else {}
    completed_steps = ledger.get("completed_steps") or []
    pending_steps = ledger.get("pending_steps") or []
    blockers = ledger.get("blockers") or []
    next_action = str(ledger.get("next_action") or "").strip().casefold()
    action_batch = ledger.get("last_action_batch") or []
    actions_successful = bool(action_batch) and all(
        isinstance(action, dict)
        and str(action.get("status") or "").strip().casefold() == "success"
        for action in action_batch
    )
    return {
        "phase": str(ledger.get("current_phase") or "").strip().casefold(),
        "completed_steps": completed_steps,
        "pending_steps": pending_steps,
        "next_action": next_action,
        "blockers": blockers,
        "last_action_batch": action_batch,
        "last_action_batch_all_success": actions_successful,
        "has_required_step": "file created and verified" in completed_steps,
    }


def forbidden_goal_actions(goal: dict[str, Any]) -> list[str]:
    """Find forbidden legacy Goal calls recorded in durable Goal evidence."""

    ledger = goal.get("task_ledger") if isinstance(goal, dict) else None
    ledger = ledger if isinstance(ledger, dict) else {}
    sources: list[str] = []
    evidence = goal.get("evidence") if isinstance(goal, dict) else None
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                sources.extend(
                    str(item.get(field) or "")
                    for field in ("kind", "summary")
                )
    failed_attempts = ledger.get("failed_attempts")
    if isinstance(failed_attempts, list):
        for item in failed_attempts:
            if isinstance(item, dict):
                sources.extend(
                    str(item.get(field) or "")
                    for field in ("action", "reason")
                )
    last_action_tools = goal.get("last_action_tools") if isinstance(goal, dict) else None
    if isinstance(last_action_tools, list):
        sources.extend(str(item or "") for item in last_action_tools)
    haystack = "\n".join(sources).casefold()
    return [name for name in FORBIDDEN_GOAL_ACTIONS if name.casefold() in haystack]


def sample_owned_processes(profile: Path, source: Path) -> dict[str, Any]:
    """Return bounded RSS/CPU samples without exposing command lines."""

    profile = profile.resolve()
    source = source.resolve()
    samples: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            # The integrated launcher passes the profile/source through the
            # child environment, not argv.  Matching both tokens in cmdline
            # therefore produced a misleading zero-sample report.  The owned
            # JAWL workers run with the disposable profile as cwd; source is
            # retained as a conservative fallback for supervisor variants.
            cwd = None
            try:
                cwd = Path(process.cwd()).resolve()
            except (psutil.Error, OSError, RuntimeError, ValueError):
                pass
            in_profile = cwd == profile or (cwd is not None and profile in cwd.parents)
            command = " ".join(process.info.get("cmdline") or []).replace("/", "\\").casefold()
            source_token = str(source).replace("/", "\\").casefold()
            if not in_profile and source_token not in command:
                continue
            memory = process.info.get("memory_info")
            samples.append(
                {
                    "pid": int(process.pid),
                    "rss_mb": round((memory.rss if memory else 0) / (1024 * 1024), 2),
                    "cpu_percent": round(float(process.cpu_percent(interval=None)), 2),
                }
            )
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return {
        "processes": samples[:12],
        "count": len(samples),
        "matching": "profile_cwd_or_source_argv",
    }


def journal_cycle_evidence(journal: Path, marker: str) -> dict[str, Any]:
    entries = read_jsonl(journal)
    started = [
        item
        for item in entries
        if item.get("event") == "action_started"
        and isinstance(item.get("parameters"), dict)
        and item["parameters"].get("content") == marker
    ]
    plan_ids = {
        str(item.get("plan_id") or "")
        for item in entries
        if item.get("event") == "action_started"
        and isinstance(item.get("parameters"), dict)
        and item["parameters"].get("content") == marker
    }
    started_ids = {
        (str(item.get("plan_id") or ""), str(item.get("action_id") or ""))
        for item in entries
        if item.get("event") == "action_started"
        and str(item.get("plan_id") or "") in plan_ids
        and item.get("action_id")
    }
    finished = [
        item
        for item in entries
        if item.get("event") == "action_finished"
        and (
            str(item.get("plan_id") or ""),
            str(item.get("action_id") or ""),
        ) in started_ids
    ]
    successful = [
        item
        for item in finished
        if item.get("is_success") is True
        and item.get("tool_name") == "HostOSWriter.write_file"
        and "idempotent no-op" not in str(item.get("message") or "").casefold()
    ]
    idempotent_noops = [
        item
        for item in finished
        if item.get("is_success") is True
        and item.get("tool_name") == "HostOSWriter.write_file"
        and "idempotent no-op" in str(item.get("message") or "").casefold()
    ]
    tools = sorted(
        {
            str(item.get("tool_name") or "")
            for item in entries
            if item.get("event") == "action_started"
            and str(item.get("plan_id") or "") in plan_ids
        }
    )
    return {
        "action_started_count": len(started),
        "action_finished_count": len(finished),
        "successful_target_writes": len(successful),
        "idempotent_noop_writes": len(idempotent_noops),
        "tools_seen": tools[:40],
        "journal_entries": len(entries),
    }


def set_unattended(
    port_file: Path,
    *,
    enabled: bool,
    ttl_seconds: int,
    timeout: float,
) -> dict[str, Any]:
    action = "hostos.autonomy.issue" if enabled else "hostos.autonomy.revoke"
    params = (
        {
            "confirm": True,
            "ttl_seconds": ttl_seconds,
            "actor": "live-unattended-goal-soak",
        }
        if enabled
        else {
            "actor": "live-unattended-goal-soak",
            "reason": "unattended goal soak finished",
        }
    )
    policy = control_request(port_file, action, params, timeout=timeout)
    state = policy.get("unattended")
    if not isinstance(state, dict):
        raise AcceptanceFailure("unattended policy response has no lease state")
    if enabled and state.get("enabled") is not True:
        raise AcceptanceFailure("unattended lease was not enabled")
    if not enabled and state.get("enabled") is True:
        raise AcceptanceFailure("unattended lease was not revoked")
    return policy


def wait_for_goal(
    port_file: Path,
    goal_id: str,
    timeout: float,
    *,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = control_request(port_file, "goal.get", {"goal_id": goal_id}, timeout=8)
            if last.get("status") in {"complete", "blocked", "cancelled", "failed"}:
                return last
        except (AcceptanceFailure, RuntimeError, OSError, ValueError):
            pass
        time.sleep(poll_seconds)
    raise AcceptanceFailure(
        f"goal {goal_id} did not reach a terminal state within {timeout:.1f}s; "
        f"last_cycle={last.get('last_cycle_status', 'unknown')}"
    )


def cleanup_cycle_target(
    *,
    base: str,
    headers: dict[str, str],
    relative_file: str,
    disk_file: Path,
    timeout: float,
) -> dict[str, Any]:
    """Remove a cycle fixture through the native route, including failed cycles."""

    if not disk_file.exists():
        return {"file_absent": True, "delete_skipped": True}
    status, payload = native_action(
        base,
        headers,
        "HostOSWriter.delete_file",
        {"filepath": relative_file},
        timeout,
    )
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return {
        "http_status": status,
        "native": payload.get("native") is True,
        "is_success": result.get("is_success") is True,
        "file_absent": not disk_file.exists(),
    }


def run_cycle(
    *,
    session: requests.Session,
    headers: dict[str, str],
    base: str,
    port_file: Path,
    profile: Path,
    source: Path,
    journal: Path,
    cycle: int,
    goal_timeout: float,
    poll_seconds: float,
    http_timeout: float,
) -> dict[str, Any]:
    run_id = uuid4().hex[:12]
    marker = f"UNATTENDED_SOAK_{cycle:04d}_{run_id}"
    relative_file = f"sandbox/unattended-soak-{cycle:04d}-{run_id}.txt"
    disk_file = profile / "sandbox" / Path(relative_file).relative_to("sandbox")
    started_at = time.monotonic()
    item: dict[str, Any] = {
        "cycle": cycle,
        "marker": marker,
        "relative_file": relative_file,
        "expected_tools": sorted(EXPECTED_TOOLS),
        "status": "failed",
    }
    goal = control_request(
        port_file,
        "goal.create",
        {
            "objective": (
                "Complete one unattended disposable acceptance task. Use only "
                f"HostOSWriter.write_file to create {relative_file} with exactly "
                f"this text: {marker}, then use HostOSReader.read_file to verify "
                "the marker. Do not access any path outside the profile sandbox, "
                "do not send messages, do not use terminal or other tools. "
                "After the read succeeds, first apply the canonical Goal Protocol "
                "v2 terminal ledger patch: phase=completed, "
                "completed_add=[\"file created and verified\"], "
                "pending_steps=[], next_action=none, blockers=[]. Then emit "
                "exactly one compact Goal Protocol v2 state=done envelope with "
                "a concise evidence summary; the ledger patch is mandatory "
                "evidence. This acceptance task deliberately tests the direct "
                "Goal-v2 terminal envelope, not the legacy GoalSkills lifecycle: "
                "do not call execute_skill as a native tool, do not call "
                "GoalSkills.update_goal, and do not call set_current_goal. If a "
                "generic prompt suggests update_goal, that instruction does not "
                "apply to this explicitly scoped acceptance objective; emit the "
                "direct state=done envelope after the verified read instead."
            ),
            "verification_policy": "none",
            "wake": True,
        },
    )
    goal_id = str(goal.get("goal_id") or "")
    if not goal_id or goal.get("status") != "active":
        raise AcceptanceFailure("unattended goal.create did not return an active goal")
    item["goal_id"] = goal_id
    item["goal_created"] = goal
    item["resource_before"] = sample_owned_processes(profile, source)
    try:
        terminal = wait_for_goal(
            port_file,
            goal_id,
            goal_timeout,
            poll_seconds=poll_seconds,
        )
        item["goal_terminal"] = terminal
        item["resource_after_goal"] = sample_owned_processes(profile, source)
        item["terminal_ledger"] = terminal_ledger_evidence(terminal)
        item["forbidden_goal_actions"] = forbidden_goal_actions(terminal)
        item["journal"] = journal_cycle_evidence(journal, marker)
        observed_tools = set(item["journal"]["tools_seen"])
        unexpected = sorted(observed_tools - EXPECTED_TOOLS)
        item["unexpected_tools"] = unexpected
        if terminal.get("status") != "complete":
            raise AcceptanceFailure(f"unattended goal ended as {terminal.get('status')}")
        ledger = item["terminal_ledger"]
        if ledger["phase"] not in TERMINAL_PHASES:
            raise AcceptanceFailure("completed Goal did not expose a terminal ledger phase")
        if ledger["pending_steps"] or ledger["blockers"]:
            raise AcceptanceFailure("completed Goal retained pending steps or blockers")
        if ledger["next_action"] not in {"", "none", "n/a", "null"}:
            raise AcceptanceFailure("completed Goal retained a next action")
        if not ledger["has_required_step"]:
            raise AcceptanceFailure("completed Goal did not record the verified acceptance step")
        if not ledger["last_action_batch_all_success"]:
            raise AcceptanceFailure("completed Goal did not expose an all-successful last action batch")
        if unexpected:
            raise AcceptanceFailure("unattended goal used unexpected native tools: " + ", ".join(unexpected))
        if item["forbidden_goal_actions"]:
            raise AcceptanceFailure(
                "unattended goal used forbidden legacy Goal actions: "
                + ", ".join(item["forbidden_goal_actions"])
            )
        if item["journal"]["successful_target_writes"] != 1:
            raise AcceptanceFailure("unattended journal did not prove exactly one successful target write")

        read_status, read_payload = native_action(
            base,
            headers,
            "HostOSReader.read_file",
            {"filepath": relative_file},
            http_timeout,
        )
        file_exists = disk_file.is_file()
        content = disk_file.read_text(encoding="utf-8") if file_exists else ""
        sha = hashlib.sha256(disk_file.read_bytes()).hexdigest() if file_exists else ""
        item["postcondition"] = {
            "http_status": read_status,
            "native": read_payload.get("native") is True,
            "is_success": (read_payload.get("result") or {}).get("is_success") is True,
            "file_exists": file_exists,
            "marker_present": content == marker,
            "sha256": sha,
        }
        if not item["postcondition"]["marker_present"]:
            raise AcceptanceFailure("unattended goal completed without the exact file postcondition")

        item["status"] = "passed"
    except Exception as exc:
        item["status"] = "failed"
        item["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if not item.get("cleanup", {}).get("file_absent"):
            try:
                item["cleanup"] = cleanup_cycle_target(
                    base=base,
                    headers=headers,
                    relative_file=relative_file,
                    disk_file=disk_file,
                    timeout=http_timeout,
                )
                if not item["cleanup"].get("file_absent"):
                    item["status"] = "failed"
                    item.setdefault("failure", "unattended cleanup did not remove the disposable file")
            except Exception as exc:
                item["status"] = "failed"
                item["cleanup_error"] = f"{type(exc).__name__}: {exc}"
                item.setdefault("failure", "unattended cleanup failed")
        item["duration_seconds"] = round(time.monotonic() - started_at, 3)
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required for a real profile")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--duration-seconds", type=float, default=300.0)
    parser.add_argument("--cycles", type=int, default=0, help="0 means run until duration expires")
    parser.add_argument("--goal-timeout", type=float, default=240.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--http-timeout", type=float, default=30.0)
    parser.add_argument("--unattended-ttl", type=int, default=0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("unattended soak requires --live")
    if not 30 <= args.duration_seconds <= MAX_DURATION_SECONDS:
        parser.error(f"--duration-seconds must be between 30 and {MAX_DURATION_SECONDS}")
    if not 0 <= args.cycles <= 1000:
        parser.error("--cycles must be between 0 and 1000")
    if not 30 <= args.goal_timeout <= 1800:
        parser.error("--goal-timeout must be between 30 and 1800")
    if not 0 <= args.unattended_ttl <= 86400:
        parser.error("--unattended-ttl must be between 0 and 86400")
    if not 0.5 <= args.poll_seconds <= 30 or not 0 <= args.interval_seconds <= 3600:
        parser.error("invalid poll/interval bounds")

    root = Path(__file__).resolve().parents[1]
    profile = (root / "runtime" / "instances" / args.profile).resolve()
    source = (root / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2").resolve()
    if profile.name != args.profile or not (profile / "sandbox").is_dir():
        raise SystemExit("selected profile sandbox is missing or unsafe")
    if not source.is_dir():
        raise SystemExit("pinned JAWL source snapshot is missing")
    manifest_path = source / "SOURCE_MANIFEST.json"
    if not manifest_path.is_file():
        raise SystemExit("pinned JAWL source manifest is missing")
    try:
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read pinned JAWL source manifest: {exc}") from exc
    port_file = profile / "data" / "interfaces" / "host" / "terminal" / "terminal.port"
    journal = profile / "data" / "agent" / "action_journal.jsonl"
    base = args.url.rstrip("/")
    report_path = args.report or root / "runtime" / (
        "unattended-goal-soak-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "test": "live_unattended_goal_heartbeat_soak",
        "profile": args.profile,
        "source_snapshot": {
            "path": str(source),
            "digest": source_manifest.get("snapshot_sha256") or source_manifest.get("digest"),
            "file_count": source_manifest.get("file_count") or len(source_manifest.get("files", {})),
        },
        "base_url": base,
        "duration_requested_seconds": args.duration_seconds,
        "cycles_requested": args.cycles,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cycles": [],
        "resource_samples": [],
        "status": "failed",
        "pass": False,
        "failure": None,
        "unattended": {"enabled": False, "revoked": False},
    }
    session: requests.Session | None = None
    headers: dict[str, str] = {}
    started = time.monotonic()
    try:
        session, headers = bootstrap(base, args.http_timeout)
        lease_ttl = args.unattended_ttl or min(
            86400, max(300, int(args.duration_seconds) + 300)
        )
        report["unattended"]["ttl_seconds"] = lease_ttl
        report["unattended"]["before"] = set_unattended(
            port_file,
            enabled=True,
            ttl_seconds=lease_ttl,
            timeout=args.http_timeout,
        )
        report["unattended"]["enabled"] = True
        cycle = 0
        while time.monotonic() - started < args.duration_seconds:
            if args.cycles and cycle >= args.cycles:
                break
            cycle += 1
            try:
                item = run_cycle(
                    session=session,
                    headers=headers,
                    base=base,
                    port_file=port_file,
                    profile=profile,
                    source=source,
                    journal=journal,
                    cycle=cycle,
                    goal_timeout=min(args.goal_timeout, max(30.0, args.duration_seconds)),
                    poll_seconds=args.poll_seconds,
                    http_timeout=args.http_timeout,
                )
                report["cycles"].append(item)
                report["resource_samples"].extend(
                    [item.get("resource_before", {}), item.get("resource_after_goal", {})]
                )
                if item.get("status") != "passed":
                    report["failure"] = f"cycle {cycle}: {item.get('failure', 'cycle failed')}"
                    break
            except Exception as exc:
                report["failure"] = f"cycle {cycle}: {type(exc).__name__}: {exc}"
                break
            if args.interval_seconds:
                time.sleep(min(args.interval_seconds, max(0.0, args.duration_seconds - (time.monotonic() - started))))
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["cycles_completed"] = len(report["cycles"])
        report["status"] = "passed" if report["failure"] is None and report["cycles_completed"] >= (args.cycles or 1) else "failed"
        report["pass"] = report["status"] == "passed"
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if report["unattended"].get("enabled"):
            try:
                report["unattended"]["after"] = set_unattended(
                    port_file,
                    enabled=False,
                    ttl_seconds=0,
                    timeout=args.http_timeout,
                )
                report["unattended"]["revoked"] = True
            except Exception as exc:
                report["unattended"]["revoke_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "pass": report["pass"], "failure": report["failure"], "cycles_completed": len(report["cycles"])}, ensure_ascii=False))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
