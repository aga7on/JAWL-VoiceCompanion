"""Brain isolation and startup identity, without importing the protected source."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# The startup receipt reads kernel constants (context capacity) after hook
# validation; make the pinned snapshot importable for that lookup.
sys.path.insert(0, str(ROOT / "runtime/jawl-sources/jawl-20260906-daily-v2"))
spec = importlib.util.spec_from_file_location("owned_brain_test_entry", ROOT / "scripts/run_owned_jawl_brain.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class OwnedBrainEntryTests(unittest.TestCase):
    @staticmethod
    def environment(root):
        home = root / "runtime/instances/brain-fixture"
        env = {"JAWL_INSTANCE_HOME": str(home), "JAWL_INSTANCE_ID": "brain-fixture",
               "JAWL_INSTANCES_ROOT": str(root / "runtime/instances"), "JAWL_ENV_FILE": str(home / ".env")}
        for name in ("DATA", "CONFIG", "LOG", "CACHE", "PROMPT", "SANDBOX"):
            env[f"JAWL_{name}_DIR"] = str(home / name.lower())
        return env

    @staticmethod
    def installations():
        classes = [type(name, (), {}) for name in ("Loop", "Terminal", "Bus")]
        delivery = SimpleNamespace(react_loop_class=classes[0], terminal_client_class=classes[1], event_bus_class=classes[2])
        for cls in classes:
            setattr(cls, "__jawl_native_delivery_guard_installation__", delivery)
        return delivery

    def test_missing_or_foreign_paths_fail_before_source_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = self.environment(root)
            for key in env:
                invalid = (None, "invalid!", "x" * 49) if key == "JAWL_INSTANCE_ID" else (None, "relative", str(root / "outside"))
                for bad in invalid:
                    values = dict(env)
                    values.pop(key) if bad is None else values.update({key: bad})
                    with self.subTest(key=key, bad=bad), patch.object(entry, "ROOT", root), patch.dict(os.environ, values, clear=True):
                        with self.assertRaises(ValueError):
                            entry.check_isolation(require_clean_import=False)
            self.assertFalse((root / "outside").exists())

    def test_preimported_native_source_is_refused_before_main(self):
        with patch.dict(sys.modules, {"src": SimpleNamespace()}), self.assertRaises(RuntimeError):
            entry.check_isolation()

    def test_receipt_is_atomic_bounded_and_contains_actual_process_and_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = self.environment(root)
            env.update(CONSOLE_TOKEN="PRIVATE_SENTINEL", JAWL_BRAIN_BOOTSTRAP_ONLY="1")
            delivery = self.installations()
            snapshot = {"source": str(root / "runtime/jawl-sources/fixture"), "snapshot_sha256": "a" * 64}
            with patch.object(entry, "ROOT", root), patch.dict(os.environ, env, clear=True):
                receipt = entry.write_startup_receipt(snapshot, delivery)
            path = Path(env["JAWL_LOG_DIR"]) / "owned-brain-startup.json"
            text = path.read_text(encoding="utf-8")
            self.assertLess(len(text), 4096)
            self.assertEqual(json.loads(text), receipt)
            self.assertEqual(receipt["pid"], os.getpid())
            self.assertEqual(receipt["parent_pid"], os.getppid())
            self.assertGreater(receipt["process_created_at"], 0)
            self.assertEqual(receipt["hooks"], {"delivery_guard": True})
            self.assertTrue(receipt["bootstrap_only"])
            self.assertNotIn("PRIVATE_SENTINEL", text)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            self.assertFalse(Path(env["JAWL_ENV_FILE"]).exists())

    def test_missing_hook_or_replaced_wrapper_never_writes_success_receipt(self):
        for replace_wrapper in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                env = self.environment(root)
                delivery = self.installations()
                if replace_wrapper:
                    delivery.react_loop_class.__jawl_native_delivery_guard_installation__ = object()
                else:
                    delattr(delivery.event_bus_class, "__jawl_native_delivery_guard_installation__")
                with patch.object(entry, "ROOT", root), patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(RuntimeError, "hooks"):
                    entry.write_startup_receipt({}, delivery)
                self.assertFalse(Path(env["JAWL_LOG_DIR"]).exists())

    def test_invalid_environment_prevents_even_snapshot_verification(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(entry, "resolve_source") as source:
            with self.assertRaises((ValueError, RuntimeError)):
                entry.main()
        source.assert_not_called()
