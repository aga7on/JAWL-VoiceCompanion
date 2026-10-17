"""Owned supervisor identity using PID/creation metadata, never command lines."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
_INSTALL_ATTR = "__jawl_owned_supervisor_identity__"


def _read_object(path):
    if path.is_symlink():
        raise ValueError("supervisor identity must not be a symbolic link")
    with path.open("rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("supervisor identity exceeds bound")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("supervisor identity must be an object")
    return result


def install_native_supervisor_identity(manager_class, supervisor_module=None, *, root=ROOT):
    """Install status readback and, in the actual supervisor, lock-bound receipt.

    The receipt is published only after the native exclusive lock is acquired,
    and removed while still holding it. The native PID marker must also match.
    This is identity readback, not a second reconciliation loop or executor.
    """
    import psutil

    root = Path(root).resolve()
    instances = root / "runtime/instances"
    receipt_path = instances / "owned-supervisor-identity.json"
    entrypoint = root / "scripts/run_owned_jawl_supervisor.py"
    existing = vars(manager_class).get(_INSTALL_ATTR)
    if existing is not None:
        if (manager_class.supervisor_status is existing and supervisor_module is None
                and getattr(existing, "_owned_root", None) == root):
            return existing
        raise RuntimeError("owned supervisor identity already installed differently")

    def status(manager):
        try:
            if Path(manager.instances_root).resolve() != instances:
                raise ValueError("foreign instances root")
            receipt = _read_object(receipt_path)
            pid = receipt.get("pid")
            created = receipt.get("process_created_at")
            if (type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != 1 or isinstance(pid, bool)
                    or not isinstance(pid, int) or pid <= 0
                    or isinstance(created, bool) or not isinstance(created, (float, int))
                    or not math.isfinite(created) or created <= 0
                    or receipt.get("instances_root") != str(instances)
                    or receipt.get("entrypoint") != str(entrypoint)):
                raise ValueError("invalid supervisor identity")
            with (instances / "supervisor.pid").open("r", encoding="utf-8") as stream:
                marker = stream.read(65)
            if marker.strip() != str(pid):
                raise ValueError("supervisor PID marker differs")
            process = psutil.Process(pid)
            if not process.is_running() or abs(process.create_time() - created) > .001:
                raise ValueError("supervisor process creation identity differs")
            return {"running": True, "pid": pid}
        except (OSError, ValueError, TypeError, psutil.Error):
            return {"running": False, "pid": None}

    if supervisor_module is not None:
        original_lock = supervisor_module.SystemInstanceLock

        class OwnedIdentityLock(original_lock):
            _identity = None

            def acquire(self):
                if Path(self.lock_file).resolve() != instances / "supervisor.lock":
                    raise ValueError("supervisor lock must stay in owned instances root")
                if not super().acquire():
                    return False
                temporary = None
                try:
                    identity = {"schema_version": 1, "pid": os.getpid(),
                                "process_created_at": psutil.Process().create_time(),
                                "instances_root": str(instances), "entrypoint": str(entrypoint)}
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=instances,
                                                     prefix=".supervisor-identity-", suffix=".tmp",
                                                     delete=False) as stream:
                        temporary = Path(stream.name)
                        json.dump(identity, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, receipt_path)
                    self._identity = identity
                    return True
                except BaseException:
                    super().release()
                    raise
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)

            def release(self):
                try:
                    if self._identity is not None:
                        try:
                            if _read_object(receipt_path) == self._identity:
                                receipt_path.unlink()
                        except (OSError, ValueError):
                            pass
                        self._identity = None
                finally:
                    super().release()

        supervisor_module.SystemInstanceLock = OwnedIdentityLock

    status._owned_root = root
    manager_class.supervisor_status = status
    setattr(manager_class, _INSTALL_ATTR, status)
    return status
