from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "configure_profile_native", ROOT / "scripts" / "configure_profile_native.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ConfigureProfileNativeTests(unittest.TestCase):
    def test_small_managed_context_receives_scaled_budget_and_valid_receipt(self):
        from scripts.native_context_budget import approved_profile_budget

        with tempfile.TemporaryDirectory() as directory:
            instances = Path(directory) / "instances"
            profile = instances / "qwen"
            config = profile / "config"
            config.mkdir(parents=True)
            (config / "settings.yaml").write_text(
                "llm: {main_model: local-qwen3-omni}\n",
                encoding="utf-8",
            )
            (config / "interfaces.yaml").write_text(
                "host:\n  os:\n    enabled: true\n    access_level: 0\n",
                encoding="utf-8",
            )
            with patch.object(MODULE, "INSTANCES_ROOT", instances):
                MODULE.configure(
                    "qwen", access_level=0, enable_debug_broker=False,
                    context_window_tokens=12288,
                )

            settings = MODULE.yaml.safe_load((config / "settings.yaml").read_text(encoding="utf-8"))
            budget = settings["system"]["context_depth"]["budget"]
            self.assertEqual(budget["max_dynamic_chars"], 9000)
            receipt_budget = approved_profile_budget(profile)
            self.assertEqual(receipt_budget["max_dynamic_chars"], 9000)

    def test_changes_only_selected_profile_and_keeps_other_interfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            instances = Path(directory) / "instances"
            profile = instances / "test"
            config = profile / "config"
            config.mkdir(parents=True)
            daily = instances / "daily" / "config"
            daily.mkdir(parents=True)
            (daily / "settings.yaml").write_bytes(b"daily settings must stay untouched\n")
            (daily / "interfaces.yaml").write_bytes(b"daily interfaces must stay untouched\n")
            (config / "settings.yaml").write_text(
                "identity: {agent_name: baseline}\n"
                "llm:\n  main_model: baseline-model\n  available_models: [baseline-model]\n",
                encoding="utf-8",
            )
            (config / "interfaces.yaml").write_text(
                "host:\n  os:\n    enabled: true\n    access_level: 0\n"
                "debug_broker: {enabled: false}\nweb:\n  browser:\n    enabled: false\n",
                encoding="utf-8",
            )
            with patch.object(MODULE, "INSTANCES_ROOT", instances):
                result = MODULE.configure(
                    "test", access_level=3, enable_debug_broker=True,
                    model_override="candidate-model:latest",
                    temperature_override="0.2",
                )
            self.assertEqual(result, config / "interfaces.yaml")
            payload = MODULE.yaml.safe_load(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["host"]["os"]["access_level"], 3)
            self.assertTrue(payload["debug_broker"]["enabled"])
            self.assertFalse(payload["web"]["browser"]["enabled"])
            settings = MODULE.yaml.safe_load(
                (config / "settings.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(settings["llm"]["main_model"], "candidate-model:latest")
            self.assertEqual(settings["llm"]["temperature"], 0.2)
            self.assertEqual((daily / "settings.yaml").read_bytes(), b"daily settings must stay untouched\n")
            self.assertEqual((daily / "interfaces.yaml").read_bytes(), b"daily interfaces must stay untouched\n")
            with patch.object(MODULE, "INSTANCES_ROOT", instances):
                MODULE.configure("test", access_level=0, enable_debug_broker=False, enable_browser=True,
                                 context_window_tokens=65536)
                enabled = MODULE.yaml.safe_load(result.read_text(encoding="utf-8"))
                self.assertTrue(enabled["web"]["browser"]["enabled"])
                self.assertTrue(enabled["web"]["browser"]["headless"])
                selected_settings = MODULE.yaml.safe_load((config / "settings.yaml").read_text(encoding="utf-8"))
                self.assertEqual(selected_settings["system"]["context_depth"]["budget"]["max_dynamic_chars"], 48000)
                self.assertTrue((profile / MODULE.RECEIPT_NAME).exists())
                MODULE.configure("test", access_level=0, enable_debug_broker=False)
                self.assertTrue(MODULE.yaml.safe_load(result.read_text(encoding="utf-8"))["web"]["browser"]["enabled"])
            self.assertEqual((daily / "interfaces.yaml").read_bytes(), b"daily interfaces must stay untouched\n")

    def test_rejects_invalid_temperature_override(self):
        with tempfile.TemporaryDirectory() as directory:
            instances = Path(directory) / "instances"
            config = instances / "test" / "config"
            config.mkdir(parents=True)
            (config / "settings.yaml").write_text("llm: {temperature: 1.0}\n", encoding="utf-8")
            (config / "interfaces.yaml").write_text(
                "host:\n  os:\n    enabled: true\n    access_level: 0\n",
                encoding="utf-8",
            )
            with patch.object(MODULE, "INSTANCES_ROOT", instances):
                with self.assertRaises(ValueError):
                    MODULE.configure(
                        "test", access_level=0, enable_debug_broker=False,
                        temperature_override="2.1",
                    )

    def test_rejects_path_escape_and_invalid_level(self):
        with self.assertRaises(ValueError):
            MODULE._profile_root("..")
        with self.assertRaises(ValueError):
            MODULE.configure("missing", access_level=4, enable_debug_broker=False)


if __name__ == "__main__":
    unittest.main()
