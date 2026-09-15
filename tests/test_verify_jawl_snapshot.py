import json
import importlib
import logging
import os
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from verify_jawl_snapshot import verify  # noqa: E402


class VerifyJawlSnapshotTests(unittest.TestCase):
    def test_native_instance_manager_uses_launcher_roots_for_supervisor(self):
        snapshot_root = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
        )
        old_instances = os.environ.get("JAWL_INSTANCES_ROOT")
        old_sandbox = os.environ.get("JAWL_SANDBOX_DIR")
        old_log_dir = os.environ.get("JAWL_LOG_DIR")
        old_instance_id = os.environ.get("JAWL_INSTANCE_ID")
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            os.environ["JAWL_INSTANCES_ROOT"] = str(temp_root / "instances")
            os.environ["JAWL_SANDBOX_DIR"] = str(temp_root / "sandbox")
            os.environ["JAWL_LOG_DIR"] = str(temp_root / "logs")
            # Use a valid disposable ID so this import probe is independent of
            # gate ordering and the native instance-id validator.
            os.environ["JAWL_INSTANCE_ID"] = "snapshot-probe"
            sys.path.insert(0, str(snapshot_root))
            before_modules = set(sys.modules)
            try:
                manager_module = importlib.import_module("src.instances.manager")
                manager = manager_module.InstanceManager(snapshot_root)
                self.assertEqual(manager.instances_root, temp_root / "instances")
                self.assertEqual(manager.shared_sandbox, temp_root / "sandbox")
                self.assertTrue((temp_root / "instances" / "registry.json").is_file())
            finally:
                logging.shutdown()
                sys.path.pop(0)
                for name in list(sys.modules):
                    if name not in before_modules and (
                        name == "src" or name.startswith("src.")
                    ):
                        sys.modules.pop(name, None)
                if old_instances is None:
                    os.environ.pop("JAWL_INSTANCES_ROOT", None)
                else:
                    os.environ["JAWL_INSTANCES_ROOT"] = old_instances
                if old_sandbox is None:
                    os.environ.pop("JAWL_SANDBOX_DIR", None)
                else:
                    os.environ["JAWL_SANDBOX_DIR"] = old_sandbox
                if old_log_dir is None:
                    os.environ.pop("JAWL_LOG_DIR", None)
                else:
                    os.environ["JAWL_LOG_DIR"] = old_log_dir
                if old_instance_id is None:
                    os.environ.pop("JAWL_INSTANCE_ID", None)
                else:
                    os.environ["JAWL_INSTANCE_ID"] = old_instance_id

    def test_model_legacy_execute_skill_wrapper_is_unwrapped_without_aliasing_unknown_tools(self):
        snapshot_root = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
        )
        sys.path.insert(0, str(snapshot_root))
        try:
            schema = importlib.import_module("src.l3_agent.skills.schema")
            payload = {
                "observation": "",
                "reasoning": "",
                "reflection": "compatibility probe",
                "actions": [
                    {
                        "tool_name": "execute_skill",
                        "parameters": {
                            "v": 2,
                            "state": "act",
                            "calls": [
                                {
                                    "tool": "HostTerminalMessages.send_message_to_terminal",
                                    "args": {"text": "OK"},
                                }
                            ],
                        },
                    }
                ],
            }
            parsed, error = schema.parse_llm_json(json.dumps(payload))
            self.assertIsNone(error)
            self.assertIsNotNone(parsed)
            self.assertEqual(
                parsed.actions[0].tool_name,
                "HostTerminalMessages.send_message_to_terminal",
            )
            self.assertEqual(parsed.actions[0].parameters["text"], "OK")

            terminal_payload = {
                "observation": "verified",
                "reasoning": "done",
                "reflection": "done",
                "actions": [
                    {
                        "tool_name": "execute_skill",
                        "parameters": {
                            "v": 2,
                            "state": "done",
                            "summary": "The marker was verified.",
                            "calls": [],
                        },
                    }
                ],
            }
            terminal, terminal_error = schema.parse_llm_json(
                json.dumps(terminal_payload)
            )
            self.assertIsNone(terminal_error)
            self.assertIsNotNone(terminal)
            self.assertEqual(terminal.actions, [])
            self.assertEqual(terminal.goal_state, "done")
            self.assertEqual(terminal.goal_summary, "The marker was verified.")

            unknown = dict(payload)
            unknown["actions"] = [
                {
                    "tool_name": "execute_skill",
                    "parameters": {"calls": [{"tool": "SQLTasks.list_all_tasks", "args": {}}]},
                }
            ]
            unknown_parsed, _ = schema.parse_llm_json(json.dumps(unknown))
            self.assertIsNotNone(unknown_parsed)
            self.assertEqual(unknown_parsed.actions[0].tool_name, "execute_skill")

            wrapped_terminal_payload = {
                "observation": "verified",
                "reasoning": "done",
                "reflection": "done",
                "actions": [
                    {
                        "tool_name": "HostTerminalMessages.send_message_to_terminal",
                        "parameters": {
                            "text": json.dumps(
                                {
                                    "v": 2,
                                    "state": "done",
                                    "summary": "The marker was verified.",
                                    "calls": [],
                                }
                            )
                        },
                    }
                ],
            }
            wrapped_terminal, wrapped_error = schema.parse_llm_json(
                json.dumps(wrapped_terminal_payload)
            )
            self.assertIsNone(wrapped_error)
            self.assertIsNotNone(wrapped_terminal)
            self.assertEqual(wrapped_terminal.actions, [])
            self.assertEqual(wrapped_terminal.goal_state, "done")
            self.assertEqual(
                wrapped_terminal.goal_summary, "The marker was verified."
            )

            ordinary_terminal = dict(wrapped_terminal_payload)
            ordinary_terminal["actions"] = [
                {
                    "tool_name": "HostTerminalMessages.send_message_to_terminal",
                    "parameters": {"text": "ordinary terminal message"},
                }
            ]
            ordinary, ordinary_error = schema.parse_llm_json(
                json.dumps(ordinary_terminal)
            )
            self.assertIsNone(ordinary_error)
            self.assertIsNotNone(ordinary)
            self.assertEqual(
                ordinary.actions[0].tool_name,
                "HostTerminalMessages.send_message_to_terminal",
            )
        finally:
            sys.path.pop(0)

    def test_managed_snapshot_keeps_goal_memory_and_native_context_namespaces_visible(self):
        source = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
            / "src"
            / "l3_agent"
            / "context"
            / "builder.py"
        ).read_text(encoding="utf-8")
        for namespace in (
            '"GoalSkills"',
            '"SQLStructuredMemory"',
            '"HostOSWriter"',
            '"HostOSReader"',
            '"HostOSChecking"',
            '"HostTerminalMessages"',
        ):
            self.assertIn(namespace, source)

    def test_managed_snapshot_keeps_only_compatibility_alias_for_stale_terminal_namespace(self):
        source = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
            / "src"
            / "l3_agent"
            / "skills"
            / "registry.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"HostOSJournalMessages.send_message_to_terminal"', source)
        self.assertIn('"HostTerminalMessages.send_message_to_terminal"', source)

    def test_managed_snapshot_keeps_native_supervisor_lifecycle_boundary(self):
        root = (
            Path(__file__).parents[1]
            / "runtime"
            / "jawl-sources"
            / "jawl-20260906-daily-v2"
        )
        manager = (root / "src" / "instances" / "manager.py").read_text(encoding="utf-8")
        agent = (root / "src" / "web" / "agent.py").read_text(encoding="utf-8")
        self.assertIn('JAWL_INSTANCES_ROOT', manager)
        self.assertIn('JAWL_SANDBOX_DIR', manager)
        self.assertIn('JAWL_SUPERVISED', agent)
        self.assertIn('request_start(INSTANCE_PATHS.instance_id)', agent)
        self.assertIn('request_stop(INSTANCE_PATHS.instance_id)', agent)

    def test_manifest_hashes_and_digest_are_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "src" / "module.py"
            file.parent.mkdir()
            file.write_bytes(b"print('ok')\n")
            import hashlib

            files = {"src/module.py": hashlib.sha256(file.read_bytes()).hexdigest()}
            digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            (root / "SOURCE_MANIFEST.json").write_text(
                json.dumps({"name": "test", "files": files, "snapshot_sha256": digest}),
                encoding="utf-8",
            )
            result = verify(root)
            self.assertTrue(result["ok"])
            self.assertEqual(result["file_count"], 1)

    def test_hash_mismatch_fails_without_disclosing_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "module.py"
            file.write_bytes(b"secret-shaped-content")
            (root / "SOURCE_MANIFEST.json").write_text(
                json.dumps({"files": {"module.py": "0" * 64}, "snapshot_sha256": "0" * 64}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify(root)

    def test_extra_snapshot_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tracked = root / "tracked.txt"
            tracked.write_text("ok", encoding="utf-8")
            (root / "extra.txt").write_text("unexpected", encoding="utf-8")
            import hashlib

            files = {"tracked.txt": hashlib.sha256(tracked.read_bytes()).hexdigest()}
            digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            (root / "SOURCE_MANIFEST.json").write_text(
                json.dumps({"files": files, "snapshot_sha256": digest}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "absent from manifest"):
                verify(root)

    def test_generated_python_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tracked = root / "module.py"
            tracked.write_text("print('ok')\n", encoding="utf-8")
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "module.cpython-314.pyc").write_bytes(b"generated")
            import hashlib

            files = {"module.py": hashlib.sha256(tracked.read_bytes()).hexdigest()}
            digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            (root / "SOURCE_MANIFEST.json").write_text(
                json.dumps({"files": files, "snapshot_sha256": digest}), encoding="utf-8"
            )
            result = verify(root)
            self.assertTrue(result["ok"])
            self.assertEqual(result["file_count"], 1)


if __name__ == "__main__":
    unittest.main()
