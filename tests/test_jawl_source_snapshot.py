import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "snapshot", Path(__file__).parents[1] / "scripts/stage_jawl_source.py"
)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SourceSnapshotTests(unittest.TestCase):
    def test_selection_excludes_working_state_and_persona(self):
        for path in (".env", "config/settings.yaml", "src/utils/local/data/x.py",
                     "src/l3_agent/prompt/personality/SOUL.md", "src/__pycache__/a.pyc"):
            self.assertFalse(snapshot.selected(Path(path)), path)
        self.assertTrue(snapshot.selected(Path("src/l3_agent/prompt/personality/SOUL.example.md")))

    def test_snapshot_is_hashed_nonoverwriting_and_dry_run_has_no_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "reference"
            (source / "src").mkdir(parents=True)
            (source / "web").mkdir()
            (source / "config").mkdir()
            for name in ("LICENSE", "requirements.txt", "pyproject.toml",
                         "config/settings.example.yaml", "config/interfaces.example.yaml",
                         "src/main.py", "web/index.html"):
                (source / name).write_text("fixture", encoding="utf-8")
            (source / ".env").write_text("sk-" + "X" * 30, encoding="utf-8")
            with patch.object(snapshot, "ROOT", root):
                preview = snapshot.stage(source, "test")
                self.assertFalse((root / "runtime").exists())
                written = snapshot.stage(source, "test", write=True)
                self.assertEqual(preview["snapshot_sha256"], written["snapshot_sha256"])
                destination = root / "runtime/jawl-sources/test"
                manifest = json.loads((destination / "SOURCE_MANIFEST.json").read_text())
                self.assertEqual(len(manifest["files"]), 7)
                self.assertFalse((destination / ".env").exists())
                with self.assertRaises(ValueError):
                    snapshot.stage(source, "test", write=True)
                (source / "src/main.py").write_text("sk-" + "X" * 30)
                with self.assertRaises(ValueError):
                    snapshot.stage(source, "secret-rejected", write=True)
                self.assertFalse((root / "runtime/jawl-sources/secret-rejected").exists())
