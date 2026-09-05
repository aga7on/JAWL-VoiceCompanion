"""Exercise a bounded native JAWL HostOS write/metadata/monitoring slice.

The profile is intentionally narrow and disposable. It creates one new child
directory and marker under a supplied JAWL sandbox, sets file metadata,
tracks and untracks the child, then deletes the marker and
directory through native JAWL. It never overwrites an existing path and never
calls the Companion-local executor. The target must be a disposable sandbox
owned by this profile.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from run_native_namespace_profile import (
    ProfileFailure,
    _loopback_url,
    _probe,
    _request,
    _write_report,
)


def _validate_paths(marker: Path, sandbox_dir: Path) -> Path:
    if marker.exists():
        raise ProfileFailure("sandbox marker already exists; refusing to overwrite it")
    action_dir = marker.parent
    if action_dir.exists() or action_dir.parent != sandbox_dir:
        raise ProfileFailure("marker parent must be one new direct child of sandbox")
    try:
        marker.relative_to(action_dir)
    except ValueError as exc:
        raise ProfileFailure("sandbox marker must be inside sandbox directory") from exc
    return action_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required acknowledgement for live disposable actions")
    parser.add_argument("--url", default="http://127.0.0.1:8773")
    parser.add_argument("--token", default=os.environ.get("CONSOLE_TOKEN", ""))
    parser.add_argument("--sandbox-marker", required=True, help="new marker path inside the JAWL sandbox")
    parser.add_argument("--sandbox-dir", required=True, help="JAWL sandbox directory to track")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("live native actions require --live")
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60 seconds")

    base_url = _loopback_url(args.url)
    marker = Path(args.sandbox_marker).resolve()
    sandbox_dir = Path(args.sandbox_dir).resolve()
    action_dir = _validate_paths(marker, sandbox_dir)
    report_path = args.report or Path("runtime") / (
        "native-action-profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": "native-jawl-hostos-action-slice",
        "correlation_id": "native-action-" + uuid4().hex,
        "base_url": base_url,
        "actions": [],
        "cleanup": {
            "delete_requested": False,
            "marker_absent": False,
            "directory_deleted": False,
            "untracked": False,
        },
        "failures": [],
        "pass": False,
    }
    tracked = False
    directory_created = False
    try:
        report["actions"].append(_probe(
            base_url,
            token=args.token,
            timeout=args.timeout,
            skill="HostOSWriter.create_directories",
            arguments={"paths": str(action_dir)},
        ))
        directory_created = True
        report["actions"].append(_probe(
            base_url,
            token=args.token,
            timeout=args.timeout,
            skill="HostOSWriter.write_file",
            arguments={
                "filepath": str(marker),
                "content": "native-action-profile disposable marker",
                "description": "Disposable native action profile marker",
            },
        ))
        report["actions"].append(_probe(
            base_url,
            token=args.token,
            timeout=args.timeout,
            skill="HostOSMetadata.set_file_description",
            arguments={"filepath": str(marker), "description": "Native action profile metadata"},
        ))
        report["actions"].append(_probe(
            base_url,
            token=args.token,
            timeout=args.timeout,
            skill="HostOSMonitoring.track_directory",
            arguments={"path": str(action_dir)},
        ))
        tracked = True
        report["actions"].append(_probe(
            base_url,
            token=args.token,
            timeout=args.timeout,
            skill="HostOSMonitoring.get_tracked_directories",
            arguments={},
        ))
        report["pass"] = True
    except (ProfileFailure, ValueError) as exc:
        report["failures"].append(str(exc))
    finally:
        if tracked:
            try:
                _probe(
                    base_url,
                    token=args.token,
                    timeout=args.timeout,
                    skill="HostOSMonitoring.untrack_directory",
                    arguments={"path": str(action_dir)},
                )
                report["cleanup"]["untracked"] = True
            except Exception as exc:  # noqa: BLE001 - preserve primary action failure
                report["failures"].append(f"untrack cleanup failed: {type(exc).__name__}")
                report["pass"] = False
        if marker.exists():
            try:
                report["cleanup"]["delete_requested"] = True
                _probe(
                    base_url,
                    token=args.token,
                    timeout=args.timeout,
                    skill="HostOSWriter.delete_file",
                    arguments={"filepath": str(marker)},
                )
            except Exception as exc:  # noqa: BLE001 - preserve primary action failure
                report["failures"].append(f"marker cleanup failed: {type(exc).__name__}")
                report["pass"] = False
        report["cleanup"]["marker_absent"] = not marker.exists()
        if not report["cleanup"]["marker_absent"]:
            report["failures"].append("sandbox marker still exists after native cleanup")
            report["pass"] = False
        if directory_created and action_dir.exists():
            try:
                _probe(
                    base_url,
                    token=args.token,
                    timeout=args.timeout,
                    skill="HostOSWriter.delete_directory",
                    arguments={"path": str(action_dir)},
                )
            except Exception as exc:  # noqa: BLE001 - preserve primary action failure
                report["failures"].append(f"directory cleanup failed: {type(exc).__name__}")
                report["pass"] = False
        report["cleanup"]["directory_deleted"] = not action_dir.exists()
        if not report["cleanup"]["directory_deleted"]:
            report["failures"].append("action directory still exists after native cleanup")
            report["pass"] = False
        _write_report(report_path, report)

    console_report = {
        "schema_version": report["schema_version"],
        "profile": report["profile"],
        "correlation_id": report["correlation_id"],
        "base_url": report["base_url"],
        "actions": [
            {key: action[key] for key in ("skill", "route", "http_status", "native", "is_success")}
            for action in report["actions"]
        ],
        "cleanup": report["cleanup"],
        "failures": report["failures"],
        "pass": report["pass"],
    }
    print(json.dumps(console_report, ensure_ascii=True, indent=2))
    print(f"report={report_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
