"""Metadata baselines must not store raw source/diff or overwrite reports."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("capture_baseline_test", ROOT / "scripts" / "capture_runtime_baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class RuntimeBaselineTests(unittest.TestCase):
    def test_hashes_sources_and_diff_without_preserving_raw_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "fixture.py").write_text("private_source_value", encoding="utf-8")
            (root / "src" / ".env").write_text("private_environment_value", encoding="utf-8")
            manifest = {"models": {}, "profile": "fixture", "ports": {}, "brain": {}, "vision": {}, "launch": {}}

            def fake_git(_root, command, *args):
                return {
                    "ls-files": b"src/fixture.py\x00src/.env\x00",
                    "status": b" M src/fixture.py\n",
                    "diff": b"private_diff_value",
                    "rev-parse": b"fixture-head\n",
                }[command]

            with patch.object(baseline, "git", side_effect=fake_git), \
                 patch.object(baseline, "load_runtime_manifest", return_value=manifest), \
                 patch.object(baseline, "verify", return_value={"ok": True}):
                report = baseline.capture(root)
            encoded = json.dumps(report)
            self.assertEqual(report["source_count"], 1)
            self.assertTrue(report["dirty"])
            self.assertEqual(report["head"], "fixture-head")
            for private in ("private_source_value", "private_environment_value", "private_diff_value"):
                self.assertNotIn(private, encoded)
            self.assertEqual(set(report["source_hashes"]), {"src/fixture.py"})

    def test_cli_refuses_outside_target_without_creating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "outside.json"
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "capture_runtime_baseline.py"),
                                     "--report", str(target)], capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
