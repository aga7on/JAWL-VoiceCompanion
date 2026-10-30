"""Regression coverage for the integrated launcher environment diagnostic."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "run_integrated_profile.ps1"


class LauncherDiagnosticRedactionTests(unittest.TestCase):
    def test_launcher_parses_and_environment_diagnostic_redacts_values(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is required for launcher parser/redaction verification")

        launcher_path = str(LAUNCHER).replace("'", "''")
        command = f"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{launcher_path}', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {{ throw ($parseErrors | Out-String) }}
$matches = @($ast.FindAll({{ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Format-EnvironmentDiagnostic'
}}, $true))
if ($matches.Count -ne 1) {{ throw 'Expected exactly one production formatter function.' }}
Invoke-Expression $matches[0].Extent.Text
$fixture = @{{
    JAWL_WEB_TOKEN = 'synthetic-token-must-not-appear'
    FUTURE_API_SECRET = 'synthetic-future-secret-must-not-appear'
    JAWL_CONFIG_DIR = 'C:\\fixture path'
    EMPTY_OPTION = ''
}}
$lines = @(Format-EnvironmentDiagnostic -Environment $fixture)
[Console]::Out.WriteLine(($lines | ConvertTo-Json -Compress))
"""
        encoded_command = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_command],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout.strip().splitlines()[-1])
        if isinstance(output, str):
            output = [output]
        self.assertEqual(
            output,
            [
                "ENV EMPTY_OPTION=<unset>",
                "ENV FUTURE_API_SECRET=<configured>",
                "ENV JAWL_CONFIG_DIR=<configured>",
                "ENV JAWL_WEB_TOKEN=<configured>",
            ],
        )
        self.assertNotIn("synthetic-token-must-not-appear", result.stdout)
        self.assertNotIn("synthetic-future-secret-must-not-appear", result.stdout)
        self.assertNotIn("C:\\fixture path", result.stdout)


if __name__ == "__main__":
    unittest.main()
