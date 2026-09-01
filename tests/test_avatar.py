import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from jawl_voicecompanion.avatar import AvatarAssetStore  # noqa: E402


class AvatarAssetStoreTests(unittest.TestCase):
    def test_config_requires_model_and_runtime_and_serves_nested_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "model3.json").write_text("{}", encoding="utf-8")
            (root / "live2d-runtime.js").write_text("runtime", encoding="utf-8")
            (root / "textures").mkdir()
            (root / "textures" / "body.png").write_bytes(b"png")
            store = AvatarAssetStore(root)
            self.assertTrue(store.config()["enabled"])
            self.assertEqual(store.resolve_public("textures/body.png").read_bytes(), b"png")
            self.assertIsNone(store.resolve_public("../outside.txt"))

    def test_missing_runtime_stays_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "model3.json").write_text("{}", encoding="utf-8")
            self.assertFalse(AvatarAssetStore(root).config()["enabled"])

    def test_model_references_are_validated_relative_to_model_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir = root / "character" / "runtime"
            texture_dir = model_dir / "textures"
            texture_dir.mkdir(parents=True)
            (model_dir / "companion.model3.json").write_text(
                '{"FileReferences":{"Moc":"companion.moc3","Textures":["textures/body.png"],'
                '"Motions":{"Idle":[{"File":"idle.motion3.json"}]}}}',
                encoding="utf-8",
            )
            (model_dir / "companion.moc3").write_bytes(b"moc")
            (model_dir / "idle.motion3.json").write_text("{}", encoding="utf-8")
            (texture_dir / "body.png").write_bytes(b"png")
            (root / "live2d-runtime.js").write_text("runtime", encoding="utf-8")
            config = AvatarAssetStore(
                root, model="character/runtime/companion.model3.json"
            ).config()
            self.assertTrue(config["enabled"])
            self.assertTrue(config["ready"])
            self.assertEqual(config["validation"]["motion_groups"], ["Idle"])
            self.assertEqual(config["validation"]["missing"], [])

    def test_missing_fatal_model_reference_keeps_placeholder_ready_false(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "model3.json").write_text(
                '{"FileReferences":{"Moc":"missing.moc3","Textures":["body.png"]}}',
                encoding="utf-8",
            )
            (root / "body.png").write_bytes(b"png")
            (root / "live2d-runtime.js").write_text("runtime", encoding="utf-8")
            config = AvatarAssetStore(root).config()
            self.assertTrue(config["enabled"])
            self.assertFalse(config["ready"])
            self.assertEqual(config["validation"]["missing"][0]["type"], "Moc")

    def test_optional_reference_is_a_warning_not_a_render_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "model3.json").write_text(
                '{"FileReferences":{"Moc":"companion.moc3","Textures":["body.png"],'
                '"Motions":{"Idle":[{"File":"missing.motion3.json"}]}}}',
                encoding="utf-8",
            )
            (root / "companion.moc3").write_bytes(b"moc")
            (root / "body.png").write_bytes(b"png")
            (root / "live2d-runtime.js").write_text("runtime", encoding="utf-8")
            config = AvatarAssetStore(root).config()
            self.assertTrue(config["ready"])
            self.assertFalse(config["validation"]["missing"][0]["fatal"])
            self.assertTrue(config["validation"]["warnings"])


if __name__ == "__main__":
    unittest.main()
