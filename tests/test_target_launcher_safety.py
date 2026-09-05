from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_target_jawl_smoke.ps1"


class TargetLauncherSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.powershell = shutil.which("powershell") or shutil.which("pwsh")

    @staticmethod
    def _ps_quote(value: Path | str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _run_extracted_helpers(self, names, body):
        if self.powershell is None:
            self.skipTest("PowerShell is unavailable")
        source_path = self._ps_quote(SCRIPT)
        name_list = "@(" + ",".join(self._ps_quote(name) for name in names) + ")"
        command = (
            "$ErrorActionPreference='Stop';"
            "$tokens=$null;$parseErrors=$null;"
            f"$sourcePath={source_path};"
            "$ast=[System.Management.Automation.Language.Parser]::ParseFile($sourcePath,[ref]$tokens,[ref]$parseErrors);"
            "if($parseErrors.Count -gt 0){throw 'launcher parse failed'};"
            f"$names={name_list};"
            "foreach($name in $names){"
            "$function=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))|Select-Object -First 1;"
            "if($null -eq $function){throw ('missing helper: ' + $name)};"
            ". ([scriptblock]::Create($function.Extent.Text));"
            "}"
            + body
        )
        return subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_extracted_write_helper_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            body = (
                "$script:runIdValue='fixture-run';$Live=$false;$script:process=$null;"
                f"Write-OutcomeReport {self._ps_quote(report)} 'failed' 'first';"
                f"$original=[IO.File]::ReadAllText({self._ps_quote(report)});"
                "$secondFailed=$false;"
                f"try{{Write-OutcomeReport {self._ps_quote(report)} 'passed' 'second'}}catch{{$secondFailed=$true}};"
                "if(-not $secondFailed){throw 'CreateNew did not reject an existing report'};"
                f"if([IO.File]::ReadAllText({self._ps_quote(report)}) -ne $original){{throw 'existing report changed'}};"
                "Write-Output 'HELPER_PASS';"
            )
            result = self._run_extracted_helpers(["Write-OutcomeReport"], body)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("HELPER_PASS", result.stdout)

    def test_extracted_containment_helper_rejects_outside_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            body = (
                f"$fixture={self._ps_quote(fixture)};"
                "if(-not (Test-PathWithin (Join-Path $fixture 'owned\\child') $fixture)){throw 'inside path rejected'};"
                "if(Test-PathWithin (Join-Path $fixture 'outside') (Join-Path $fixture 'owned')){throw 'outside path accepted'};"
                "Write-Output 'HELPER_PASS';"
            )
            result = self._run_extracted_helpers(["Test-PathWithin"], body)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("HELPER_PASS", result.stdout)

    def test_extracted_ancestor_helper_rejects_existing_file_under_junction(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            body = (
                f"$fixture={self._ps_quote(fixture)};"
                "$target=Join-Path $fixture 'target';[IO.Directory]::CreateDirectory($target)|Out-Null;"
                "$junction=Join-Path $fixture 'junction';"
                "try{New-Item -ItemType Junction -Path $junction -Target $target -ErrorAction Stop|Out-Null}"
                "catch{Write-Output 'SKIP_JUNCTION';exit 0};"
                "$file=Join-Path $junction 'existing.txt';[IO.File]::WriteAllText($file,'fixture');"
                "$rejected=$false;"
                "try{Assert-NoReparseAncestors $file 'existing fixture file'}"
                "catch{if($_.Exception.Message -like 'Refusing reparse-point*'){$rejected=$true}else{throw}};"
                "if(-not $rejected){throw 'file ancestor reparse point was not rejected'};"
                "Write-Output 'HELPER_PASS';"
            )
            result = self._run_extracted_helpers(["Assert-NoReparseAncestors"], body)
            if "SKIP_JUNCTION" in result.stdout:
                self.skipTest("junction creation is unavailable")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("HELPER_PASS", result.stdout)

    def test_helper_harness_extracts_function_definition_extents_only(self):
        harness_source = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("FunctionDefinitionAst", harness_source)
        self.assertIn("$function.Extent.Text", harness_source)
        self.assertNotIn("$current.Parent", self.source)

    def test_launcher_has_explicit_live_and_owned_path_guards(self):
        parameter_block = self.source.split("param(", 1)[1].split(")", 1)[0]
        self.assertIn("[switch]$Live", parameter_block)
        for name in ("JawlRoot", "JawlPython", "ConfigDir", "DataDir", "LogDir", "RuntimeRoot"):
            self.assertRegex(parameter_block, rf"\[string\]\${name}(?:\s*,|\s*$)")
        self.assertIn("Refusing to launch native JAWL", self.source)
        self.assertIn(".jawl-owned-runtime-v1", self.source)
        self.assertIn("RuntimeRoot under protected tree", self.source)
        self.assertNotIn("runtime\\jawl-live", parameter_block)

    def test_launcher_never_places_console_token_in_arguments_or_logs(self):
        self.assertNotIn("--token", self.source)
        self.assertNotIn("--jawl-token", self.source)
        self.assertIn("CONSOLE_TOKEN = $token", self.source)
        self.assertIn("EnvironmentVariables.Clear()", self.source)
        self.assertIn("BaseStream.CopyToAsync([IO.Stream]::Null)", self.source)

    def test_launcher_uses_supported_powershell_and_creation_time_semantics(self):
        self.assertIn("New-Item -ItemType Directory -Path", self.source)
        self.assertIn("CreationDate -is [DateTime]", self.source)
        self.assertIn("ManagementDateTimeConverter", self.source)
        self.assertIn("Test-ProcessIdentity $parent.Identity", self.source)
        self.assertIn("profileDeadline", self.source)

    def test_cleanup_is_identity_time_bound_and_profile_coverage_is_present(self):
        self.assertNotIn("function Get-PortOwnerIds", self.source)
        self.assertIn("function Stop-VerifiedProcess", self.source)
        self.assertIn("CreationUtc", self.source)
        self.assertIn("Add-VerifiedDescendants $script:rootIdentity", self.source)
        self.assertIn("target_release_profile.py", self.source)
        self.assertIn("profileInfo.EnvironmentVariables", self.source)


if __name__ == "__main__":
    unittest.main()
