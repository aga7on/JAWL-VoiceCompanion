"""Opt-in live matrix for JAWL's native HostOS authority.

The profile talks only to an already running, authenticated JAWL web console.
It never starts a process, accepts a remote URL, or calls a Companion-local
executor.  Use a disposable JAWL instance and disposable paths when enabling
the level-changing and write exercises.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class ProfileFailure(RuntimeError):
    """A live policy assertion failed."""


def _loopback_url(value: str) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--url must not contain credentials, query parameters or fragments")
    host = parsed.hostname
    if not host:
        raise ValueError("--url has no hostname")
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("refusing a non-loopback URL")
    except ValueError as exc:
        if "non-loopback" in str(exc):
            raise
        try:
            addresses = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
        except OSError as dns_exc:
            raise ValueError("cannot resolve --url hostname") from dns_exc
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses
        ):
            raise ValueError("refusing a non-loopback URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _request(
    base_url: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Console-Token"] = token
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(base_url + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(512 * 1024)
            return int(response.status), json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        try:
            raw = exc.read(512 * 1024)
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        return int(exc.code), parsed
    except (URLError, OSError, TimeoutError) as exc:
        raise ProfileFailure(f"JAWL request failed for {path}: {type(exc).__name__}") from exc


def _wait_agent(
    base_url: str,
    *,
    token: str,
    running: bool,
    access_level: int | None = None,
    timeout: float = 90,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, payload = _request(base_url, "/api/agent/status", token=token)
        last = payload
        if (
            status == 200
            and payload.get("running") is running
            and not payload.get("starting")
            and not payload.get("stopping")
        ):
            if not running:
                return payload
            policy_status, policy_payload = _request(
                base_url, "/api/hostos/policy", token=token
            )
            policy = policy_payload.get("policy")
            if (
                policy_status == 200
                and policy_payload.get("native") is True
                and isinstance(policy, dict)
                and (access_level is None or policy.get("access_level") == access_level)
            ):
                return payload
        time.sleep(0.25)
    wanted = "running" if running else "stopped"
    suffix = f" at level {access_level}" if access_level is not None else ""
    raise ProfileFailure(f"agent did not become {wanted}{suffix}; last={last}")


def _native_skill(
    base_url: str,
    *,
    token: str,
    skill: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    status, payload = _request(
        base_url,
        "/api/hostos/skill",
        token=token,
        method="POST",
        payload={"skill": skill, "arguments": arguments},
    )
    result = payload.get("result")
    if status != 200 or not isinstance(result, dict):
        raise ProfileFailure(f"native skill transport failed: {skill} HTTP {status}")
    return result


def _set_level(base_url: str, *, token: str, level: int) -> dict[str, Any]:
    status, payload = _request(
        base_url,
        "/api/config",
        token=token,
        method="PUT",
        payload={
            "values": {"interfaces:host.os.access_level": level},
            "lists": {},
        },
    )
    if status != 200 or payload.get("ok") is not True:
        raise ProfileFailure(f"JAWL rejected HostOS level {level}")
    status, payload = _request(
        base_url, "/api/agent/stop", token=token, method="POST", payload={}
    )
    if status != 200 or payload.get("ok") is not True:
        raise ProfileFailure("JAWL agent did not stop for the policy restart")
    _wait_agent(base_url, token=token, running=False)
    status, payload = _request(
        base_url, "/api/agent/start", token=token, method="POST", payload={}
    )
    if status != 200 or payload.get("ok") is not True:
        raise ProfileFailure(f"JAWL agent did not start at level {level}")
    _wait_agent(base_url, token=token, running=True, access_level=level)
    status, payload = _request(base_url, "/api/hostos/policy", token=token)
    policy = payload.get("policy")
    if status != 200 or payload.get("native") is not True or not isinstance(policy, dict):
        raise ProfileFailure(f"native policy snapshot unavailable at level {level}")
    return policy


def _parse_levels(raw: str) -> tuple[int, ...]:
    levels = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not levels or any(level not in range(4) for level in levels):
        raise ValueError("--levels must contain only comma-separated values 0..3")
    return levels


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for live actions")
    parser.add_argument("--url", default="http://127.0.0.1:8773")
    parser.add_argument("--token", default=os.environ.get("CONSOLE_TOKEN", ""))
    parser.add_argument("--levels", default="0,1,2,3")
    parser.add_argument("--sandbox-path", required=True)
    parser.add_argument("--outside-read-path", required=True)
    parser.add_argument("--outside-write-path")
    parser.add_argument("--exercise-write", action="store_true")
    parser.add_argument("--exercise-emergency-stop", action="store_true")
    parser.add_argument("--exercise-autonomy", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live policy changes require --live")
    if args.exercise_write and not args.outside_write_path:
        parser.error("--exercise-write requires --outside-write-path")

    base_url = _loopback_url(args.url)
    levels = _parse_levels(args.levels)
    report_path = args.report or Path("runtime") / (
        "native-policy-profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    write_path = Path(args.outside_write_path).resolve() if args.outside_write_path else None
    if args.exercise_write and write_path and write_path.exists():
        raise ProfileFailure("outside write path already exists; refusing to overwrite test data")

    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "native-jawl-hostos-policy",
        "base_url": base_url,
        "initial_access_level": None,
        "final_access_level": None,
        "levels": [],
        "emergency_stop": None,
        "autonomy": None,
        "failures": [],
        "pass": False,
    }
    current_level: int | None = None
    initial_level: int | None = None
    try:
        status, payload = _request(base_url, "/api/agent/status", token=args.token)
        if status != 200 or payload.get("running") is not True:
            raise ProfileFailure("JAWL agent must already be running")
        _wait_agent(base_url, token=args.token, running=True, timeout=90)
        status, payload = _request(base_url, "/api/hostos/policy", token=args.token)
        initial_policy = payload.get("policy")
        if (
            status != 200
            or payload.get("native") is not True
            or not isinstance(initial_policy, dict)
            or not isinstance(initial_policy.get("access_level"), int)
        ):
            raise ProfileFailure("native policy snapshot unavailable before profile")
        initial_level = int(initial_policy["access_level"])
        report["initial_access_level"] = initial_level
        for level in levels:
            policy = _set_level(base_url, token=args.token, level=level)
            current_level = level
            sandbox = _native_skill(
                base_url,
                token=args.token,
                skill="HostOSReader.read_file_range",
                arguments={"filepath": args.sandbox_path, "start_line": 1, "end_line": 1, "max_lines": 1},
            )
            outside_read = _native_skill(
                base_url,
                token=args.token,
                skill="HostOSReader.read_file_range",
                arguments={"filepath": args.outside_read_path, "start_line": 1, "end_line": 1, "max_lines": 1},
            )
            write_result = None
            if args.exercise_write:
                write_result = _native_skill(
                    base_url,
                    token=args.token,
                    skill="HostOSWriter.write_file",
                    arguments={
                        "filepath": str(write_path),
                        "content": f"native-policy-profile-level-{level}",
                        "description": "Disposable native JAWL policy profile marker",
                    },
                )
            expected = {
                "sandbox_read": True,
                "outside_read": level >= 1,
                "outside_write": (level >= 2) if args.exercise_write else None,
            }
            actual = {
                "sandbox_read": sandbox.get("is_success") is True,
                "outside_read": outside_read.get("is_success") is True,
                "outside_write": (
                    write_result.get("is_success") is True if write_result is not None else None
                ),
            }
            if any(actual[key] != value for key, value in expected.items()):
                raise ProfileFailure(f"policy expectation mismatch at level {level}: {actual}")
            report["levels"].append({
                "level": level,
                "access_name": policy.get("access_name"),
                "expected": expected,
                "actual": actual,
                "messages": {
                    "sandbox_read": str(sandbox.get("message", ""))[:300],
                    "outside_read": str(outside_read.get("message", ""))[:300],
                    "outside_write": str((write_result or {}).get("message", ""))[:300],
                },
            })

        if args.exercise_emergency_stop:
            if current_level != 3:
                _set_level(base_url, token=args.token, level=3)
                current_level = 3
            status, stopped = _request(
                base_url,
                "/api/hostos/emergency-stop",
                token=args.token,
                method="POST",
                payload={"actor": "native-policy-profile", "reason": "disposable fail-closed probe"},
            )
            stopped_policy = stopped.get("policy", {})
            blocked = _native_skill(
                base_url,
                token=args.token,
                skill="HostOSReader.read_file_range",
                arguments={"filepath": args.sandbox_path, "start_line": 1, "end_line": 1, "max_lines": 1},
            )
            reset_status, reset = _request(
                base_url,
                "/api/hostos/emergency-stop/reset",
                token=args.token,
                method="POST",
                payload={"confirm": True, "actor": "native-policy-profile"},
            )
            reset_policy = reset.get("policy", {})
            if (
                status != 200
                or stopped_policy.get("emergency_stop", {}).get("active") is not True
                or blocked.get("is_success") is not False
                or reset_status != 200
                or reset_policy.get("emergency_stop", {}).get("active") is not False
            ):
                raise ProfileFailure("emergency stop did not fail closed and recover explicitly")
            report["emergency_stop"] = {"stopped": True, "blocked": True, "reset": True}

        if args.exercise_autonomy:
            if current_level != 3:
                _set_level(base_url, token=args.token, level=3)
                current_level = 3
            status, issued = _request(
                base_url,
                "/api/hostos/autonomy",
                token=args.token,
                method="POST",
                payload={"enabled": True, "confirm": True, "ttl_seconds": 60, "actor": "native-policy-profile"},
            )
            revoke_status, revoked = _request(
                base_url,
                "/api/hostos/autonomy",
                token=args.token,
                method="POST",
                payload={"enabled": False, "actor": "native-policy-profile", "reason": "profile complete"},
            )
            issued_state = issued.get("policy", {}).get("unattended", {})
            revoked_state = revoked.get("policy", {}).get("unattended", {})
            if (
                status != 200
                or issued_state.get("enabled") is not True
                or issued_state.get("lease_present") is not True
                or revoke_status != 200
                or revoked_state.get("enabled") is not False
                or revoked_state.get("lease_present") is not False
            ):
                raise ProfileFailure("ROOT autonomy lease did not issue and revoke cleanly")
            report["autonomy"] = {"issued": True, "revoked": True}

        report["pass"] = True
    except (ProfileFailure, ValueError) as exc:
        report["failures"].append(str(exc))
    finally:
        # A failed probe must not leave the live agent in a temporary policy
        # state or with a temporary safety latch/lease.  This matters most when
        # an assertion fails before the normal emergency-stop/autonomy cleanup.
        try:
            status, payload = _request(base_url, "/api/hostos/policy", token=args.token)
            policy = payload.get("policy") if isinstance(payload, dict) else None
            if status == 200 and isinstance(policy, dict):
                emergency = policy.get("emergency_stop")
                if isinstance(emergency, dict) and emergency.get("active") is True:
                    reset_status, _ = _request(
                        base_url,
                        "/api/hostos/emergency-stop/reset",
                        token=args.token,
                        method="POST",
                        payload={"confirm": True, "actor": "native-policy-profile-cleanup"},
                    )
                    if reset_status != 200:
                        report["failures"].append("emergency-stop cleanup failed")
                        report["pass"] = False
                unattended = policy.get("unattended")
                if isinstance(unattended, dict) and (
                    unattended.get("enabled") is True
                    or unattended.get("lease_present") is True
                ):
                    revoke_status, _ = _request(
                        base_url,
                        "/api/hostos/autonomy",
                        token=args.token,
                        method="POST",
                        payload={
                            "enabled": False,
                            "actor": "native-policy-profile-cleanup",
                            "reason": "profile cleanup",
                        },
                    )
                    if revoke_status != 200:
                        report["failures"].append("autonomy cleanup failed")
                        report["pass"] = False
        except Exception as exc:  # noqa: BLE001 - preserve the primary profile failure
            report["failures"].append(f"safety-state cleanup failed: {type(exc).__name__}")
            report["pass"] = False

        if args.exercise_write and write_path and write_path.exists():
            try:
                if current_level != 3:
                    _set_level(base_url, token=args.token, level=3)
                    current_level = 3
                _native_skill(
                    base_url,
                    token=args.token,
                    skill="HostOSWriter.delete_file",
                    arguments={"filepath": str(write_path)},
                )
            except Exception as exc:  # noqa: BLE001 - preserve the primary profile failure
                report["failures"].append(f"write-marker cleanup failed: {type(exc).__name__}")
            if write_path.exists():
                report["failures"].append("write-marker still exists after native cleanup")
                report["pass"] = False

        if initial_level is not None:
            try:
                status, payload = _request(base_url, "/api/hostos/policy", token=args.token)
                policy = payload.get("policy") if isinstance(payload, dict) else None
                current_policy_level = (
                    policy.get("access_level")
                    if status == 200 and isinstance(policy, dict)
                    else None
                )
                if current_policy_level != initial_level:
                    _set_level(base_url, token=args.token, level=initial_level)
                report["final_access_level"] = initial_level
            except Exception as exc:  # noqa: BLE001 - report failed restoration
                report["failures"].append(
                    f"access-level restoration failed: {type(exc).__name__}"
                )
                report["pass"] = False

        try:
            status, payload = _request(base_url, "/api/hostos/policy", token=args.token)
            policy = payload.get("policy") if isinstance(payload, dict) else None
            if status == 200 and isinstance(policy, dict):
                report["final_access_level"] = policy.get("access_level")
        except Exception as exc:  # noqa: BLE001 - preserve the profile report
            report["failures"].append(f"final policy snapshot failed: {type(exc).__name__}")
            report["pass"] = False
        _write_report(report_path, report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={report_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
