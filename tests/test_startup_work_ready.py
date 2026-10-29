import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows launcher regression")
class StartupWorkReadyTests(unittest.TestCase):
    def test_successful_native_work_unblocks_ui_without_waiting_for_goal_completion(self):
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            # The fixture is synthetic; no runtime log or active profile is changed.
            script = Path(directory) / "probe.ps1"
            source = str(root / "scripts/run_integrated_profile.ps1").replace("'", "''")
            script.write_text("""
$errors=$null; $tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
$fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Wait-JawlHeartbeatReady'},$true)
. ([ScriptBlock]::Create($fn.Extent.Text))
$portFile=Join-Path $PSScriptRoot 'terminal.port'
Set-Content -LiteralPath $portFile -Value '12345'
$log=Join-Path $PSScriptRoot 'synthetic-main.log'
$started=Get-Date
$stamp=$started.ToString('yyyy-MM-dd HH:mm:ss.fff')
@("$stamp - JAWL - INFO - [System] JAWL started successfully", "$stamp - JAWL.Agent - INFO - [Agent Action Result] HostOSReader.read_file (Success): fixture") | Set-Content -LiteralPath $log
Wait-JawlHeartbeatReady $log $started 2 ([pscustomobject]@{HasExited=$false})
'WORK_READY'
""".replace("SOURCE", source), encoding="utf-8")
            result = subprocess.run(["powershell", "-NoProfile", "-File", str(script)], capture_output=True,
                                    timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertIn(b"WORK_READY", result.stdout)
