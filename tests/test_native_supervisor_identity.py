"""Supervisor readback is lock-bound, bounded and resistant to PID reuse."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("supervisor_identity_test", ROOT / "src/jawl_voicecompanion/native_supervisor_identity.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class SupervisorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.instances = self.root / "runtime/instances"
        self.instances.mkdir(parents=True)
        self.receipt = self.instances / "owned-supervisor-identity.json"
        self.pid = self.instances / "supervisor.pid"

        class Manager:
            def supervisor_status(self):
                raise AssertionError("native command-line check must not run")
        self.manager_class = Manager
        self.manager = Manager()
        self.manager.instances_root = self.instances

    def native(self, *, succeeds=True):
        receipt = self.receipt

        class Lock:
            def __init__(self, lock_file):
                self.lock_file = lock_file
                self.releases = 0
                self.receipt_on_acquire = None
                self.receipt_on_release = None

            def acquire(self):
                self.receipt_on_acquire = receipt.exists()
                return succeeds

            def release(self):
                self.releases += 1
                self.receipt_on_release = receipt.exists()
        return SimpleNamespace(SystemInstanceLock=Lock)

    def test_receipt_exists_only_inside_acquired_native_lock_and_no_command_line_is_read(self):
        native = self.native()
        entry.install_native_supervisor_identity(self.manager_class, native, root=self.root)
        lock = native.SystemInstanceLock(self.instances / "supervisor.lock")
        with patch.object(psutil.Process, "cmdline", side_effect=AssertionError("private command line")):
            self.assertTrue(lock.acquire())
            self.assertFalse(lock.receipt_on_acquire)
            self.assertLess(self.receipt.stat().st_size, 4096)
            self.assertEqual(self.manager.supervisor_status(), {"running": False, "pid": None})
            self.pid.write_text(str(os.getpid()))
            self.assertEqual(self.manager.supervisor_status(), {"running": True, "pid": os.getpid()})
            lock.release()
        self.assertFalse(lock.receipt_on_release)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(list(self.instances.glob("*.tmp")), [])

    def test_failed_lock_and_receipt_failure_never_publish_running_identity(self):
        native = self.native(succeeds=False)
        entry.install_native_supervisor_identity(self.manager_class, native, root=self.root)
        lock = native.SystemInstanceLock(self.instances / "supervisor.lock")
        self.assertFalse(lock.acquire())
        self.assertFalse(self.receipt.exists())
        native2 = self.native()
        manager2 = type("Manager", (), {})
        entry.install_native_supervisor_identity(manager2, native2, root=self.root)
        lock2 = native2.SystemInstanceLock(self.instances / "supervisor.lock")
        with patch.object(entry.os, "replace", side_effect=OSError("fixture disk failure")), self.assertRaises(OSError):
            lock2.acquire()
        self.assertEqual(lock2.releases, 1)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(list(self.instances.glob("*.tmp")), [])

    def test_reused_pid_foreign_root_and_malformed_receipts_fail_closed(self):
        native = self.native()
        entry.install_native_supervisor_identity(self.manager_class, native, root=self.root)
        lock = native.SystemInstanceLock(self.instances / "supervisor.lock")
        self.assertTrue(lock.acquire())
        self.pid.write_text(str(os.getpid()))
        valid = json.loads(self.receipt.read_text())
        variants = ({"pid": True}, {"schema_version": True}, {"pid": -1},
                    {"process_created_at": True}, {"process_created_at": float("nan")},
                    {"process_created_at": valid["process_created_at"] - 1},
                    {"entrypoint": "foreign.py"}, {"instances_root": str(self.root)})
        for changed in variants:
            with self.subTest(changed=changed):
                self.receipt.write_text(json.dumps(dict(valid, **changed)))
                self.assertFalse(self.manager.supervisor_status()["running"])
        for raw in ("[]", "{broken", " " * 4097):
            self.receipt.write_text(raw)
            self.assertFalse(self.manager.supervisor_status()["running"])
        self.receipt.write_text(json.dumps(valid))
        self.pid.write_text("456")
        self.assertFalse(self.manager.supervisor_status()["running"])
        self.pid.write_text(str(os.getpid()))
        self.manager.instances_root = self.root
        self.assertFalse(self.manager.supervisor_status()["running"])
        lock.release()

    def test_foreign_lock_path_and_replaced_receipt_are_never_removed(self):
        native = self.native()
        entry.install_native_supervisor_identity(self.manager_class, native, root=self.root)
        with self.assertRaises(ValueError):
            native.SystemInstanceLock(self.root / "foreign.lock").acquire()
        lock = native.SystemInstanceLock(self.instances / "supervisor.lock")
        self.assertTrue(lock.acquire())
        self.receipt.write_text('{"pid":456}')
        lock.release()
        self.assertEqual(json.loads(self.receipt.read_text()), {"pid": 456})

    def test_install_is_idempotent_and_replaced_status_is_refused(self):
        first = entry.install_native_supervisor_identity(self.manager_class, root=self.root)
        self.assertIs(entry.install_native_supervisor_identity(self.manager_class, root=self.root), first)
        self.manager_class.supervisor_status = lambda manager: None
        with self.assertRaises(RuntimeError):
            entry.install_native_supervisor_identity(self.manager_class, root=self.root)


if __name__ == "__main__":
    unittest.main()
