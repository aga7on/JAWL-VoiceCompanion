"""Owned entry isolation/wiring; no native snapshot imports or model startup."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("owned_console_test_entry", ROOT / "scripts/run_owned_jawl_console.py")
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


class OwnedConsoleEntryTests(unittest.TestCase):
    def environment(self, root):
        home = root / "runtime/instances/test-entry"
        values = {"JAWL_INSTANCE_HOME": str(home), "JAWL_INSTANCES_ROOT": str(root / "runtime/instances")}
        for key in ("DATA", "CONFIG", "LOG", "CACHE", "PROMPT", "SANDBOX"):
            values[f"JAWL_{key}_DIR"] = str(home / key.lower())
        values["JAWL_ENV_FILE"] = str(home / ".env")
        return values

    def test_missing_home_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            entry.check_isolation()

    def test_owned_home_and_all_paths_are_accepted_without_reading_env_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(entry, "ROOT", root), patch.dict(os.environ, self.environment(root), clear=True):
                entry.check_isolation()
            self.assertFalse((root / "runtime/instances/test-entry/.env").exists())

    def test_outer_home_and_shared_instances_root_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for home in (root, root / "runtime/instances"):
                env = self.environment(root)
                env["JAWL_INSTANCE_HOME"] = str(home)
                with self.subTest(home=home), patch.object(entry, "ROOT", root), patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(ValueError):
                        entry.check_isolation()

    def test_missing_relative_and_escaping_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for key in ("JAWL_DATA_DIR", "JAWL_CONFIG_DIR", "JAWL_LOG_DIR", "JAWL_CACHE_DIR",
                        "JAWL_PROMPT_DIR", "JAWL_SANDBOX_DIR", "JAWL_ENV_FILE"):
                for value in (None, "relative", str(root / "outside")):
                    env = self.environment(root)
                    env.pop(key) if value is None else env.update({key: value})
                    with self.subTest(key=key, value=value), patch.object(entry, "ROOT", root), patch.dict(os.environ, env, clear=True):
                        with self.assertRaises(ValueError):
                            entry.check_isolation()

    def test_foreign_registry_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = self.environment(root)
            env["JAWL_INSTANCES_ROOT"] = str(root / "foreign-registry")
            with patch.object(entry, "ROOT", root), patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                entry.check_isolation()

    def test_source_selection_is_confined_to_managed_snapshot_root(self):
        expected = (ROOT / "runtime/jawl-sources/jawl-20260906-daily-v2").resolve()
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(entry.resolve_source(), expected)
        with tempfile.TemporaryDirectory(dir=ROOT / "runtime/jawl-sources") as temp:
            candidate = Path(temp).resolve()
            with patch.dict(os.environ, {"JAWL_SOURCE_ROOT": str(candidate)}, clear=True):
                self.assertEqual(entry.resolve_source(), candidate)
            outside = Path(temp).parent
            with patch.dict(os.environ, {"JAWL_SOURCE_ROOT": str(outside)}, clear=True):
                with self.assertRaisesRegex(ValueError, "under runtime/jawl-sources"):
                    entry.resolve_source()

    def test_brain_bootstrap_probe_exits_before_native_main_import(self):
        source = (ROOT / "scripts/run_owned_jawl_brain.py").read_text(encoding="utf-8")
        self.assertIn('JAWL_BRAIN_BOOTSTRAP_ONLY") == "1"', source)
        self.assertLess(source.index("write_startup_receipt("),
                        source.index("Owned brain bootstrap probe complete."))
        self.assertLess(source.index("Owned brain bootstrap probe complete."),
                        source.index("from src import main as jawl_main"))

    def test_extension_loads_directly_from_owned_file(self):
        extension = entry.load_extension()
        self.assertEqual(Path(extension.__file__), ROOT / "src/jawl_voicecompanion/native_jawl_admission.py")
        self.assertTrue(callable(extension.install_native_admission))

    def test_delivery_extension_loads_without_importing_native_runtime(self):
        extension = entry.load_delivery_extension()
        self.assertEqual(Path(extension.__file__), ROOT / "src/jawl_voicecompanion/native_jawl_delivery.py")
        self.assertTrue(callable(extension.install_native_delivery_guard))

    def test_turn_context_extension_is_retired_into_the_kernel(self):
        with self.assertRaisesRegex(RuntimeError, "kernel"):
            entry.load_turn_context_extension()

    def test_main_checks_isolation_and_snapshot_before_native_import(self):
        actions = []
        server = SimpleNamespace(chatsrc=SimpleNamespace(bridge=object()))
        app = object()
        server.make_app = lambda token=None: (actions.append(("native", token)) or app)
        server.main = lambda: self.assertIs(server.make_app("fixture"), app)
        extension = SimpleNamespace(install_native_admission=lambda a, b: actions.append(("extension", a, b)))
        delivery = SimpleNamespace(install_native_delivery_guard=lambda: actions.append(("delivery",)))
        fake_manager_cls = type("FakeInstanceManager", (), {"supervisor_status": lambda self: {"running": False, "pid": None}})
        modules = {"verify_jawl_snapshot": SimpleNamespace(verify=lambda source: actions.append(("verify", source))),
                   "src.web": SimpleNamespace(server=server, agent=SimpleNamespace(ROOT_DIR=ROOT)),
                   "src.web.agent": SimpleNamespace(ROOT_DIR=ROOT),
                   "src.instances.manager": SimpleNamespace(InstanceManager=fake_manager_cls)}
        with patch.object(entry, "check_isolation", side_effect=lambda: actions.append(("isolation",))), \
                patch.object(entry, "load_extension", return_value=extension), patch.dict(sys.modules, modules), \
                patch.object(entry, "load_delivery_extension", return_value=delivery), \
                patch.dict(os.environ), patch.object(sys, "path", list(sys.path)), patch.object(sys, "dont_write_bytecode", False):
            self.assertEqual(entry.main(), 0)
            self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual(os.environ["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(actions[0], ("isolation",))
        self.assertEqual(actions[1], ("verify", entry.resolve_source()))
        self.assertEqual(actions[2], ("delivery",))
        self.assertEqual(actions[3], ("native", "fixture"))
        self.assertEqual(actions[4], ("extension", app, server.chatsrc.bridge))

    def test_failed_snapshot_never_starts_native_console(self):
        server = SimpleNamespace(main=lambda: self.fail("native main called"))
        modules = {"verify_jawl_snapshot": SimpleNamespace(verify=lambda source: (_ for _ in ()).throw(ValueError("snapshot"))),
                   "src.web": SimpleNamespace(server=server, agent=SimpleNamespace()),
                   "src.web.agent": SimpleNamespace()}
        with patch.object(entry, "check_isolation"), patch.dict(sys.modules, modules), patch.dict(os.environ), \
                patch.object(sys, "dont_write_bytecode", False), self.assertRaisesRegex(ValueError, "snapshot"):
            entry.main()

    def test_launchers_select_owned_entry_and_integrated_readback(self):
        for name in ("run_daily_profile.ps1", "run_integrated_profile.ps1"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("run_owned_jawl_console.py", text)
            self.assertNotIn("-m src.web.server", text)
        text = (ROOT / "scripts/run_integrated_profile.ps1").read_text(encoding="utf-8")
        self.assertIn("/api/companion/admission-capabilities", text)
        self.assertIn("http-turn-admission-v1", text)

    def test_integrated_launcher_confines_and_propagates_source_snapshot(self):
        text = (ROOT / "scripts/run_integrated_profile.ps1").read_text(encoding="utf-8")
        self.assertIn("JawlSourceRoot", text)
        self.assertIn("runtime\\jawl-sources", text)
        self.assertIn("$jawlEnv['JAWL_SOURCE_ROOT'] = $source", text)
        self.assertIn("verify_jawl_snapshot.py", text)
        self.assertIn("run_owned_jawl_supervisor.py", text)
        reg_text = (ROOT / "scripts/register_supervised_profile.py").read_text(encoding="utf-8")
        self.assertIn("run_owned_jawl_brain.py", reg_text)
        sup_text = (ROOT / "scripts/run_owned_jawl_supervisor.py").read_text(encoding="utf-8")
        self.assertIn("run_owned_jawl_brain.py", sup_text)

    def test_console_token_redaction_handles_split_writes_and_flush(self):
        output = io.StringIO()
        stream = entry.RedactedConsole(output, ["fixture-secret"])
        stream.write("raw fixture-")
        stream.flush()
        self.assertEqual(output.getvalue(), "")
        stream.write("secret http://localhost/?token=other-secret\n")
        self.assertNotIn("fixture-secret", output.getvalue())
        self.assertNotIn("other-secret", output.getvalue())
        self.assertIn("<redacted>", output.getvalue())

    def test_native_generated_token_and_oversized_line_are_not_logged(self):
        output = io.StringIO()
        stream = entry.RedactedConsole(output)
        stream.write("сгенерирован токен доступа:\n  generated-secret\n")
        stream.write("x" * 9000)
        stream.write("tail-secret\nnext-safe-line\n")
        self.assertNotIn("generated-secret", output.getvalue())
        self.assertNotIn("tail-secret", output.getvalue())
        self.assertLess(len(output.getvalue()), 300)
        self.assertIn("next-safe-line", output.getvalue())


if __name__ == "__main__":
    unittest.main()
