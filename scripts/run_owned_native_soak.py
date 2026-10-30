"""Native Goal/Heartbeat soak under exact launcher and model Job ownership.

Called by run_owned_gateway_acceptance --suite soak. No physical devices,
foreign services, raw context, command lines or private Goal text are exported.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

from jawl_voicecompanion.owned_resource_sampler import OwnedResourceSampler
from run_goal_reconciliation_live import bootstrap, control_request
from run_unattended_goal_soak import run_cycle, set_unattended

ROOT = Path(__file__).resolve().parents[1]


def queue_counters(status):
    heartbeat = status.get("heartbeat")
    if not isinstance(heartbeat, dict):
        raise ValueError("native queue counters are missing")
    buffers = {"wake": heartbeat.get("wake_queue")}
    react = heartbeat.get("react_buffers", {})
    for name in ("realtime", "steer"):
        buffers[name] = react.get(name) if isinstance(react, dict) else None
    result = {}
    for name, buffer in buffers.items():
        if not isinstance(buffer, dict):
            raise ValueError("native queue counters are incomplete")
        values = {key: buffer.get(key) for key in ("size", "capacity", "coalesced_total", "dropped_total")}
        if (any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values.values())
                or not 1 <= values["capacity"] <= 10000 or values["size"] > values["capacity"]):
            raise ValueError("native queue counter bound failed")
        result[name] = values
    return result


def project_cycle(item):
    """Keep observable outcomes; native thought/Goal payloads stay native."""
    result = {key: item[key] for key in ("cycle", "goal_id", "status", "duration_seconds", "journal",
              "postcondition", "cleanup", "unexpected_tools", "forbidden_goal_actions",
              "goal_last_cycle_status", "goal_continuation_count", "goal_pending_work",
              "no_progress_guard_triggered") if key in item}
    if item.get("failure"):
        result["failure"] = item["failure"][:400]
    ledger = item.get("terminal_ledger", {})
    result["terminal_ledger"] = {key: ledger.get(key) for key in (
        "phase", "last_action_batch_all_success", "has_required_step")}
    result["terminal_ledger"].update({key + "_count": len(ledger.get(key) or [])
                                     for key in ("completed_steps", "pending_steps", "blockers")})
    result["goal_status"] = item.get("goal_terminal", {}).get("status")
    return result


def run_soak(base, control_base, token, profile, source, run_root, owners, brain,
             *, duration_seconds, interval_seconds=300, sample_seconds=30):
    if not 30 <= duration_seconds <= 28800:
        raise ValueError("soak duration must be 30 seconds to eight hours")
    home = ROOT / "runtime/instances" / profile
    port_file = home / "data/interfaces/host/terminal/terminal.port"
    journal = home / "data/agent/action_journal.jsonl"
    checkpoint = Path(run_root) / "soak-checkpoint.json"
    report = {"pass": False, "status": "running", "scope": "native model/agent/Goal/Companion; no physical mic/audio/capture",
              "duration_requested_seconds": duration_seconds, "started_at": datetime.now(timezone.utc).isoformat(),
              "cycles": [], "resource_samples": [], "fault": {}, "lease": {"revoked": False}}
    sampler = OwnedResourceSampler(owners)
    lock = threading.RLock()
    stopped = threading.Event()
    sampling_errors = []
    session = None
    started = time.monotonic()

    def persist():
        with lock:
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            temporary = checkpoint.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, checkpoint)

    def sample():
        # Single sampler lock protects CPU deltas between poller and goal probes.
        with lock:
            current = sampler.sample()
            if not current["process_count"]:
                raise RuntimeError("owned resource sample is empty")
            current["elapsed_seconds"] = round(time.monotonic() - started, 3)
            current["queues"] = queue_counters(control_request(port_file, "status.get", {}, timeout=10))
            current["log_bytes"] = sum(p.stat().st_size for p in (home / "logs").glob("*") if p.is_file())
            current["journal_bytes"] = journal.stat().st_size if journal.exists() else 0
            if current["log_bytes"] > 128 * 1024 * 1024 or current["journal_bytes"] > 32 * 1024 * 1024:
                raise RuntimeError("native log/journal growth exceeded soak bound")
            # Include model memory; allow normal warm allocations but detect runaway RSS.
            if current["rss_bytes"] > 64 * 1024 ** 3:
                raise RuntimeError("owned aggregate RSS exceeded 64GiB soak bound")
            report["resource_samples"].append(current)
            return current

    def poll_resources():
        while not stopped.wait(sample_seconds):
            try:
                sample()
                persist()
            except Exception as exc:
                sampling_errors.append(type(exc).__name__ + ": " + str(exc)[:200])
                stopped.set()

    thread = threading.Thread(target=poll_resources, name="owned-soak-resources", daemon=True)
    try:
        session, headers = bootstrap(control_base, 10)
        policy = control_request(port_file, "hostos.policy.get", {}, timeout=10)
        if policy.get("access_level") != 3:
            raise RuntimeError("disposable native soak requires explicit ROOT profile")
        issued = set_unattended(port_file, enabled=True, ttl_seconds=int(duration_seconds) + 300, timeout=10)
        report["lease"]["enabled"] = issued.get("unattended", {}).get("enabled") is True
        sample()
        persist()
        thread.start()
        cycle = 0
        while time.monotonic() - started < duration_seconds:
            if sampling_errors:
                raise RuntimeError(sampling_errors[0])
            cycle += 1
            item = run_cycle(session=session, headers=headers, base=control_base, port_file=port_file,
                             profile=home, source=Path(source), journal=journal, cycle=cycle,
                             goal_timeout=180, poll_seconds=1, http_timeout=15, resource_sampler=sample)
            report["cycles"].append(project_cycle(item))
            from verify_jawl_snapshot import verify
            verify(Path(source))
            persist()
            if item.get("status") != "passed":
                raise RuntimeError("native Goal cycle failed: " + str(item.get("failure", "unknown"))[:300])
            if cycle == 1:
                # Fault only the model Job this driver created, between durable
                # tasks. Native correlated delivery must error once, then recover.
                from run_owned_gateway_acceptance import gateway
                brain.stop()
                failure = gateway(base, token, 1, probes=False, failure=True)
                report["fault"]["one_error"] = bool(failure["scoped_event_counts"].get("turn.error") == 1
                    and not failure["scoped_event_counts"].get("assistant.final"))
                if not report["fault"]["one_error"] or not brain.start().ok:
                    raise RuntimeError("owned provider fault/restart failed")
                recovery = gateway(base, token, 1, probes=False)
                report["fault"]["recovered"] = recovery["pass"]
                if not recovery["pass"]:
                    raise RuntimeError("native delivery after provider restart failed")
                persist()
            remaining = duration_seconds - (time.monotonic() - started)
            if remaining > 0:
                stopped.wait(min(interval_seconds, remaining))
        if sampling_errors:
            raise RuntimeError(sampling_errors[0])
        report["pass"] = bool(report["cycles"]) and bool(report["fault"].get("recovered"))
        report["status"] = "passed" if report["pass"] else "failed"
    except Exception as exc:
        report.update(status="failed", failure=type(exc).__name__ + ": " + str(exc)[:400])
    finally:
        stopped.set()
        if thread.is_alive():
            thread.join(timeout=10)
        report["sampler_stopped"] = not thread.is_alive()
        if report["lease"].get("enabled"):
            try:
                set_unattended(port_file, enabled=False, ttl_seconds=0, timeout=10)
                report["lease"]["revoked"] = True
            except Exception as exc:
                report["lease"]["revoke_error"] = type(exc).__name__
        if session is not None:
            session.close()
        report["pass"] = report["pass"] and report["sampler_stopped"] and report["lease"]["revoked"]
        report["status"] = "passed" if report["pass"] else "failed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        persist()
    return report
