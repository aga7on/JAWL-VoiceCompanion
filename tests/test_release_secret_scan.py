from __future__ import annotations

import subprocess
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

    def test_allow_directive_suppresses_a_deliberate_fixture_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = "sk-" + ("C" * 24)
            allowed = root / "test_redaction.py"
            allowed.write_text(
                f'value = "{fake}"  # secret-scan: allow\n', encoding="utf-8"
            )
            other = root / "settings.yaml"
            other.write_text(f"provider_key: {fake}\n", encoding="utf-8")

            self.assertEqual(scan_file(allowed, root), [])
            findings = scan_file(other, root)
            self.assertEqual(len(findings), 1)
            # The directive must not leak into the report either.
            self.assertNotIn(fake, str(findings))

    def test_gitignored_files_are_outside_the_release_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
            (root / ".gitignore").write_text("session-dump.json\n", encoding="utf-8")
            (root / "session-dump.json").write_text(
                '{"key": "sk-' + ("D" * 24) + '"}', encoding="utf-8"
            )
            report = scan_tree(root)
            self.assertTrue(report["pass"])
            self.assertEqual(report["findings"], [])
            self.assertGreaterEqual(report["gitignored_skipped"], 1)
            self.assertTrue(
                all("session-dump" not in finding["path"] for finding in report["findings"])
            )

    def test_tracked_files_are_still_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
            tracked = root / "settings.yaml"
            tracked.write_text("provider_key: sk-" + ("E" * 24) + "\n", encoding="utf-8")
            report = scan_tree(root)
            self.assertFalse(report["pass"])
            self.assertEqual(report["findings"][0]["path"], "settings.yaml")


if __name__ == "__main__":
    unittest.main()
