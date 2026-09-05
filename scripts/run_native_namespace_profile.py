"""Read-only live parity checks for JAWL's native skill namespaces.

This profile talks to an already running, authenticated JAWL web console. It
does not start processes, change policy, open a debug session, or call a
Companion-local executor. The catalog is dynamic: the report proves what the
running JAWL instance exposes, while the representative probes prove that the
web routes reach native JAWL implementations.

Use a disposable JAWL instance and paths owned by the operator. The profile
intentionally exercises only read-only skills.
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
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


NAMESPACE_PREFIXES = ("HostOS", "HostTerminal", "DebugBroker")
MAX_RESPONSE_BYTES = 512 * 1024


class ProfileFailure(RuntimeError):
    """A live namespace assertion failed."""


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
    timeout: float,
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
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES)
            parsed = json.loads(raw.decode("utf-8"))
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except HTTPError as exc:
        try:
            raw = exc.read(MAX_RESPONSE_BYTES)
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        return int(exc.code), parsed if isinstance(parsed, dict) else {}
    except (URLError, OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileFailure(f"JAWL request failed for {path}: {type(exc).__name__}") from exc


def _namespace_counts(skills: list[dict[str, Any]]) -> dict[str, int]:
    counts = {prefix: 0 for prefix in NAMESPACE_PREFIXES}
    for item in skills:
        name = item.get("name")
        for prefix in NAMESPACE_PREFIXES:
            if isinstance(name, str) and _matches_prefix(name, prefix):
                counts[prefix] += 1
                break
    return counts


def _matches_prefix(name: str, prefix: str) -> bool:
    """Match the catalog query family (class namespace plus dot skill name)."""
    return name.startswith(prefix)


def _validate_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok") is not True or payload.get("native") is not True:
        raise ProfileFailure("JAWL returned a non-native or unsuccessful skill catalog")
    catalog = payload.get("catalog")
    if not isinstance(catalog, dict):
        raise ProfileFailure("JAWL returned no skill catalog object")
    if catalog.get("schema_version") != 1:
        raise ProfileFailure("unsupported JAWL skill catalog schema")
    skills = catalog.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ProfileFailure("JAWL returned an empty or invalid skill catalog")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in skills:
        if not isinstance(item, dict):
            raise ProfileFailure("JAWL skill catalog contains a non-object entry")
        name = item.get("name")
        signature = item.get("signature")
        required_level = item.get("required_access_level")
        if (
            not isinstance(name, str)
            or not name
            or not any(_matches_prefix(name, prefix) for prefix in NAMESPACE_PREFIXES)
            or name in seen
            or not isinstance(signature, str)
            or not isinstance(item.get("available"), bool)
            or not isinstance(item.get("custom"), bool)
            or (required_level is not None and required_level not in range(4))
        ):
            raise ProfileFailure(f"invalid or duplicate catalog entry: {name!r}")
        seen.add(name)
        normalized.append(
            {
                "name": name,
                "required_access_level": required_level,
                "available": item["available"],
                "custom": item["custom"],
            }
        )
    counts = _namespace_counts(normalized)
    missing = [prefix for prefix, count in counts.items() if count == 0]
    if missing:
        raise ProfileFailure("JAWL catalog is missing namespaces: " + ", ".join(missing))
    available = {
        prefix: sum(
            item["available"]
            for item in normalized
            if _matches_prefix(item["name"], prefix)
        )
        for prefix in NAMESPACE_PREFIXES
    }
    return {
        "schema_version": catalog["schema_version"],
        "prefixes": list(catalog.get("prefixes", [])),
        "total": len(normalized),
        "counts": counts,
        "available": available,
        "skills": normalized,
    }


def _skill_route(skill: str) -> str:
    if skill.startswith("DebugBroker."):
        return "/api/debug/skill"
    if skill.startswith("HostOS") or skill.startswith("HostTerminal"):
        return "/api/hostos/skill"
    raise ValueError(f"unsupported native namespace: {skill}")


def _probe(
    base_url: str,
    *,
    token: str,
    timeout: float,
    skill: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    route = _skill_route(skill)
    status, payload = _request(
        base_url,
        route,
        token=token,
        timeout=timeout,
        method="POST",
        payload={"skill": skill, "arguments": arguments},
    )
    result = payload.get("result")
    if (
        status != 200
        or payload.get("ok") is not True
        or payload.get("native") is not True
        or not isinstance(result, dict)
        or result.get("is_success") is not True
    ):
        raise ProfileFailure(f"native read-only probe failed: {skill} HTTP {status}")
    message = str(result.get("message", ""))
    return {
        "skill": skill,
        "route": route,
        "http_status": status,
        "native": True,
        "is_success": True,
        "result_keys": sorted(str(key) for key in result.keys())[:32],
        "message_excerpt": message[:300],
    }


def _wait_running(base_url: str, *, token: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = _request(
            base_url, "/api/agent/status", token=token, timeout=min(timeout, 10)
        )
        if status == 200 and payload.get("running") is True and not payload.get("starting"):
            return
        time.sleep(0.25)
    raise ProfileFailure("JAWL agent is not running")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for live probes")
    parser.add_argument("--url", default="http://127.0.0.1:8773")
    parser.add_argument("--token", default=os.environ.get("CONSOLE_TOKEN", ""))
    parser.add_argument("--read-path", required=True, help="read-only file visible to native JAWL")
    parser.add_argument("--directory-path", required=True, help="directory visible to native JAWL")
    parser.add_argument("--search-path", required=True, help="directory used by the bounded file search")
    parser.add_argument("--network-host", default="127.0.0.1")
    parser.add_argument("--network-port", type=int, default=8773)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live namespace probes require --live")
    if not 1 <= args.network_port <= 65535:
        parser.error("--network-port must be between 1 and 65535")
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60 seconds")

    base_url = _loopback_url(args.url)
    report_path = args.report or Path("runtime") / (
        "native-namespace-profile-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "native-jawl-namespace-representative",
        "base_url": base_url,
        "catalog": None,
        "probes": [],
        "failures": [],
        "pass": False,
    }
    try:
        _wait_running(base_url, token=args.token, timeout=args.timeout)
        query = urlencode(
            [("limit", "512")]
            + [("prefix", prefix) for prefix in NAMESPACE_PREFIXES]
        )
        status, payload = _request(
            base_url,
            "/api/skills/catalog?" + query,
            token=args.token,
            timeout=args.timeout,
        )
        if status != 200:
            raise ProfileFailure(f"native skill catalog request failed: HTTP {status}")
        report["catalog"] = _validate_catalog(payload)
        probe_specs = (
            (
                "HostOSReader.read_file_range",
                {"filepath": args.read_path, "start_line": 1, "end_line": 1, "max_lines": 1},
            ),
            ("HostOSSearch.list_directory", {"path": args.directory_path, "max_depth": 0}),
            ("HostOSSearch.search_files", {"pattern": "README.md", "path": args.search_path}),
            (
                "HostOSNetwork.check_port",
                {"host": args.network_host, "port": args.network_port, "timeout": 3},
            ),
            ("HostOSMonitoring.get_tracked_directories", {}),
            ("HostTerminalMessages.read_terminal_history", {"limit": 3}),
            ("DebugBroker.list_providers", {}),
            ("DebugBroker.session_snapshot", {}),
        )
        report["probes"] = [
            _probe(
                base_url,
                token=args.token,
                timeout=args.timeout,
                skill=skill,
                arguments=arguments,
            )
            for skill, arguments in probe_specs
        ]
        report["pass"] = True
    except (ProfileFailure, ValueError) as exc:
        report["failures"].append(str(exc))
    finally:
        _write_report(report_path, report)

    console_report = {
        "schema_version": report["schema_version"],
        "profile": report["profile"],
        "base_url": report["base_url"],
        "catalog": (
            {
                key: report["catalog"][key]
                for key in ("schema_version", "prefixes", "total", "counts", "available")
            }
            if isinstance(report["catalog"], dict)
            else None
        ),
        "probes": [
            {
                "skill": probe["skill"],
                "route": probe["route"],
                "http_status": probe["http_status"],
                "native": probe["native"],
                "is_success": probe["is_success"],
            }
            for probe in report["probes"]
        ],
        "failures": report["failures"],
        "pass": report["pass"],
    }
    print(json.dumps(console_report, ensure_ascii=True, indent=2))
    print(f"report={report_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
