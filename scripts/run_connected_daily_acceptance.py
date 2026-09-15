"""Run the connected daily Companion acceptance as one bounded scenario.

The profile must already be running.  This harness deliberately reuses the
real browser voice runner and the Companion's native JAWL control routes; it
does not call a local executor or write canonical memory itself.

Sequence:
memory remember/revise -> browser voice -> native write/read -> JAWL restart
-> memory recall and native read after restart -> native recoverable cleanup.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import requests

from run_connected_native_action_acceptance import AcceptanceFailure, native_action


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAVS = (
    ROOT / "runtime" / "synthetic-questions" / "question-01.wav",
    ROOT / "runtime" / "synthetic-questions" / "question-02.wav",
    ROOT / "runtime" / "synthetic-questions" / "question-03.wav",
)
DEFAULT_EXPECTED = ("статус", "короткие", "тестовый")
FIRST_VALUE = "connected daily value one"
REVISED_VALUE = "connected daily value two"


def loopback_url(value: str) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--url must not contain credentials, query parameters or fragments")
    host = parsed.hostname
    if not host:
        raise ValueError("--url has no hostname")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("refusing a non-loopback URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def json_response(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AcceptanceFailure(
            f"{response.request.method} {response.request.path_url} returned non-JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise AcceptanceFailure("Companion returned a non-object JSON payload")
    return payload


def memory_mutation(
    session: requests.Session,
    base: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = session.post(
        base + "/api/jawl/memory",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    data = json_response(response)
    if response.status_code != 200 or data.get("ok") is not True or data.get("native") is not True:
        raise AcceptanceFailure(f"canonical memory mutation failed: HTTP {response.status_code}")
    return data


def memory_contains(payload: dict[str, Any], key: str, value: str) -> bool:
    projection = payload.get("memory", payload)
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    return key in encoded and value in encoded


def wait_memory_contains(
    session: requests.Session,
    base: str,
    headers: dict[str, str],
    key: str,
    value: str,
    timeout: float,
) -> dict[str, Any]:
    """Wait for the native memory read route after a JAWL process restart.

    JAWL reports its control plane ready before the web process has necessarily
    completed the first database-backed memory projection.  A single GET here
    would turn that normal startup race into a false persistence failure.
    """

    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            response = session.get(base + "/api/jawl/memory", headers=headers, timeout=10)
            last = json_response(response)
            if response.status_code == 200 and memory_contains(last, key, value):
                return last
        except (requests.RequestException, AcceptanceFailure):
            pass
        time.sleep(2)
    raise AcceptanceFailure("revised canonical memory was not recalled after restart")


def jawl_health_ready(payload: dict[str, Any]) -> bool:
    """Return whether the JAWL control plane is usable after a restart.

    ``/api/health.status`` is an aggregate Companion status.  It is allowed
    to be ``degraded`` while optional adapters (VoiceMem/TTS) are reconnecting;
    that must not make a JAWL restart acceptance fail.  The durable acceptance
    only requires the JAWL control plane and its web route to be available.
    """

    components = payload.get("components")
    if not isinstance(components, dict):
        return False
    return (
        components.get("jawl") in {"online", "connected"}
        and components.get("jawl_web") == "online"
    )


def wait_jawl_online(
    session: requests.Session, base: str, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            response = session.get(base + "/api/health", timeout=5)
            last = json_response(response)
            if response.status_code == 200 and jawl_health_ready(last):
                return last
        except (requests.RequestException, AcceptanceFailure):
            pass
        time.sleep(2)
    raise AcceptanceFailure(f"JAWL control plane did not return ready after restart: {last}")


def run_voice(
    base: str,
    wavs: tuple[Path, ...],
    expected: tuple[str, ...],
    report_path: Path,
    evidence_dir: Path,
    timeout: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_browser_voice_e2e.py"),
        "--live",
        "--url",
        base,
        "--report",
        str(report_path),
        "--evidence-dir",
        str(evidence_dir),
    ]
    for wav, phrase in zip(wavs, expected):
        command.extend(("--wav", str(wav), f"--expected={phrase}"))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise AcceptanceFailure("browser voice acceptance timed out") from exc
    if not report_path.is_file():
        raise AcceptanceFailure(
            f"browser voice runner produced no report (exit {completed.returncode})"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("status") != "passed":
        raise AcceptanceFailure(
            f"browser voice acceptance failed: {str(report.get('failure') if isinstance(report, dict) else report)[:300]}"
        )
    return {
        "status": report.get("status"),
        "turns": len(report.get("turns") or []),
        "report": str(report_path),
        "runner_exit": completed.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required for a real connected profile")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--sandbox-dir", type=Path, required=True)
    parser.add_argument("--memory-key", default="")
    parser.add_argument("--voice-wav", action="append", type=Path, default=[])
    parser.add_argument("--voice-expected", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--voice-timeout", type=float, default=900.0)
    parser.add_argument("--report", type=Path, default=ROOT / "runtime" / "connected-daily-acceptance.json")
    parser.add_argument("--voice-report", type=Path, default=ROOT / "runtime" / "connected-daily-voice.json")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "runtime" / "browser-evidence" / "connected-daily")
    args = parser.parse_args()
    if not args.live:
        parser.error("connected daily acceptance requires --live")
    if not 5 <= args.timeout <= 300 or not 30 <= args.voice_timeout <= 1800:
        parser.error("invalid timeout bounds")

    base = loopback_url(args.url)
    sandbox = args.sandbox_dir.resolve()
    if sandbox.name != "sandbox" or not sandbox.is_dir():
        raise AcceptanceFailure("--sandbox-dir must be an existing profile sandbox")
    wavs = tuple(args.voice_wav or DEFAULT_WAVS)
    expected = tuple(args.voice_expected or DEFAULT_EXPECTED)
    if len(wavs) != len(expected) or len(wavs) < 3:
        raise AcceptanceFailure("voice wav and expected lists must contain at least three matching items")
    for wav in wavs:
        if not wav.is_file():
            raise AcceptanceFailure(f"voice fixture is missing: {wav}")

    memory_key = args.memory_key or f"acceptance.connected_daily.{uuid4().hex}"
    action_name = "connected-daily-" + uuid4().hex
    relative_dir = f"sandbox/{action_name}"
    relative_file = f"{relative_dir}/marker.txt"
    marker = f"CONNECTED_DAILY_OK_{uuid4().hex}"
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    voice_report = args.voice_report if args.voice_report.is_absolute() else ROOT / args.voice_report
    evidence_dir = args.evidence_dir if args.evidence_dir.is_absolute() else ROOT / args.evidence_dir
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "connected_daily_acceptance",
        "status": "failed",
        "base_url": base,
        "memory_key": memory_key,
        "relative_file": relative_file,
        "steps": [],
        "failure": None,
        "cleanup": {"file_absent": False, "directory_absent": False},
    }
    session = requests.Session()
    headers: dict[str, str] = {"Origin": base, "Accept": "application/json"}
    marker_exists = False
    directory_created = False
    try:
        bootstrap = session.get(base + "/api/session", timeout=args.timeout)
        session_data = json_response(bootstrap)
        csrf = session_data.get("csrf_token")
        cookie = session.cookies.get("companion_session")
        if bootstrap.status_code != 200 or not isinstance(csrf, str) or not csrf or not cookie:
            raise AcceptanceFailure("Companion session bootstrap was incomplete")
        headers.update({"X-Companion-CSRF": csrf, "X-Companion-Session": cookie})
        report["steps"].append("session_bootstrap")

        memory_base = {
            "memory_key": memory_key,
            "kind": "preference",
            "subject": "connected daily acceptance",
            "predicate": "value",
            "source": "connected-daily-acceptance",
            "confidence": 1.0,
        }
        memory_mutation(
            session, base, headers,
            {"operation": "remember", **memory_base, "value": FIRST_VALUE},
            args.timeout,
        )
        memory_mutation(
            session, base, headers,
            {"operation": "revise", "memory_key": memory_key, "kind": "preference",
             "subject": "connected daily acceptance", "predicate": "value",
             "value": REVISED_VALUE, "source": "connected-daily-acceptance",
             "confidence": 1.0, "provenance": {"actor": "acceptance"}},
            args.timeout,
        )
        report["steps"].append("canonical_memory_remember_revise")

        report["voice"] = run_voice(
            base, wavs, expected, voice_report, evidence_dir, args.voice_timeout
        )
        report["steps"].append("browser_voice_3_turns")

        report["native"] = []
        report["native"].append(native_action(
            base, headers, "HostOSWriter.create_directories", {"paths": [relative_dir]}, args.timeout
        ))
        directory_created = True
        report["native"].append(native_action(
            base, headers, "HostOSWriter.write_file",
            {"filepath": relative_file, "content": marker, "description": "connected daily marker"},
            args.timeout,
        ))
        marker_exists = (sandbox / action_name / "marker.txt").is_file()
        if not marker_exists:
            raise AcceptanceFailure("native write did not create the marker on disk")
        report["steps"].append("native_write_verified_before_restart")

        restart = session.post(
            base + "/api/jawl/restart", headers=headers,
            json={"wait_for_memory": True}, timeout=max(args.timeout, 120),
        )
        restart_payload = json_response(restart)
        if restart.status_code != 200 or restart_payload.get("ok") is not True:
            raise AcceptanceFailure(f"JAWL restart failed: HTTP {restart.status_code}")
        report["restart"] = restart_payload
        report["health_after_restart"] = wait_jawl_online(session, base, 240)
        report["steps"].append("jawl_restart_and_online")

        recalled_payload = wait_memory_contains(
            session, base, headers, memory_key, REVISED_VALUE, max(args.timeout, 120)
        )
        report["memory_after_restart"] = {
            "status": 200,
            "revised_value_found": True,
            "projection_keys": sorted(recalled_payload.keys()),
        }
        report["steps"].append("canonical_memory_recalled_after_restart")

        readback = native_action(
            base, headers, "HostOSReader.read_file", {"filepath": relative_file}, args.timeout
        )
        if marker not in readback["message_excerpt"] and not (sandbox / action_name / "marker.txt").read_text(encoding="utf-8") == marker:
            raise AcceptanceFailure("native read after restart did not verify the marker")
        report["native"].append(readback)
        report["steps"].append("native_read_verified_after_restart")
    except (AcceptanceFailure, OSError, ValueError, json.JSONDecodeError, requests.RequestException) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        marker_path = sandbox / action_name / "marker.txt"
        action_dir = sandbox / action_name
        if marker_path.exists():
            try:
                report.setdefault("cleanup_actions", []).append(
                    native_action(base, headers, "HostOSWriter.delete_file", {"filepath": relative_file}, args.timeout)
                )
            except Exception as exc:
                report["failure"] = report["failure"] or f"cleanup delete_file: {type(exc).__name__}: {exc}"
        report["cleanup"]["file_absent"] = not marker_path.exists()
        if directory_created and action_dir.exists():
            try:
                report.setdefault("cleanup_actions", []).append(
                    native_action(base, headers, "HostOSWriter.delete_directory", {"path": relative_dir}, args.timeout)
                )
            except Exception as exc:
                report["failure"] = report["failure"] or f"cleanup delete_directory: {type(exc).__name__}: {exc}"
        report["cleanup"]["directory_absent"] = not action_dir.exists()
        if report["failure"] is None and report["cleanup"]["file_absent"] and report["cleanup"]["directory_absent"]:
            report["status"] = "passed"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={report_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
