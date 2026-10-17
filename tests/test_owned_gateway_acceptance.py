"""Acceptance driver identity fences and actual log-wrapper behavior."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("owned_gateway_acceptance_test", ROOT / "scripts/run_owned_gateway_acceptance.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class OwnedGatewayAcceptanceTests(unittest.TestCase):
    def test_cleanup_removes_only_dead_exact_supervisor_lock_and_refuses_foreign_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            instances = Path(temporary)
            lock = instances / "supervisor.lock"
            pid_file = instances / "supervisor.pid"
            with patch.object(entry, "INSTANCES", instances), patch.object(psutil, "pid_exists", return_value=False):
                receipt = instances / "owned-supervisor-identity.json"
                receipt.write_text('{"pid":123,"process_created_at":1}')
                lock.write_text("123")
                with self.assertRaisesRegex(RuntimeError, "foreign supervisor identity"):
                    entry.cleanup_supervisor_lock(123)
                self.assertTrue(lock.exists())
                entry.cleanup_supervisor_lock(123, {"pid": 123, "process_created_at": 1})
                self.assertFalse(receipt.exists())
                lock.write_text("123")
                entry.cleanup_supervisor_lock(123)
                self.assertFalse(lock.exists())
                for foreign_pid in (True, False):
                    lock.write_text("123" if foreign_pid else "456")
                    if foreign_pid:
                        pid_file.write_text("456")
                    with self.assertRaisesRegex(RuntimeError, "foreign supervisor"):
                        entry.cleanup_supervisor_lock(123)
                    self.assertTrue(lock.exists())
                    pid_file.unlink(missing_ok=True)
            with patch.object(entry, "INSTANCES", instances), patch.object(psutil, "pid_exists", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "still live"):
                    entry.cleanup_supervisor_lock(123)
                self.assertTrue(lock.exists())

    def receipt(self):
        return {"schema_version": 1, "instance_id": "fixture", "bootstrap_only": False,
                "local_json_format_installed": True,
                "goal_protocol_repair_installed": True,
                "hooks": {"delivery_guard": True, "turn_context": True, "policy_completion": True},
                "instance_home": str(entry.INSTANCES / "fixture"),
                "entrypoint": str(ROOT / "scripts/run_owned_jawl_brain.py"),
                "source": str(ROOT / "runtime/jawl-sources/fixture"),
                "snapshot_sha256": "a" * 64, "pid": os.getpid(),
                "process_created_at": psutil.Process().create_time()}

    def test_receipt_requires_source_hooks_exact_job_and_process_creation_identity(self):
        receipt = self.receipt()
        snapshot = {"source": receipt["source"], "snapshot_sha256": receipt["snapshot_sha256"]}
        owner = SimpleNamespace(owns_pid=lambda pid: pid == os.getpid())
        entry.validate_brain_receipt(receipt, "fixture", snapshot, owner)
        for changed in ({"bootstrap_only": True}, {"local_json_format_installed": False}, {"snapshot_sha256": "b" * 64},
                        {"hooks": {"delivery_guard": True, "turn_context": False}},
                        {"process_created_at": receipt["process_created_at"] - 1},
                        {"entrypoint": str(ROOT / "other.py")}, {"pid": True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                entry.validate_brain_receipt(dict(receipt, **changed), "fixture", snapshot, owner)
        with self.assertRaisesRegex(ValueError, "exact launcher Job"):
            entry.validate_brain_receipt(receipt, "fixture", snapshot, SimpleNamespace(owns_pid=lambda pid: False))

    def test_logged_wrapper_preserves_both_provider_generations(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "owned.log"
            for value in ("first", "second"):
                command = entry.logged_command(log, [sys.executable, "-B", "-c", f"print({value!r})"])
                self.assertEqual(subprocess.run(command, timeout=5).returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ["first", "second"])

    def test_supervised_preflight_rejects_another_running_intent_before_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            instances = Path(temporary)
            (instances / "registry.json").write_text(json.dumps({"profiles": {"foreign": {"desired_state": "running"}}}))
            with patch.object(entry, "INSTANCES", instances), self.assertRaisesRegex(RuntimeError, "another profile"):
                entry.supervisor_preflight()
            (instances / "registry.json").write_text(json.dumps({"profiles": {"foreign": {"desired_state": "stopped"}}}))
            with patch.object(entry, "INSTANCES", instances):
                entry.supervisor_preflight()
            (instances / "supervisor.pid").write_text("1")
            with patch.object(entry, "INSTANCES", instances), self.assertRaisesRegex(RuntimeError, "existing native supervisor"):
                entry.supervisor_preflight()
