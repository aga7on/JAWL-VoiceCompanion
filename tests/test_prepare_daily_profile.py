import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_daily_profile", ROOT / "scripts" / "prepare_daily_profile.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrepareDailyProfileTests(unittest.TestCase):
    def _layout(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "source"
        config = root / "config"
        profile = root / "profile"
        (source / "src" / "l3_agent" / "prompt" / "system").mkdir(parents=True)
        (config / "prompts" / "custom").mkdir(parents=True)
        (source / "src" / "l3_agent" / "prompt" / "system" / "INSTRUCTIONS.md").write_text(
            "system prompt\n", encoding="utf-8"
        )
        (source / "SOURCE_MANIFEST.json").write_text(
            json.dumps(
                {
                    "name": "test-source",
                    "files": {"src/l3_agent/prompt/system/INSTRUCTIONS.md": "a" * 64},
                    "snapshot_sha256": "b" * 64,
                }
            ),
            encoding="utf-8",
        )
        (config / "SOUL.md").write_text("soul\n", encoding="utf-8")
        (config / "settings.yaml").write_text("llm: {}\n", encoding="utf-8")
        (config / "interfaces.yaml").write_text("interfaces: {}\n", encoding="utf-8")
        (config / "prompts" / "custom" / "RESPOND_DIRECTLY.md").write_text(
            "respond\n", encoding="utf-8"
        )
        return source, config, profile

    def test_prepare_creates_manifest_and_separate_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            source, config, profile = self._layout(Path(temp))
            with patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile):
                result = MODULE.prepare()

            self.assertIn("created_files=5", result)
            self.assertTrue((profile / "cache").is_dir())
            manifest = json.loads((profile / MODULE.MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["conflicts"], [])
            self.assertIn("config/settings.yaml", manifest["managed"])
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["source"]["name"], "test-source")

    def test_prepare_provisions_embedding_into_profile_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, config, profile = self._layout(root)
            asset_root = root / "asset"
            model = asset_root / MODULE.EMBEDDING_RELATIVE
            model.parent.mkdir(parents=True)
            model.write_bytes(b"verified-embedding")
            with patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile), patch.object(
                MODULE, "EMBEDDING_ASSET_ROOT", asset_root
            ), patch.object(MODULE, "EMBEDDING_BOOTSTRAP_ROOT", root / "unused"):
                result = MODULE.prepare()

            self.assertTrue(any(line.startswith("embedding_cache=provisioned:") for line in result))
            self.assertEqual(
                (profile / "data" / "vector" / "embeddings" / MODULE.EMBEDDING_RELATIVE).read_bytes(),
                b"verified-embedding",
            )

    def test_conflict_is_fail_closed_and_does_not_advance_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            source, config, profile = self._layout(Path(temp))
            paths = patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile)
            with paths[0], paths[1], paths[2]:
                MODULE.prepare()
                target = profile / "config" / "settings.yaml"
                target.write_text("user override\n", encoding="utf-8")
                (config / "settings.yaml").write_text("new managed default\n", encoding="utf-8")
                manifest_path = profile / MODULE.MANIFEST_NAME
                before_manifest = manifest_path.read_bytes()

                with self.assertRaises(MODULE.ProfileConflict):
                    MODULE.prepare()

                self.assertEqual(target.read_text(encoding="utf-8"), "user override\n")
                self.assertEqual(manifest_path.read_bytes(), before_manifest)

                MODULE.prepare(sync=True)
                self.assertEqual(target.read_text(encoding="utf-8"), "new managed default\n")
                self.assertEqual(
                    (profile / "config" / "settings.yaml.bak").read_text(encoding="utf-8"),
                    "user override\n",
                )

    def test_jawl_generated_yaml_superset_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            source, config, profile = self._layout(Path(temp))
            (config / "settings.yaml").write_text(
                "llm:\n  model: baseline\n", encoding="utf-8"
            )
            with patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile):
                MODULE.prepare()
                target = profile / "config" / "settings.yaml"
                target.write_text(
                    "llm:\n  model: baseline\n  generated_default: true\n",
                    encoding="utf-8",
                )
                MODULE.prepare()

            self.assertIn("generated_default: true", target.read_text(encoding="utf-8"))

    def test_launcher_native_switches_are_approved_profile_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            source, config, profile = self._layout(Path(temp))
            interfaces = "host:\n  os:\n    enabled: true\n    access_level: 0\n" \
                "debug_broker: {enabled: false}\n"
            (config / "interfaces.yaml").write_text(interfaces, encoding="utf-8")
            with patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile):
                MODULE.prepare()
                target = profile / "config" / "interfaces.yaml"
                target.write_text(
                    "host:\n  os:\n    enabled: true\n    access_level: 3\n"
                    "debug_broker: {enabled: true}\n",
                    encoding="utf-8",
                )
                MODULE.prepare()

            self.assertIn("access_level: 3", target.read_text(encoding="utf-8"))
            self.assertIn("enabled: true", target.read_text(encoding="utf-8"))

    def test_explicit_model_override_is_approved_but_unmarked_edit_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            source, config, profile = self._layout(Path(temp))
            (config / "settings.yaml").write_text(
                "llm:\n  main_model: baseline-model\n  temperature: 0.2\n",
                encoding="utf-8",
            )
            with patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile):
                MODULE.prepare()
                target = profile / "config" / "settings.yaml"
                target.write_text(
                    "llm:\n  main_model: candidate-model\n  temperature: 0.2\n",
                    encoding="utf-8",
                )
                with self.assertRaises(MODULE.ProfileConflict):
                    MODULE.prepare()
                with patch.dict(MODULE.os.environ, {"JAWL_MODEL_OVERRIDE": "candidate-model"}):
                    MODULE.prepare()
                self.assertIn("candidate-model", target.read_text(encoding="utf-8"))

    def test_explicit_temperature_override_is_approved_but_unmarked_edit_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            source, config, profile = self._layout(Path(temp))
            (config / "settings.yaml").write_text(
                "llm:\n  main_model: baseline-model\n  temperature: 1.0\n",
                encoding="utf-8",
            )
            with patch.object(MODULE, "SOURCE_ROOT", source), patch.object(
                MODULE, "CONFIG_ROOT", config
            ), patch.object(MODULE, "PROFILE_ROOT", profile):
                MODULE.prepare()
                target = profile / "config" / "settings.yaml"
                target.write_text(
                    "llm:\n  main_model: baseline-model\n  temperature: 0.2\n",
                    encoding="utf-8",
                )
                with self.assertRaises(MODULE.ProfileConflict):
                    MODULE.prepare()
                with patch.dict(MODULE.os.environ, {"JAWL_TEMPERATURE_OVERRIDE": "0.2"}):
                    MODULE.prepare()
                self.assertIn("temperature: 0.2", target.read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
