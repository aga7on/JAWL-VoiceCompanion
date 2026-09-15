from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.release_secret_scan import scan_file, scan_tree


class ReleaseSecretScanTests(unittest.TestCase):
    def test_detects_key_without_returning_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = "sk-" + ("A" * 24)
            path = root / "config.yaml"
            path.write_text(f"provider_key: {value}\n", encoding="utf-8")
            findings = scan_file(path, root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["category"], "api_key_literal")
            self.assertNotIn(value, str(findings))
            self.assertTrue(findings[0]["value_redacted"])

    def test_allows_environment_only_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.yaml"
            path.write_text("api_key: ${LLM_API_KEY_1}\n", encoding="utf-8")
            self.assertEqual(scan_tree(root)["findings"], [])

    def test_skips_generated_runtime_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            runtime.joinpath("log.md").write_text("sk-" + ("B" * 24), encoding="utf-8")
            report = scan_tree(root)
            self.assertTrue(report["pass"])
            self.assertEqual(report["files_scanned"], 0)


if __name__ == "__main__":
    unittest.main()
