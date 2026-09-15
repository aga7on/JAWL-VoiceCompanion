"""Probe provider loss after a native action has become durable.

The provider is stopped by the operator outside this process.  This script
never kills a process.  It waits until a real JAWL turn is in flight, prints a
ready marker, records the failed stream, waits for the operator to restore the
same provider endpoint, then restarts JAWL and verifies the disposable file
through the native reader before recoverable cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from uuid import uuid4

import requests


class AcceptanceFailure(RuntimeError):
    pass


def parse_events(lines: list[str]) -> list[dict]:
    events: list[dict] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def final_event(lines: list[str]) -> dict:
    result = {}
    for event in parse_events(lines):
        if event.get("type") == "final" and isinstance(event.get("response"), dict):
            result = dict(event["response"])
    return result


def native_request(base: str, headers: dict[str, str], skill: str, arguments: dict, timeout: float) -> dict:
    response = requests.post(
        base + "/api/hostos/execute",
        headers=headers,
        json={"request": {"skill": skill, "arguments": arguments}},
        timeout=timeout,
    )
    payload = response.json()
    result = payload.get("result") if isinstance(payload, dict) else None
    if response.status_code != 200 or payload.get("ok") is not True or payload.get("native") is not True:
        raise AcceptanceFailure(f"{skill}: non-native HTTP {response.status_code}")
    if not isinstance(result, dict) or result.get("is_success") is not True:
        raise AcceptanceFailure(f"{skill}: unsuccessful native result")
    return {
        "skill": skill,
        "status": response.status_code,
        "native": True,
        "is_success": True,
        "message": str(result.get("message") or "")[:500],
    }


def journal_for_marker(path: Path, marker: str) -> list[dict]:
    if not path.is_file():
        return []
    output = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters")
        message = str(item.get("message") or "")
        if (isinstance(parameters, dict) and parameters.get("content") == marker) or marker in message:
            output.append(item)
    return output


def journal_entries(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    output = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            output.append(item)
    return output


def successful_marker_write(entries: list[dict], marker: str) -> bool:
    started = {
        (str(item.get("plan_id") or ""), str(item.get("action_id") or ""))
        for item in entries
        if item.get("event") == "action_started"
        and item.get("tool_name") == "HostOSWriter.write_file"
        and isinstance(item.get("parameters"), dict)
        and item["parameters"].get("content") == marker
    }
    return any(
        item.get("event") == "action_finished"
        and item.get("tool_name") == "HostOSWriter.write_file"
        and item.get("is_success") is True
        and (str(item.get("plan_id") or ""), str(item.get("action_id") or "")) in started
        and "idempotent no-op" not in str(item.get("message") or "").lower()
        for item in entries
    )


def wait_http(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=3).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def wait_provider_inference(base: str, timeout: float) -> bool:
    """Wait for the model, not just Ollama's metadata endpoint."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = requests.post(
                base + "/v1/chat/completions",
                json={
                    "model": "jawl-gemma4-it:latest",
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 1,
                    "temperature": 0,
                    "stream": False,
                },
                timeout=30,
            )
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for a disposable native action")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--provider-url", default="http://127.0.0.1:11435")
    parser.add_argument("--sandbox-dir", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--min-flight", type=float, default=8.0)
    parser.add_argument("--flight-timeout", type=float, default=240.0)
    parser.add_argument("--provider-recovery-timeout", type=float, default=240.0)
    parser.add_argument("--chat-timeout", type=float, default=300.0)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    if not args.live:
        parser.error("provider failure recovery requires --live")
    if not (1 <= args.min_flight <= 120 and 30 <= args.flight_timeout <= 900):
        parser.error("invalid flight timing bounds")

    base = args.url.rstrip("/")
    provider = args.provider_url.rstrip("/")
    sandbox = args.sandbox_dir.resolve()
    journal = args.journal.resolve()
    if sandbox.name != "sandbox" or not sandbox.is_dir():
        raise AcceptanceFailure("--sandbox-dir must be an existing profile sandbox")
    if not journal.name.endswith(".jsonl"):
        raise AcceptanceFailure("--journal must point to action_journal.jsonl")

    session_id = "provider-recovery-" + uuid4().hex[:10]
    marker = "PROVIDER_RECOVERY_OK_" + uuid4().hex[:12]
    relative_file = f"sandbox/provider-recovery-{session_id}.txt"
    disk_file = sandbox / Path(relative_file).relative_to("sandbox")
    content = marker
    expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    report_path = args.report or Path("runtime") / (
        "provider-failure-native-recovery-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report: dict = {
        "schema_version": 1,
        "test": "provider_failure_after_native_write_and_recovery",
        "base_url": base,
        "provider_url": provider,
        "session_id": session_id,
        "marker": marker,
        "relative_file": relative_file,
        "expected_sha256": expected_sha,
        "turn_a": {"events": [], "error": None},
        "restart": {},
        "turn_b": {"events": [], "error": None},
        "journal": {},
        "cleanup": {"actions": [], "file_absent": False},
        "pass": False,
        "failure": None,
    }

    def persist_report() -> Path:
        output = report_path if report_path.is_absolute() else Path(__file__).resolve().parents[1] / report_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return output

    session = requests.Session()
    boot = session.get(base + "/api/session", timeout=20)
    boot.raise_for_status()
    csrf = boot.json().get("csrf_token")
    cookie = SimpleCookie(boot.headers.get("Set-Cookie", "")).get("companion_session")
    if not isinstance(csrf, str) or not csrf or cookie is None:
        raise AcceptanceFailure("Companion session bootstrap was incomplete")
    headers = {
        "Origin": base,
        "Content-Type": "application/json",
        "X-Companion-CSRF": csrf,
        "X-Companion-Session": cookie.value,
    }

    # The managed profile may have been left in a provider-error state by a
    # previous run.  Recycle JAWL before creating the new marker so that the
    # first turn is a real provider-backed turn, not an error-envelope replay.
    if not wait_provider_inference(provider, args.provider_recovery_timeout):
        raise AcceptanceFailure("provider was not inference-ready before the preflight restart")
    preflight_restart = session.post(
        base + "/api/jawl/restart",
        headers=headers,
        json={"wait_for_memory": True},
        timeout=300,
    )
    if preflight_restart.status_code != 200 or preflight_restart.json().get("ok") is not True:
        raise AcceptanceFailure("JAWL preflight restart failed before provider-failure turn")
    # /api/jawl/restart reports process readiness, while SYSTEM_CORE_START can
    # still be consuming the first LLM turn.  Give that autonomous heartbeat a
    # bounded quiet window before the acceptance turn.
    time.sleep(20)

    turn_a: dict = {"events": [], "error": None, "started_at": datetime.now(timezone.utc).isoformat()}

    def stream_a() -> None:
        started = time.perf_counter()
        try:
            with session.post(
                base + "/api/chat/stream",
                headers=headers,
                json={
                    "text": (
                        f"Use HostOSWriter.write_file to create {relative_file} with exactly this text: {marker}. "
                        f"Then use HostOSReader.read_file on {relative_file}. "
                        "After that, perform eight additional sequential HostOSReader.read_file "
                        f"verifications of {relative_file}; do not answer until all eight are complete."
                    ),
                    "session_id": session_id,
                },
                stream=True,
                timeout=args.chat_timeout,
            ) as response:
                turn_a["status"] = response.status_code
                turn_a["events"] = [line.decode("utf-8", "replace") for line in response.iter_lines() if line]
        except Exception as exc:  # provider disconnect is the expected failure path
            turn_a["error"] = f"{type(exc).__name__}: {exc}"
        turn_a["elapsed_s"] = round(time.perf_counter() - started, 3)
        turn_a["done"] = True

    worker = threading.Thread(target=stream_a, name="provider-failure-turn", daemon=True)
    worker.start()
    flight_started = time.monotonic()
    flight_deadline = flight_started + args.flight_timeout
    while time.monotonic() < flight_deadline:
        marker_written = successful_marker_write(journal_entries(journal), marker)
        if (
            worker.is_alive()
            and not final_event(turn_a.get("events") or [])
            and time.monotonic() >= flight_started + args.min_flight
            and marker_written
        ):
            break
        if not worker.is_alive():
            break
        time.sleep(0.5)
    report["turn_a"]["ready_elapsed_s"] = round(time.monotonic() - flight_started, 3)
    report["turn_a"]["durable_write_observed"] = successful_marker_write(journal_entries(journal), marker)
    report["turn_a"]["ready_for_provider_stop"] = (
        worker.is_alive()
        and not final_event(turn_a.get("events") or [])
        and report["turn_a"]["durable_write_observed"]
    )
    print(
        json.dumps(
            {"PROVIDER_FAILURE_READY": report["turn_a"]["ready_for_provider_stop"], "provider_url": provider, "pid_action": "stop provider externally now", "marker": marker},
            ensure_ascii=False,
        ),
        flush=True,
    )
    if not report["turn_a"]["ready_for_provider_stop"]:
        # Never continue into restore/readback when the durable native effect
        # was not observed.  Continuing would let a later unrelated heartbeat
        # create a file and produce a misleading recovery report.
        worker.join(timeout=5)
        report["turn_a"].update({key: value for key, value in turn_a.items() if key not in {"events"}})
        report["turn_a"]["event_types"] = [event.get("type") for event in parse_events(turn_a.get("events") or [])]
        report["turn_a"]["events"] = turn_a.get("events") or []
        report["turn_a"]["terminal_error_event"] = "error" in report["turn_a"]["event_types"]
        report["turn_a"]["terminal_final_event"] = "final" in report["turn_a"]["event_types"]
        report["turn_a"]["provider_failure_observed"] = bool(turn_a.get("error")) or any(
            event.get("type") == "error" for event in parse_events(turn_a.get("events") or [])
        )
        report["turn_a"]["aborted_before_outage"] = True
        report["turn_a"]["worker_alive_after_abort"] = worker.is_alive()
        report["failure"] = "durable native write was not observed before the provider-outage boundary"
        report["acceptance"] = {"durable_write_observed": False}
        output = persist_report()
        print(json.dumps({"report": str(output), "pass": False, "acceptance": report["acceptance"]}, ensure_ascii=False))
        return 2
    worker.join(timeout=args.chat_timeout + 30)
    report["turn_a"].update({key: value for key, value in turn_a.items() if key not in {"events"}})
    report["turn_a"]["event_types"] = [event.get("type") for event in parse_events(turn_a.get("events") or [])]
    report["turn_a"]["events"] = turn_a.get("events") or []
    turn_a_final = final_event(turn_a.get("events") or [])
    report["turn_a"]["final_text"] = str(turn_a_final.get("text") or "")
    report["turn_a"]["terminal_error_event"] = "error" in report["turn_a"]["event_types"]
    report["turn_a"]["terminal_final_event"] = "final" in report["turn_a"]["event_types"]
    report["turn_a"]["provider_failure_observed"] = bool(turn_a.get("error")) or any(
        event.get("type") == "error" for event in parse_events(turn_a.get("events") or [])
    )
    if worker.is_alive():
        raise AcceptanceFailure("turn A did not terminate after the bounded provider-failure window")

    metadata_restored = wait_http(provider + "/api/tags", args.provider_recovery_timeout)
    restored = metadata_restored and wait_provider_inference(provider, args.provider_recovery_timeout)
    report["provider_restored"] = restored
    report["provider_metadata_restored"] = metadata_restored
    if not restored:
        raise AcceptanceFailure("provider endpoint was not restored within the bounded window")

    restart = session.post(base + "/api/jawl/restart", headers=headers, json={"wait_for_memory": True}, timeout=300)
    report["restart"] = {"status": restart.status_code, "body": restart.json()}
    restart_body = report["restart"]["body"]
    result_body = restart_body.get("result") if isinstance(restart_body, dict) else {}
    if restart.status_code != 200 or restart_body.get("ok") is not True or result_body.get("agent_ready") is not True:
        raise AcceptanceFailure("JAWL did not become ready after provider recovery")
    time.sleep(20)

    turn_b: dict = {"events": [], "error": None}
    try:
        with session.post(
            base + "/api/chat/stream",
            headers=headers,
            json={
                "text": (
                    f"Inspect {relative_file} after provider recovery. Call HostOSReader.read_file and report the "
                    "SHA-256 from its result. Do not rely on conversation memory."
                ),
                "session_id": session_id,
            },
            stream=True,
            timeout=args.chat_timeout,
        ) as response:
            turn_b["status"] = response.status_code
            turn_b["events"] = [line.decode("utf-8", "replace") for line in response.iter_lines() if line]
    except Exception as exc:
        turn_b["error"] = f"{type(exc).__name__}: {exc}"
    turn_b["event_types"] = [event.get("type") for event in parse_events(turn_b.get("events") or [])]
    turn_b["final_text"] = final_event(turn_b.get("events") or []).get("text", "")
    report["turn_b"] = turn_b

    entries = journal_for_marker(journal, marker)
    started_keys = {
        (str(item.get("plan_id") or ""), str(item.get("action_id") or ""))
        for item in entries
        if item.get("event") == "action_started"
        and item.get("tool_name") == "HostOSWriter.write_file"
    }
    actual_writes = [
        item
        for item in journal_entries(journal)
        if item.get("event") == "action_finished"
        and item.get("tool_name") == "HostOSWriter.write_file"
        and item.get("is_success") is True
        and (str(item.get("plan_id") or ""), str(item.get("action_id") or "")) in started_keys
        and "idempotent no-op" not in str(item.get("message") or "").lower()
    ]
    report["journal"] = {
        "path": str(journal),
        "marker_entries": len(entries),
        "actual_successful_writes": len(actual_writes),
        "action_tools": sorted({str(item.get("tool_name")) for item in entries}),
        "companion_turn_ids": sorted({str(item.get("companion_turn_id")) for item in entries if item.get("companion_turn_id")}),
    }
    disk_match = disk_file.is_file() and disk_file.read_text(encoding="utf-8") == content
    disk_sha = hashlib.sha256(disk_file.read_bytes()).hexdigest() if disk_file.is_file() else ""
    report["postcondition"] = {
        "file_exists": disk_file.is_file(),
        "disk_content_match": disk_match,
        "disk_sha256": disk_sha,
        "sha_matches": disk_sha == expected_sha,
        "exactly_one_actual_write": len(actual_writes) == 1,
    }

    if disk_file.exists():
        try:
            report["cleanup"]["actions"].append(native_request(base, headers, "HostOSWriter.delete_file", {"filepath": relative_file}, 60))
        except Exception as exc:
            report["cleanup"]["failure"] = f"{type(exc).__name__}: {exc}"
    report["cleanup"]["file_absent"] = not disk_file.exists()
    final_text = str(report["turn_b"].get("final_text") or "")
    report["acceptance"] = {
        "provider_failure_observed": report["turn_a"].get("provider_failure_observed") is True,
        "provider_failure_terminal": (
            report["turn_a"].get("terminal_error_event") is True
            and report["turn_a"].get("terminal_final_event") is True
            and report["turn_a"].get("error") is None
        ),
        "provider_restored": restored,
        "restart_ready": result_body.get("agent_ready") is True,
        "turn_b_final_present": bool(final_text),
        "readback_sha_reported": expected_sha in final_text,
        "disk_postcondition": disk_match and disk_sha == expected_sha,
        "exactly_one_actual_write": len(actual_writes) == 1,
        "cleanup_complete": report["cleanup"]["file_absent"],
    }
    report["pass"] = all(report["acceptance"].values())
    if not report["pass"]:
        report["failure"] = "; ".join(key for key, value in report["acceptance"].items() if not value)
    output = persist_report()
    print(json.dumps({"report": str(output), "pass": report["pass"], "acceptance": report.get("acceptance")}, ensure_ascii=False))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AcceptanceFailure, requests.RequestException, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"pass": False, "failure": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise SystemExit(2)
