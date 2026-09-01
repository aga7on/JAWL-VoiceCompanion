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


if __name__ == "__main__":
    unittest.main()
