"""Authenticated loopback smoke for a real Companion target machine.

The profile attaches to already running services. It never starts or stops a
process and never turns an optional dependency into a fake pass. By default it
checks both Companion HTTP surfaces; ``--require-*`` flags promote external
provider, JAWL, and Live2D checks to release requirements.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from run_native_namespace_profile import _loopback_url, _request, _write_report


class ProfileFailure(RuntimeError):
    """A target-machine release assertion failed."""


FORBIDDEN_PRESENTATION_FIELDS = {
    "session_token",
    "csrf_token",
    "policy",
    "last_turn",
    "recent_turns",
}


def _request_text(url: str, timeout: float) -> tuple[int, str]:
    request = Request(url, headers={"Accept": "text/html,application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(512 * 1024).decode("utf-8")
    except HTTPError as exc:
        try:
            exc.read(4096)
        finally:
            exc.close()
        return int(exc.code), ""
    except (URLError, OSError, TimeoutError, UnicodeDecodeError) as exc:
        raise ProfileFailure(f"target request failed: {type(exc).__name__}") from exc


def _dependency(value: str) -> tuple[str, str]:
    name, separator, url = value.partition("=")
    if not separator or not name.strip() or not url.strip():
        raise ValueError("--require-dependency must use name=loopback-url")
    return name.strip()[:64], _loopback_url(url.strip())


def _check_required_dependency(name: str, url: str, timeout: float) -> dict[str, Any]:
    status, payload = _request(url, "/health", token="", timeout=timeout)
    # HTTP availability alone does not establish that a worker finished loading.
    markers = [payload[key] is True for key in ("ok", "ready") if key in payload]
    if "status" in payload:
        markers.append(payload["status"] in ("ok", "ready", "online", "healthy"))
    if status != 200 or not markers or not all(markers):
        raise ProfileFailure(f"required dependency {name} has not reported ready: HTTP {status}")
    return {"name": name, "url": url, "http_status": status, "ok": True, "payload_keys": sorted(payload)[:24]}


def _check_jawl(url: str, token: str, timeout: float) -> dict[str, Any]:
    status, status_payload = _request(url, "/api/agent/status", token=token, timeout=timeout)
    policy_status, policy_payload = _request(url, "/api/hostos/policy", token=token, timeout=timeout)
    policy = policy_payload.get("policy")
    if (
        status != 200
        or status_payload.get("ok") is not True
        or status_payload.get("running") is not True
        or policy_status != 200
        or policy_payload.get("ok") is not True
        or policy_payload.get("native") is not True
        or not isinstance(policy, dict)
        or policy.get("authority") != "jawl"
        or type(policy.get("access_level")) is not int
        or policy["access_level"] not in range(4)
    ):
        raise ProfileFailure(
            "required native JAWL status/policy check failed: "
            f"status_http={status}, status_keys={sorted(status_payload)[:16]}, "
            f"status_ok={status_payload.get('ok')!r}, "
            f"policy_http={policy_status}, policy_keys={sorted(policy_payload)[:16]}, "
            f"policy_native={policy_payload.get('native')!r}"
        )
    return {
        "http_status": 200,
        "running": status_payload.get("running") is True,
        "native": True,
        "access_level": policy.get("access_level"),
        "authority": policy.get("authority"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for target-machine checks")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--presentation-url", default="http://127.0.0.1:8766")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--require-live2d", action="store_true")
    parser.add_argument("--require-jawl-url")
    parser.add_argument("--jawl-token", default=os.environ.get("CONSOLE_TOKEN", ""))
    parser.add_argument("--require-dependency", action="append", default=[], metavar="NAME=URL")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("target release checks require --live")
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60 seconds")

    control_url = _loopback_url(args.url)
    presentation_url = _loopback_url(args.presentation_url)
    if control_url == presentation_url:
        raise ValueError("control and presentation URLs must be different")
    report_path = args.report or Path("runtime") / (
        "target-release-profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "target-machine-loopback-release",
        "control_url": control_url,
        "presentation_url": presentation_url,
        "surfaces": {},
        "required_dependencies": [],
        "jawl": None,
        "live2d": None,
        "failures": [],
        "pass": False,
    }
    try:
        for path in ("/api/health", "/api/doctor", "/api/resources"):
            status, payload = _request(control_url, path, token="", timeout=args.timeout)
            if status != 200 or not payload:
                raise ProfileFailure(f"control endpoint failed: {path} HTTP {status}")
        status, html = _request_text(control_url + "/", args.timeout)
        if status != 200 or "JAWL VoiceCompanion" not in html:
            raise ProfileFailure("control HTML marker is missing")
        report["surfaces"]["control"] = {"health": True, "html": True}

        status, presentation_state = _request(
            presentation_url,
            "/api/presentation/state",
            token="",
            timeout=args.timeout,
        )
        if status != 200 or presentation_state.keys() & FORBIDDEN_PRESENTATION_FIELDS:
            raise ProfileFailure("presentation state is unavailable or contains privileged fields")
        status, html = _request_text(presentation_url + "/avatar", args.timeout)
        if status != 200 or "JAWL Avatar" not in html:
            raise ProfileFailure("presentation avatar marker is missing")
        report["surfaces"]["presentation"] = {"state": True, "html": True}

        if args.require_live2d:
            status, avatar = _request(control_url, "/api/avatar/config", token="", timeout=args.timeout)
            if status != 200 or avatar.get("ready") is not True:
                raise ProfileFailure("required Live2D asset/runtime is not ready")
            report["live2d"] = {"required": True, "ready": True}

        for raw_dependency in args.require_dependency:
            name, url = _dependency(raw_dependency)
            report["required_dependencies"].append(
                _check_required_dependency(name, url, args.timeout)
            )

        if args.require_jawl_url:
            jawl_url = _loopback_url(args.require_jawl_url)
            report["jawl"] = _check_jawl(jawl_url, args.jawl_token, args.timeout)
        report["pass"] = True
    except (ProfileFailure, ValueError) as exc:
        report["failures"].append(str(exc))
    finally:
        _write_report(report_path, report)

    print(json.dumps(report, ensure_ascii=True, indent=2))
    print(f"report={report_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
