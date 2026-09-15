"""Accept one disposable native JAWL action through the real Companion route.

The script intentionally uses the Companion session/CSRF boundary and
``/api/hostos/execute``.  It never calls the Companion-local executor and it
never overwrites an existing path: a fresh child of the supplied profile
sandbox is created, read back, and removed by native JAWL.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4


MAX_RESPONSE_BYTES = 512 * 1024


class AcceptanceFailure(RuntimeError):
    """A live connected assertion failed."""


def loopback_url(value: str) -> str:
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
        addresses = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses):
            raise ValueError("refusing a non-loopback URL") from exc
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def read_json(response: Any) -> dict[str, Any]:
    raw = response.read(MAX_RESPONSE_BYTES)
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def request_json(
    base: str,
    path: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    body = None
    request_headers = {"Accept": "application/json", **headers}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(base + path, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), read_json(response)
    except HTTPError as exc:
        try:
            return int(exc.code), read_json(exc)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return int(exc.code), {}
    except (OSError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceFailure(f"request failed for {path}: {type(exc).__name__}") from exc


def native_action(
    base: str,
    headers: dict[str, str],
    skill: str,
    arguments: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    status, payload = request_json(
        base,
        "/api/hostos/execute",
        headers,
        method="POST",
        payload={"request": {"skill": skill, "arguments": arguments}},
        timeout=timeout,
    )
    result = payload.get("result")
    if status != 200 or payload.get("ok") is not True or payload.get("native") is not True:
        raise AcceptanceFailure(f"{skill} was not accepted as native: HTTP {status}")
    if not isinstance(result, dict) or result.get("is_success") is not True:
        raise AcceptanceFailure(f"{skill} returned an unsuccessful native result")
    return {
        "skill": skill,
        "http_status": status,
        "native": True,
        "is_success": True,
        "message_excerpt": str(result.get("message", ""))[:400],
        "result_keys": sorted(str(key) for key in result)[:24],
    }


def connected_text_turn(
    base: str,
    headers: dict[str, str],
    correlation_id: str,
    timeout: float,
) -> dict[str, Any]:
    """Exercise the same Companion-to-JAWL native chat lane used by the UI."""

    request = Request(
        base + "/api/chat/stream",
        data=json.dumps({
            "text": "Это acceptance-проверка связанного текстового канала. Вызови ровно один canonical skill HostTerminalMessages.send_message_to_terminal с text=CONNECTED_TEXT_OK, затем заверши цикл. Не оставляй ответ только в thoughts.",
            "correlation_id": correlation_id,
        }, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    event_types: list[str] = []
    final: dict[str, Any] | None = None
    with urlopen(request, timeout=timeout) as response:
        if int(response.status) != 200:
            raise AcceptanceFailure(f"connected chat returned HTTP {response.status}")
        for raw_line in response:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line:
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise AcceptanceFailure("connected chat emitted a non-object event")
            event_types.append(str(event.get("type") or ""))
            if event.get("type") == "final" and isinstance(event.get("response"), dict):
                final = dict(event["response"])
    if final is None:
        raise AcceptanceFailure("connected chat ended without a final envelope")
    if not str(final.get("text") or "").strip():
        raise AcceptanceFailure("connected chat ended with an empty final envelope")
    return {
        "pass": final.get("speak") is True,
        "event_types": event_types,
        "response_turn_id": str(final.get("turn_id") or ""),
        "response_text_excerpt": str(final.get("text") or "")[:240],
        "correlation_id": correlation_id,
        "response_correlation_matches": final.get("correlation_id") in {None, correlation_id},
        "speak": final.get("speak") is True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for live disposable actions")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--sandbox-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--expected-model",
        default="jawl-gemma4-it:latest",
        help="model identifier that must appear in the selected JAWL ReAct log",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live native actions require --live")
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds")

    base = loopback_url(args.url)
    sandbox = args.sandbox_dir.resolve()
    if sandbox.name != "sandbox" or not sandbox.is_dir():
        raise AcceptanceFailure("--sandbox-dir must be an existing profile sandbox directory")
    action_name = "connected-native-" + uuid4().hex
    action_dir = sandbox / action_name
    marker = action_dir / "marker.txt"
    relative_dir = f"sandbox/{action_name}"
    relative_marker = f"{relative_dir}/marker.txt"
    marker_text = "connected native acceptance marker\n"
    expected_sha = hashlib.sha256(marker_text.encode("utf-8")).hexdigest()
    report_path = args.report or Path("runtime") / (
        "connected-native-action-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "connected_companion_native_action",
        "base_url": base,
        "sandbox": str(sandbox),
        "relative_marker": relative_marker,
        "correlation_id": "connected-native-" + uuid4().hex,
        "actions": [],
        "cleanup": {"delete_file_requested": False, "delete_directory_requested": False,
                     "marker_absent": False, "directory_absent": False},
        "pass": False,
        "failure": None,
    }
    headers: dict[str, str] = {"Origin": base}
    created = False
    try:
        with urlopen(Request(base + "/api/session", method="GET"), timeout=args.timeout) as response:
            session = read_json(response)
            cookies = SimpleCookie(response.headers.get("Set-Cookie", ""))
        cookie = cookies.get("companion_session")
        csrf = session.get("csrf_token")
        if cookie is None or not isinstance(csrf, str) or not csrf:
            raise AcceptanceFailure("Companion session bootstrap was incomplete")
        headers.update({
            "Cookie": f"companion_session={cookie.value}",
            "X-Companion-Session": cookie.value,
            "X-Companion-CSRF": csrf,
        })
        text_correlation = "connected-text-" + uuid4().hex
        connected = connected_text_turn(base, headers, text_correlation, args.timeout)
        if not connected["response_correlation_matches"]:
            raise AcceptanceFailure("connected chat final envelope lost its correlation id")
        log_path = sandbox.parent / "logs" / "main.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        model_id = str(args.expected_model or "").strip()
        if not model_id or len(model_id) > 200 or "\n" in model_id or "\r" in model_id:
            raise AcceptanceFailure("--expected-model must be a bounded single-line identifier")
        connected["model_id"] = model_id
        connected["model_identity_in_jawl_log"] = f"LLM Model: {model_id}" in log_text
        if not connected["model_identity_in_jawl_log"]:
            raise AcceptanceFailure("JAWL log did not prove the selected local model identity")
        report["connected_text"] = connected
        status, hostos = request_json(base, "/api/jawl/hostos", headers, timeout=args.timeout)
        if status != 200 or hostos.get("control_enabled") is not True:
            raise AcceptanceFailure("Companion does not expose native JAWL HostOS control")
        report["hostos"] = {
            "status": status,
            "control_enabled": hostos.get("control_enabled"),
            "native": hostos.get("native") is True,
        }

        report["actions"].append(native_action(
            base, headers, "HostOSWriter.create_directories", {"paths": [relative_dir]}, args.timeout,
        ))
        created = True
        report["actions"].append(native_action(
            base,
            headers,
            "HostOSWriter.write_file",
            {"filepath": relative_marker, "content": marker_text,
             "description": "Disposable connected Companion native acceptance marker"},
            args.timeout,
        ))
        readback = native_action(
            base, headers, "HostOSReader.read_file", {"filepath": relative_marker}, args.timeout,
        )
        report["actions"].append(readback)
        if marker.read_text(encoding="utf-8") != marker_text:
            raise AcceptanceFailure("postcondition disk read did not match native write")
        if expected_sha not in readback["message_excerpt"]:
            raise AcceptanceFailure("native HostOSReader response did not expose expected SHA-256")
        report["postcondition"] = {"disk_match": True, "expected_sha256": expected_sha,
                                   "native_read_exposed_sha256": True}
    except (AcceptanceFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if marker.exists():
            report["cleanup"]["delete_file_requested"] = True
            try:
                report["actions"].append(native_action(
                    base, headers, "HostOSWriter.delete_file", {"filepath": relative_marker}, args.timeout,
                ))
            except Exception as exc:  # preserve primary failure while recording cleanup failure
                report["failure"] = report["failure"] or f"cleanup delete_file: {type(exc).__name__}: {exc}"
        report["cleanup"]["marker_absent"] = not marker.exists()
        if created and action_dir.exists():
            report["cleanup"]["delete_directory_requested"] = True
            try:
                report["actions"].append(native_action(
                    base, headers, "HostOSWriter.delete_directory", {"path": relative_dir}, args.timeout,
                ))
            except Exception as exc:  # preserve primary failure while recording cleanup failure
                report["failure"] = report["failure"] or f"cleanup delete_directory: {type(exc).__name__}: {exc}"
        report["cleanup"]["directory_absent"] = not action_dir.exists()
        report["pass"] = report["failure"] is None and report.get("connected_text", {}).get("pass") is True and report["cleanup"]["marker_absent"] and report["cleanup"]["directory_absent"]
    report_path = report_path if report_path.is_absolute() else Path(__file__).resolve().parents[1] / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print(f"report={report_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
