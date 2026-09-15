"""Live acceptance for native supervisor lease-gated crash recovery.

This is a disposable control-plane test.  It starts the pinned JAWL
``src.instances.supervisor`` with a tiny local child process, kills that child
at a controlled boundary, and checks two different outcomes:

* a valid ROOT autonomy lease permits one bounded restart;
* revoking the lease before the next crash leaves the profile crashed and
  does not launch a third child.

The fake child has no agent/tool authority.  The test therefore proves the
native lifecycle/recovery boundary only; it does not claim checkpoint
reconciliation or exactly-once semantics for an arbitrary syscall.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psutil


ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"


class AcceptanceFailure(RuntimeError):
    pass


def wait_until(predicate, timeout: float, *, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def child_alive(manager, instance_id: str) -> bool:
    return manager._process(instance_id) is not None


def kill_owned(manager, instance_id: str) -> None:
    process = manager._process(instance_id)
    if process is None:
        return
    try:
        process.kill()
        process.wait(timeout=5)
    except (psutil.Error, OSError):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="required safety opt-in")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    if not args.live:
        parser.error("supervisor recovery acceptance requires --live")
    if not 5 <= args.timeout <= 120:
        parser.error("--timeout must be between 5 and 120 seconds")
    if not PINNED.is_dir():
        raise AcceptanceFailure(f"Pinned JAWL snapshot is missing: {PINNED}")

    report_path = args.report or ROOT / "runtime" / (
        "supervised-recovery-acceptance-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    instance_id = "recovery-acceptance-" + uuid4().hex[:8]
    supervisor = None
    manager = None
    temp_name = None
    result: dict = {
        "schema_version": 1,
        "test": "native_supervisor_lease_gated_crash_recovery",
        "pinned_snapshot": str(PINNED),
        "instance_id": instance_id,
        "valid_lease_restart": False,
        "revoke_blocks_restart": False,
        "no_third_child_after_revoke": False,
        "cleanup": False,
        "pass": False,
        "failure": None,
    }

    # Keep all generated files outside the immutable source snapshot.
    with tempfile.TemporaryDirectory(prefix="jawl-supervised-recovery-") as temp:
        temp_name = Path(temp)
        instances = temp_name / "instances"
        sandbox = temp_name / "sandbox"
        logs = temp_name / "logs"
        fake_src = temp_name / "src"
        fake_src.mkdir(parents=True)
        # The child is deliberately boring: it records its generation and
        # exits only after the native manager requests a graceful stop.
        (fake_src / "main.py").write_text(
            """import os
import time
from pathlib import Path

home = Path(os.environ["JAWL_INSTANCE_HOME"])
home.mkdir(parents=True, exist_ok=True)
counter = home / "child-starts.txt"
try:
    value = int(counter.read_text(encoding="utf-8"))
except (FileNotFoundError, ValueError):
    value = 0
counter.write_text(str(value + 1), encoding="utf-8")
stop = Path(os.environ["JAWL_DATA_DIR"]) / "agent.stop"
while not stop.exists():
    time.sleep(0.05)
""",
            encoding="utf-8",
        )
        os.environ.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "JAWL_INSTANCE_ID": instance_id,
                "JAWL_INSTANCES_ROOT": str(instances),
                "JAWL_SANDBOX_DIR": str(sandbox),
                "JAWL_LOG_DIR": str(logs),
            }
        )
        sys.path.insert(0, str(PINNED))
        try:
            from src.instances.manager import InstanceManager
            from src.instances.models import InstanceProfile

            manager = InstanceManager(
                temp_name,
                instances_root=instances,
                shared_sandbox=sandbox,
                python_executable=Path(sys.executable),
                entrypoint=fake_src / "main.py",
            )
            profile = InstanceProfile(
                instance_id=instance_id,
                display_name="Disposable supervisor recovery acceptance",
                desired_state="running",
                auto_restart=True,
                restart_limit=3,
                restart_window_sec=30,
                visible_console=False,
                telegram_mode="disabled",
            )
            manager.registry.create_profile(profile)
            # The registry entry is durable intent; create the isolated
            # profile layout exactly as the native manager does before launch.
            from src.instances.paths import bootstrap_instance_layout

            bootstrap_instance_layout(manager.paths_for(instance_id))
            paths = manager.paths_for(instance_id)
            (paths.config_dir / "interfaces.yaml").write_text(
                "host:\n  os:\n    enabled: true\n    access_level: 3\n",
                encoding="utf-8",
            )
            now = time.time()
            paths.autonomy_lease_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "active": True,
                        "access_level": 3,
                        "lease_id": "acceptance-lease-" + uuid4().hex[:12],
                        "issued_at": now - 1,
                        "expires_at": now + 300,
                        "actor": "acceptance",
                        "revoked_at": None,
                    }
                ),
                encoding="utf-8",
            )

            child_env = {
                **os.environ,
                "PYTHONPATH": str(PINNED),
                "PYTHONIOENCODING": "utf-8",
                "JAWL_INSTANCE_ID": instance_id,
                "JAWL_INSTANCES_ROOT": str(instances),
                "JAWL_SANDBOX_DIR": str(sandbox),
                "JAWL_LOG_DIR": str(logs),
            }
            supervisor_log = instances / "supervisor.log"
            supervisor_log.parent.mkdir(parents=True, exist_ok=True)
            log_stream = supervisor_log.open("w", encoding="utf-8")
            try:
                supervisor = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "src.instances.supervisor",
                        "--root",
                        str(temp_name),
                        "--interval",
                        "0.1",
                    ],
                    cwd=str(temp_name),
                    env=child_env,
                    stdout=log_stream,
                    stderr=log_stream,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            finally:
                log_stream.close()

            if not wait_until(
                lambda: manager.supervisor_status()["running"]
                and child_alive(manager, instance_id),
                args.timeout,
            ):
                raise AcceptanceFailure("supervisor or first child did not become ready")
            first = manager.status(instance_id)
            counter = paths.instance_home / "child-starts.txt"
            if counter.read_text(encoding="utf-8") != "1":
                raise AcceptanceFailure("first child generation marker was not written")

            first_pid = first["runtime"]["pid"]
            kill_owned(manager, instance_id)
            restarted = wait_until(
                lambda: counter.is_file()
                and counter.read_text(encoding="utf-8") == "2"
                and child_alive(manager, instance_id),
                args.timeout,
            )
            second = manager.status(instance_id)
            result["first_pid"] = first_pid
            result["second_pid"] = second["runtime"]["pid"]
            result["restart_outcome"] = manager.registry.get_runtime(instance_id).public()
            result["valid_lease_restart"] = bool(
                restarted
                and second["runtime"]["state"] == "running"
                and second["runtime"]["pid"] != first_pid
            )
            if not result["valid_lease_restart"]:
                raise AcceptanceFailure("valid ROOT lease did not permit exactly one restart")

            # The lease is the recovery authority.  Remove it before killing
            # the second generation; a desired_state=running alone must not
            # be enough to produce unattended recovery.
            paths.autonomy_lease_path.unlink()
            kill_owned(manager, instance_id)
            blocked = wait_until(
                lambda: manager.registry.get_runtime(instance_id).state == "crashed"
                and not child_alive(manager, instance_id),
                args.timeout,
            )
            blocked_runtime = manager.registry.get_runtime(instance_id)
            starts_after_block = counter.read_text(encoding="utf-8")
            time.sleep(1.0)
            starts_final = counter.read_text(encoding="utf-8")
            result["blocked_runtime"] = blocked_runtime.public()
            result["starts_after_revoke"] = starts_after_block
            result["starts_final"] = starts_final
            result["revoke_blocks_restart"] = bool(
                blocked
                and blocked_runtime.state == "crashed"
                and "ROOT autonomy lease" in blocked_runtime.last_error
            )
            result["no_third_child_after_revoke"] = (
                starts_after_block == "2" and starts_final == "2"
            )
            if not result["revoke_blocks_restart"]:
                raise AcceptanceFailure("revoked ROOT lease did not block recovery")
            if not result["no_third_child_after_revoke"]:
                raise AcceptanceFailure("supervisor launched a child after lease revocation")
            result["pass"] = True
        except Exception as exc:
            result["failure"] = f"{type(exc).__name__}: {exc}"
        finally:
            if manager is not None:
                try:
                    manager.request_stop(instance_id)
                except Exception:
                    pass
                try:
                    kill_owned(manager, instance_id)
                except Exception:
                    pass
            if supervisor is not None:
                stop_file = instances / "supervisor.stop"
                stop_file.parent.mkdir(parents=True, exist_ok=True)
                stop_file.write_text("stop\n", encoding="utf-8")
                try:
                    supervisor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    supervisor.terminate()
                    try:
                        supervisor.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        supervisor.kill()
                        supervisor.wait(timeout=5)
            result["cleanup"] = bool(
                supervisor is None or supervisor.poll() is not None
            ) and not (manager is not None and child_alive(manager, instance_id))
        # Pinned JAWL installs file handlers during import.  Close them before
        # TemporaryDirectory cleanup; Windows otherwise keeps the disposable
        # tree undeletable even after the supervisor has exited.
        logging.shutdown()
        sys.path.pop(0)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), **result}, ensure_ascii=False))
    return 0 if result["pass"] and result["cleanup"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
