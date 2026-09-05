"""Check JAWL native catalog availability at access levels 0 through 3.

The profile changes and restores only the policy of an already running
disposable JAWL instance. It performs no native writes, process starts,
provider calls, or debug-session operations; each level is checked through
the read-only dynamic catalog.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from run_native_namespace_profile import (
    NAMESPACE_PREFIXES,
    ProfileFailure,
    _loopback_url,
    _request,
    _validate_catalog,
    _write_report,
)


def _parse_levels(raw: str) -> tuple[int, ...]:
    levels = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not levels or any(level not in range(4) for level in levels):
        raise ValueError("--levels must contain only comma-separated values 0..3")
    return levels


def _wait_agent(base_url: str, *, token: str, timeout: float, running: bool) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = _request(
            base_url,
            "/api/agent/status",
            token=token,
            timeout=min(timeout, 10),
        )
        if (
            status == 200
            and payload.get("running") is running
            and not payload.get("starting")
            and not payload.get("stopping")
        ):
            return
        time.sleep(0.25)
    state = "running" if running else "stopped"
    raise ProfileFailure(f"JAWL agent did not become {state}")


def _current_policy(base_url: str, *, token: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = _request(base_url, "/api/hostos/policy", token=token, timeout=min(timeout, 10))
        policy = payload.get("policy")
        if status == 200 and payload.get("native") is True and isinstance(policy, dict):
            level = policy.get("access_level")
            if level not in range(4):
                raise ProfileFailure("native JAWL policy has an invalid access level")
            return policy
        if status not in {502, 503}:
            break
        time.sleep(0.25)
    raise ProfileFailure("native JAWL policy snapshot unavailable")


def _set_level(base_url: str, *, token: str, timeout: float, level: int) -> dict[str, Any]:
    status, payload = _request(
        base_url,
        "/api/config",
        token=token,
        timeout=timeout,
        method="PUT",
        payload={"values": {"interfaces:host.os.access_level": level}, "lists": {}},
    )
    if status != 200 or payload.get("ok") is not True:
        raise ProfileFailure(f"JAWL rejected native access level {level}")
    status, payload = _request(
        base_url,
        "/api/agent/stop",
        token=token,
        timeout=timeout,
        method="POST",
        payload={},
    )
    if status != 200 or payload.get("ok") is not True:
        raise ProfileFailure(f"JAWL did not stop for access level {level}")
    _wait_agent(base_url, token=token, timeout=timeout, running=False)
    status, payload = _request(
        base_url,
        "/api/agent/start",
        token=token,
        timeout=timeout,
        method="POST",
        payload={},
    )
    if status != 200 or payload.get("ok") is not True:
        raise ProfileFailure(f"JAWL did not start at access level {level}")
    _wait_agent(base_url, token=token, timeout=timeout, running=True)
    policy = _current_policy(base_url, token=token, timeout=timeout)
    if policy.get("access_level") != level:
        raise ProfileFailure(f"JAWL policy did not settle at level {level}")
    return policy


def _catalog(base_url: str, *, token: str, timeout: float) -> dict[str, Any]:
    query = urlencode(
        [("limit", "512")] + [("prefix", prefix) for prefix in NAMESPACE_PREFIXES]
    )
    status, payload = _request(
        base_url,
        "/api/skills/catalog?" + query,
        token=token,
        timeout=timeout,
    )
    if status != 200:
        raise ProfileFailure(f"native skill catalog request failed: HTTP {status}")
    return _validate_catalog(payload)


def _level_summary(level: int, policy: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    mismatches = []
    for item in catalog["skills"]:
        required = item["required_access_level"]
        expected = required is None or required <= level
        if item["available"] != expected:
            mismatches.append(item["name"])
    if mismatches:
        raise ProfileFailure(
            f"catalog availability mismatch at level {level}: {', '.join(mismatches[:8])}"
        )
    return {
        "level": level,
        "access_name": policy.get("access_name"),
        "total": catalog["total"],
        "counts": catalog["counts"],
        "available": catalog["available"],
        "availability_matches_required_level": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for live policy changes")
    parser.add_argument("--url", default="http://127.0.0.1:8773")
    parser.add_argument("--token", default=os.environ.get("CONSOLE_TOKEN", ""))
    parser.add_argument("--levels", default="0,1,2,3")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live catalog matrix changes require --live")
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds")

    base_url = _loopback_url(args.url)
    levels = _parse_levels(args.levels)
    report_path = args.report or Path("runtime") / (
        "native-catalog-matrix-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "native-jawl-catalog-access-matrix",
        "base_url": base_url,
        "requested_levels": list(levels),
        "initial_level": None,
        "levels": [],
        "restored_level": None,
        "failures": [],
        "pass": False,
    }
    initial_level: int | None = None
    current_level: int | None = None
    try:
        policy = _current_policy(base_url, token=args.token, timeout=args.timeout)
        initial_level = int(policy["access_level"])
        current_level = initial_level
        report["initial_level"] = initial_level
        for level in levels:
            # Mark the target before the mutating restart. If config accepts the
            # level but stop/start fails, finally must still attempt restoration.
            current_level = level
            policy = _set_level(
                base_url,
                token=args.token,
                timeout=args.timeout,
                level=level,
            )
            report["levels"].append(_level_summary(level, policy, _catalog(
                base_url, token=args.token, timeout=args.timeout
            )))
        report["pass"] = True
    except (ProfileFailure, ValueError) as exc:
        report["failures"].append(str(exc))
    finally:
        if initial_level is not None and current_level != initial_level:
            try:
                _set_level(
                    base_url,
                    token=args.token,
                    timeout=args.timeout,
                    level=initial_level,
                )
                current_level = initial_level
            except Exception as exc:  # noqa: BLE001 - preserve primary failure
                report["failures"].append(f"policy restoration failed: {type(exc).__name__}")
                report["pass"] = False
        report["restored_level"] = current_level
        _write_report(report_path, report)

    console_report = {
        key: report[key]
        for key in (
            "schema_version",
            "profile",
            "base_url",
            "requested_levels",
            "initial_level",
            "levels",
            "restored_level",
            "failures",
            "pass",
        )
    }
    print(json.dumps(console_report, ensure_ascii=True, indent=2))
    print(f"report={report_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
