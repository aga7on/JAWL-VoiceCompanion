"""Fixture-only coverage for the shared launcher runtime manifest defaults."""

from __future__ import annotations

import base64
import copy
import importlib
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
scripts_path = str(ROOT / "scripts")
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

from jawl_voicecompanion.runtime_manifest import load_runtime_manifest  # noqa: E402
hold_supervised_brain = importlib.import_module("hold_supervised_brain")


FIXTURE = {
    "schema_version": 1,
    "created": "2026-10-10",
    "purpose": "test fixture",
    "repo_root": "fixture",
    "profile": "daily",
    "profile_script": "scripts/run_integrated_profile.ps1",
    "ports": {
        "control": 2367,
        "presentation": 8766,
        "jawl_console": 8770,
        "opencode_relay": 8891,
        "qwen3_vl": 8983,
        "bonsai_coding": 8986,
        "tera_tts": 9889,
        "brain_port": 8990,
    },
    "models": {
        "llama_server_exe": "fixture/taardis.exe",
        "brain_server_exe": "fixture/prism.exe",
        "bonsai_model": "fixture/hikari.gguf",
        "tera_python": "fixture/tera/python.exe",
        "tera_release": "fixture/tera/release",
    },
    "mic": {"prefer": "fixture"},
    "brain": {
        "provider": "local-hikari",
        "model": "local-bonsai2",
        "llm_url": "http://127.0.0.1:8990/v1",
        "use_relay": False,
        "raised_by": "fixture",
        "context_size": 65536,
        "max_output_tokens": 2048,
        "gpu_layers": 99,
        "device": "CUDA1",
        "threads": 12,
    },
    "launch": {"run_seconds": 0, "tts_provider": "tera"},
    "vision": {"url": "http://127.0.0.1:8986/v1", "model": "bonsai", "auto_start": False},
}


class LauncherManifestTests(unittest.TestCase):
    def test_qwen_visual_option_enables_screen_source_and_ocr_without_legacy_watcher(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        path = str(ROOT / "scripts" / "run_integrated_profile.ps1").replace("'", "''")
        command = f"""
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw 'Invalid launcher syntax' }}
$EnableScreenWatch=$false; $EnableScreenOcr=$true; $VisualDescriber='qwen'
$VisualDescriberUrl='http://127.0.0.1:8994/v1'; $VisualDescriberModel='qwen3.5-0.8b'
$VisualDescriberRoi='0,0,1,1'; $VisualDescriberDisplayIndex=0
$VisualDescriberActiveInterval=1.0; $VisualDescriberStaticInterval=4.0
$VisualDescriberPeriodic=4.0; $VisualDescriberMaxAge=6.0; $companionArgs=''
$qwenArgs = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like '*--visual-describer qwen*'}}, $true))[0]
Invoke-Expression $qwenArgs.Extent.Text
$assembledArgs = $companionArgs
$invalidOcr = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if ($EnableScreenOcr -and -not $EnableScreenWatch*'}}, $true))[0]
$EnableScreenOcr=$true; $EnableScreenWatch=$false; $VisualDescriber='eg2'; $rejected=$false
try {{ Invoke-Expression $invalidOcr.Extent.Text }} catch {{ $rejected=$true }}
[Console]::Out.WriteLine((ConvertTo-Json -Compress @{{args=$assembledArgs; rejected=$rejected}}))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, errors="replace", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertIn("--hostos-live --screen-enabled", payload["args"])
        self.assertIn("--screen-ocr", payload["args"])
        self.assertIn("--visual-describer qwen", payload["args"])
        self.assertTrue(payload["rejected"], "OCR without any screen sensor must fail clearly")

    def test_qwen_refresh_defaults_stay_inside_screen_caption_ttl(self) -> None:
        for relative in (
            "scripts/run_integrated_profile.ps1",
            "scripts/run_local_bonsai_integrated.ps1",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            for name in ("VisualDescriberStaticInterval", "VisualDescriberPeriodic"):
                match = re.search(rf"\[double\]\${name}\s*=\s*([0-9.]+)", source)
                self.assertIsNotNone(match, f"missing default for {name} in {relative}")
                self.assertLess(float(match.group(1)), 5.0, f"{name} must fit the 5 s screen TTL")

        cli = (ROOT / "src/jawl_voicecompanion/__main__.py").read_text(encoding="utf-8")
        composition = (ROOT / "src/jawl_voicecompanion/composition.py").read_text(encoding="utf-8")
        for option in ("static_interval", "periodic"):
            match = re.search(
                rf'getattr\(args, "visual_describer_{option}", ([0-9.]+)\)',
                composition,
            )
            self.assertIsNotNone(match, f"missing composition fallback for {option}")
            self.assertLess(float(match.group(1)), 5.0, f"{option} fallback must fit the 5 s screen TTL")
        for option in ("static-interval", "periodic"):
            match = re.search(
                rf'"--visual-describer-{option}",\s*type=float,\s*default=([0-9.]+)',
                cli,
            )
            self.assertIsNotNone(match, f"missing CLI default for {option}")
            self.assertLess(float(match.group(1)), 5.0, f"{option} must fit the 5 s screen TTL")

    def test_desktop_launch_clears_electron_run_as_node_for_child_only(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        source = str(ROOT / "scripts" / "run_integrated_profile.ps1").replace("'", "''")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            electron = root / "desktop" / "node_modules" / "electron" / "dist" / "electron.exe"
            electron.parent.mkdir(parents=True)
            electron.write_bytes(b"fixture")
            logs = root / "logs"
            logs.mkdir()
            command = f"""
$ErrorActionPreference='Stop'; $errors=$null; $tokens=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{source}',[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw 'Invalid launcher syntax' }}
$block=@($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if ($StartDesktopShell)*'}},$true))[0]
$repo='{str(root).replace("'", "''")}'; $logDir='{str(logs).replace("'", "''")}'; $StartDesktopShell=$true
$env:ELECTRON_RUN_AS_NODE='1'; $script:captured='unset'
function Start-Process {{ param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru,$RedirectStandardOutput,$RedirectStandardError)
    $script:captured=if ($env:ELECTRON_RUN_AS_NODE) {{$env:ELECTRON_RUN_AS_NODE}} else {{'unset'}}
    [pscustomobject]@{{Id=12;HasExited=$false}}
}}
Invoke-Expression $block.Extent.Text
[Console]::Out.WriteLine((ConvertTo-Json -Compress @{{captured=$script:captured;restored=$env:ELECTRON_RUN_AS_NODE;pid=$desktopShell.Id}}))
"""
            encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload, {"captured": "unset", "restored": "1", "pid": 12})

    def test_supervised_acceptance_forwards_only_managed_snapshot_override(self) -> None:
        source = (ROOT / "scripts" / "run_supervised_profile_acceptance.py").read_text(encoding="utf-8")
        self.assertIn('command.extend(("-JawlSourceRoot", str(source_path)))', source)
        self.assertIn('source_path.is_relative_to(snapshots_root)', source)

    def test_manifest_api_deep_merges_optional_local_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config"
            config.mkdir()
            canonical = config / "runtime.manifest.json"
            canonical.write_text(json.dumps(copy.deepcopy(FIXTURE)), encoding="utf-8")
            (config / "runtime.manifest.local.json").write_text(
                json.dumps({"ports": {"control": 2467}, "launch": {"run_seconds": 60}}),
                encoding="utf-8",
            )

            effective = load_runtime_manifest(root)
            effective_by_path = load_runtime_manifest(root, manifest_path=canonical)
            cli = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "resolve_runtime_manifest.py"),
                    "--manifest",
                    str(canonical),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(cli.stderr, "")
        self.assertEqual(len(cli.stdout.splitlines()), 1)
        self.assertEqual(json.loads(cli.stdout), effective)
        self.assertEqual(effective_by_path, effective)
        self.assertEqual(effective["ports"]["control"], 2467)
        self.assertEqual(effective["ports"]["jawl_console"], 8770)
        self.assertEqual(effective["brain"]["context_size"], 65536)
        self.assertEqual(effective["brain"]["max_output_tokens"], 2048)
        self.assertEqual(effective["launch"]["run_seconds"], 60)
        self.assertEqual(effective["vision"]["model"], "bonsai")

    def test_profile_configuration_is_locked_and_selected_before_writes(self) -> None:
        source = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        lock = source.index("$profileLock = [IO.File]::Open")
        prepare = source.index("scripts\\prepare_daily_profile.py")
        native_args = source.index("$nativeProfileArgs = @(")
        configure = source.index("scripts\\configure_profile_native.py")
        self.assertLess(lock, prepare)
        self.assertLess(prepare, configure)
        self.assertLess(native_args, configure)
        self.assertIn("$env:JAWL_PROFILE_NAME = $ProfileName", source[:prepare])
        self.assertIn("'--profile', $ProfileName", source)
        self.assertIn(") @nativeProfileArgs", source)
        self.assertIn('instances\\$ProfileName\\.jawl_events', source)
        self.assertNotIn("instances\\daily\\.jawl_events", source)

    def test_managed_stop_signal_is_profile_local_instance_bound_and_uses_shared_cleanup_deadline(self) -> None:
        source = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        lock = source.index("$profileLock = [IO.File]::Open")
        stale_signal_cleanup = source.index("Remove-Item -LiteralPath $launcherStopRequestPath", lock)
        self.assertGreater(stale_signal_cleanup, lock)
        self.assertIn("JAWL_LAUNCHER_STOP_REQUEST = $launcherStopRequestPath", source)
        self.assertIn("JAWL_LAUNCHER_STOP_STATUS = $launcherStopStatusPath", source)
        self.assertIn("$stopRequest.schema_version -eq 1", source)
        self.assertIn("-ceq $companionRuntimeInstanceId", source)
        self.assertIn("request_id = [string]$stopRequest.request_id", source)
        self.assertIn("status = 'stopping'", source)
        self.assertIn("Move-Item -LiteralPath $statusTempPath -Destination $launcherStopStatusPath -Force", source)
        self.assertIn("Test-Path -LiteralPath $launcherStopRequestPath -PathType Leaf", source)
        self.assertIn("$shutdownDeadline = [DateTime]::UtcNow.AddSeconds(25)", source)
        self.assertIn("$ownedProcesses | Where-Object { -not $_.HasExited }", source)
        self.assertNotIn("$process.WaitForExit(25000)", source)

    def test_process_tree_cleanup_refuses_reused_root_pid(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        source = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        function = source.split("function Stop-OwnedProcessTree($process) {", 1)[1].split(
            "\nfunction Wait-JawlHeartbeatReady", 1
        )[0]
        command = f"""
$ErrorActionPreference='Stop'; $script:stopCalls=0
function Get-Process {{ param($Id, $ErrorAction); [pscustomobject]@{{Id=$Id;StartTime=[datetime]'2026-01-02T03:04:06'}} }}
function Get-CimInstance {{ @() }}
function Stop-Process {{ $script:stopCalls++ }}
function Stop-OwnedProcessTree($process) {{{function}
$owned=[pscustomobject]@{{Id=123;StartTime=[datetime]'2026-01-02T03:04:05'}}
Stop-OwnedProcessTree $owned
[Console]::Out.WriteLine((ConvertTo-Json -Compress @{{stopCalls=$script:stopCalls}}))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), {"stopCalls": 0})

    def test_startup_readiness_waits_for_fresh_react_completion(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        source = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        function = source.split(
            "function Wait-JawlHeartbeatReady", 1
        )[1].split("\n\nAssert-PortAvailable", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            log_path = str(Path(temporary) / "main.log").replace("'", "''")
            command = f"""
$ErrorActionPreference='Stop'; $script:polls=0; $script:logPath='{log_path}'
$script:portFile=Join-Path (Split-Path -Parent $script:logPath) 'terminal.port'
$started=[datetime]::UtcNow.AddSeconds(-1)
$stamp=[datetime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss.fff',[Globalization.CultureInfo]::InvariantCulture)
Set-Content -LiteralPath $script:logPath -Value "$stamp - JAWL - INFO - [System] JAWL started successfully."
function Start-Sleep {{ param([int]$Milliseconds); $script:polls++; if ($script:polls -eq 2) {{
    $next=[datetime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss.fff',[Globalization.CultureInfo]::InvariantCulture)
    Add-Content -LiteralPath $script:logPath -Value "$next - JAWL.Agent - INFO - [ReAct] Empty actions list received. Concluding cycle."
}} }}
function Wait-JawlHeartbeatReady{function}
$proc=[pscustomobject]@{{HasExited=$false}}
Wait-JawlHeartbeatReady $script:logPath $started 5 $proc
[Console]::Out.WriteLine((ConvertTo-Json -Compress @{{polls=$script:polls}}))
"""
            encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True, text=True, errors="replace", timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), {"polls": 2})

    def test_wrapper_forwards_disposable_profile_no_browser_and_temperature(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        path = str(ROOT / "scripts" / "run_local_bonsai_integrated.ps1").replace("'", "''")
        command = f"""
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw 'Invalid launcher syntax' }}
$ProfileName = 'b0-fixture'; $NoBrowser = $true; $StartDesktopShell = $true; $RunSeconds = 1
$VisualDescriber='qwen'; $VisualDescriberUrl=''; $VisualDescriberPort=8994
$VisualDescriberModel='qwen3.5-0.8b'; $VisualDescriberThreads=4
$VisualDescriberServerPath='server.exe'; $VisualDescriberModelPath='model.gguf'; $VisualDescriberMmprojPath='mmproj.gguf'
$VisualDescriberRoi='0,0,1,1'; $VisualDescriberActiveInterval=1.0; $VisualDescriberStaticInterval=5.0
$VisualDescriberPeriodic=10.0; $VisualDescriberMaxAge=6.0
$NoLocalAudio=$false
$repo='G:\\fixture'; $ReportPath='runtime\\qwen-cowatch.json'
$JawlConsolePort=2770; $ControlPort=2467; $PresentationPort=2766; $TtsPort=2889
$TtsProvider='tera'; $VisionUrl='http://127.0.0.1:8986/v1'; $VisionModel='fixture'; $ModelAlias='fixture'
$assignment = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$integratedArgs'}}, $true))[0]
Invoke-Expression $assignment.Extent.Text
$audioModes = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if (-not $NoLocalAudio*'}}, $true))
foreach ($audioMode in $audioModes) {{ Invoke-Expression $audioMode.Extent.Text }}
$noBrowser = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if ($NoBrowser)*'}}, $true))[0]
Invoke-Expression $noBrowser.Extent.Text
$desktopShell = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if ($StartDesktopShell)*'}}, $true))[0]
Invoke-Expression $desktopShell.Extent.Text
$qwen = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if ($VisualDescriber -eq ''qwen'')*'}}, $true))[0]
Invoke-Expression $qwen.Extent.Text
$managedArgs = @($integratedArgs)
$reportAssignment = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$report'}}, $true))[0]
Invoke-Expression $reportAssignment.Extent.Text
$managedReport = $report
$VisualDescriberUrl='http://127.0.0.1:8994/v1'
$NoLocalAudio=$true
Invoke-Expression $assignment.Extent.Text
foreach ($audioMode in $audioModes) {{ Invoke-Expression $audioMode.Extent.Text }}
Invoke-Expression $qwen.Extent.Text
$externalArgs = @($integratedArgs)
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{{managed=$managedArgs;external=$externalArgs;report=$managedReport}} -Compress))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        arguments = payload["managed"]
        self.assertIn("-StartLocalAudio", arguments)
        self.assertIn("-UseVoiceMem", arguments)
        self.assertEqual(arguments[arguments.index("-ProfileName") + 1], "b0-fixture")
        self.assertEqual(arguments[arguments.index("-JawlTemperatureOverride") + 1], "0.3")
        self.assertIn("-NoBrowser", arguments)
        self.assertNotIn("-AllowBusyStartup", arguments)
        self.assertIn("-StartDesktopShell", arguments)
        self.assertIn("-ManageVisualQwenServer", arguments)
        self.assertEqual(arguments[arguments.index("-VisualDescriberUrl") + 1], "http://127.0.0.1:8994/v1")
        self.assertNotIn("-ManageVisualQwenServer", payload["external"])
        self.assertNotIn("-StartLocalAudio", payload["external"])
        self.assertNotIn("-UseVoiceMem", payload["external"])
        self.assertEqual(payload["report"], str(Path("G:/fixture/runtime/qwen-cowatch.json")))
        self.assertEqual(payload["external"][payload["external"].index("-VisualDescriberUrl") + 1], "http://127.0.0.1:8994/v1")
        source = (ROOT / "scripts" / "run_local_bonsai_integrated.ps1").read_text(encoding="utf-8")
        self.assertNotIn("apply_llm_overrides.py", source)

    def test_headless_ambient_audio_keeps_voicemem_without_starting_tts(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        path = str(ROOT / "scripts" / "run_local_bonsai_integrated.ps1").replace("'", "''")
        command = f"""
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw 'Invalid launcher syntax' }}
$NoLocalAudio=$true; $EnableAmbientAudio=$true; $StartAmbientAudio=$true; $integratedArgs=@('core')
$audioModes = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if (-not $NoLocalAudio*'}}, $true))
$startLocal = $audioModes[0]
$voiceMem = $audioModes[1]
Invoke-Expression $startLocal.Extent.Text
Invoke-Expression $voiceMem.Extent.Text
$autostart = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -eq 'if ($StartAmbientAudio) {{ $integratedArgs += ''-StartAmbientAudio'' }}'}}, $true))[0]
if (-not $autostart) {{ throw 'Ambient audio autostart forwarding is missing.' }}
Invoke-Expression $autostart.Extent.Text
[Console]::Out.WriteLine((ConvertTo-Json -Compress @{{args=$integratedArgs}}))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                capture_output=True, text=True, errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout.strip())["args"]
        self.assertIn("-UseVoiceMem", args)
        self.assertNotIn("-StartLocalAudio", args)
        self.assertIn("-StartAmbientAudio", args)
        integrated = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($EnableStreamingAsr -and -not $StartLocalAudio)", integrated)
        self.assertIn("--ambient-audio-autostart", integrated)

    def test_profile_lock_is_exclusive_and_released_on_prepare_failure(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        source = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        # Execute the real lock/write prefix only, with temporary paths. No
        # snapshot preparation, device access, models, or child processes.
        prefix = source.split("# Lock before prepare/configure", 1)[1].split("\n", 1)[1].split("& $browserPy", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = str(Path(temporary)).replace("'", "''")
            command = f"""
$ErrorActionPreference='Stop'; $ProfileName='fixture'
$logDir='{directory}'; $profileLockPath=Join-Path $logDir 'run.lock'
$launcherStopRequestPath=Join-Path $logDir 'data\\interfaces\\launcher-stop.request'
    $launcherStopStatusPath=Join-Path $logDir 'data\\interfaces\\launcher-stop.status'
$blocked=$false; $failed=$false
try {{
{prefix}
    try {{ $other=[IO.File]::Open($profileLockPath, 'OpenOrCreate', 'ReadWrite', 'None'); $other.Dispose() }} catch [IO.IOException] {{ $blocked=$true }}
    throw 'fixture preparation failed'
}} finally {{ if ($profileLock) {{ $profileLock.Dispose() }} }}
}} catch {{ $failed=$_.Exception.Message -eq 'fixture preparation failed' }}
$again=[IO.File]::Open($profileLockPath, 'OpenOrCreate', 'ReadWrite', 'None'); $again.Dispose()
[Console]::Out.WriteLine((@{{blocked=$blocked;failed=$failed;released=$true}} | ConvertTo-Json -Compress))
"""
            encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()), {"blocked": True, "failed": True, "released": True})

    def test_real_wrapper_refuses_busy_port_from_foreign_cwd_without_starting_models(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            # Existing tiny fixture files satisfy presence checks only; if
            # preflight were bypassed, the holder would fail instead of
            # loading real weights. No daily configuration is read/written.
            model = Path(temporary) / "fixture.gguf"
            model.write_bytes(b"not a model")
            result = subprocess.run([
                powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(ROOT / "scripts" / "run_local_bonsai_integrated.ps1"),
                "-ProfileName", "b0-preflight-fixture", "-NoBrowser", "-RunSeconds", "1",
                "-BrainPort", str(port), "-BrainServer", sys.executable, "-Model", str(model),
            ], cwd=temporary, capture_output=True, text=True, errors="replace", timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Brain port is unavailable", result.stderr)
            self.assertEqual(listener.getsockname()[1], port)

    def test_real_wrapper_rejects_managed_qwen_port_collision_before_holder_starts(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        required = (
            ROOT / "runtime/gemma4-e4b-cpu/llama.cpp/llama-server.exe",
            ROOT / "runtime/vlm-cpu-bench/models/qwen3.5-0.8b/Qwen3.5-0.8B-Q4_K_M.gguf",
            ROOT / "runtime/vlm-cpu-bench/models/qwen3.5-0.8b/mmproj-F16.gguf",
        )
        if not all(path.is_file() for path in required):
            self.skipTest("managed Qwen local assets required")
        with socket.socket() as listener, socket.socket() as brain_listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            # The machine may have the daily brain already running on its
            # managed default port. Keep that unrelated endpoint untouched and
            # give preflight a free brain port so this test reaches the Qwen
            # collision it is intended to verify.
            brain_listener.bind(("127.0.0.1", 0))
            brain_port = brain_listener.getsockname()[1]
            brain_listener.close()
            # Keep this smoke test independent of a running daily companion:
            # its standard control and presentation ports may be occupied.
            managed_ports = []
            for _ in range(3):
                with socket.socket() as port_probe:
                    port_probe.bind(("127.0.0.1", 0))
                    managed_ports.append(port_probe.getsockname()[1])
            result = subprocess.run(
                [
                    powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "scripts" / "run_local_bonsai_integrated.ps1"),
                    "-ProfileName", "b0-qwen-port-collision", "-NoBrowser", "-RunSeconds", "1",
                    "-JawlConsolePort", str(managed_ports[0]),
                    "-ControlPort", str(managed_ports[1]),
                    "-PresentationPort", str(managed_ports[2]),
                    "-BrainPort", str(brain_port),
                    "-VisualDescriber", "qwen", "-VisualDescriberPort", str(port),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Visual Qwen port is unavailable", result.stderr)
            self.assertEqual(listener.getsockname()[1], port)

    def test_real_integrated_launcher_rejects_colliding_overrides_before_profile_writes(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([
                powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(ROOT / "scripts" / "run_integrated_profile.ps1"),
                "-ProfileName", "b0-collision-fixture", "-NoBrowser", "-RunSeconds", "1",
                "-ControlPort", "2467", "-JawlConsolePort", "2467",
            ], cwd=temporary, capture_output=True, text=True, errors="replace", timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("service ports must be distinct", result.stderr)

    def test_launcher_initializers_use_manifest_defaults_and_bound_overrides(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is required for launcher AST/dry-config verification")

        manifest_json = json.dumps(FIXTURE, separators=(",", ":"))
        script_paths = [
            ROOT / "scripts" / "run_local_bonsai_integrated.ps1",
            ROOT / "scripts" / "run_integrated_profile.ps1",
        ]
        literal_paths = [str(path).replace("'", "''") for path in script_paths]
        command = f"""
$fixture = '{manifest_json}' | ConvertFrom-Json
        $paths = @('{literal_paths[0]}', '{literal_paths[1]}')
$results = @()
foreach ($path in $paths) {{
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {{ throw ($parseErrors | Out-String) }}
    $functionAst = @($ast.FindAll({{ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Resolve-LauncherRuntimeDefaults'
    }}, $true))
    if ($functionAst.Count -ne 1) {{ throw "Expected one manifest initializer in $path" }}
    Invoke-Expression $functionAst[0].Extent.Text
    $defaults = Resolve-LauncherRuntimeDefaults $fixture @{{}}
    $overrides = if ($path -eq $paths[0]) {{
        @{{ RunSeconds = 60; ControlPort = 2467; BrainPort = 8992; VisionModel = 'fixture-vision' }}
    }} else {{
        @{{ RunSeconds = 60; ControlPort = 2467; TtsPort = 9899; TeraPython = 'override/python.exe'; TeraRelease = 'override/release'; VisionModel = 'fixture-vision' }}
    }}
    $explicit = Resolve-LauncherRuntimeDefaults $fixture $overrides
    $results += ,@{{ defaults = $defaults; explicit = $explicit }}
}}
[Console]::Out.WriteLine(($results | ConvertTo-Json -Depth 8 -Compress))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(len(output), 2)
        for item in output:
            defaults = item["defaults"]
            explicit = item["explicit"]
            self.assertEqual(defaults["JawlConsolePort"], 8770)
            self.assertEqual(defaults["ControlPort"], 2367)
            # ADR-052: no PresentationPort mapping remains in the launchers.
            self.assertNotIn("PresentationPort", defaults)
            self.assertEqual(defaults["TtsPort"], 9889)
            self.assertEqual(defaults["RunSeconds"], 0)
            self.assertEqual(defaults["TtsProvider"], "tera")
            self.assertEqual(defaults["VisionUrl"], "http://127.0.0.1:8986/v1")
            self.assertEqual(defaults["VisionModel"], "bonsai")
            self.assertEqual(explicit["RunSeconds"], 60)
            self.assertEqual(explicit["ControlPort"], 2467)
            self.assertEqual(explicit["VisionModel"], "fixture-vision")
        self.assertEqual(output[1]["defaults"]["TeraPython"], "fixture/tera/python.exe")
        self.assertEqual(output[1]["defaults"]["TeraRelease"], "fixture/tera/release")
        self.assertEqual(output[1]["explicit"]["TeraPython"], "override/python.exe")
        self.assertEqual(output[1]["explicit"]["TeraRelease"], "override/release")

    def test_brain_probe_urls_are_exact_and_reject_port_mismatch(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell is required for launcher AST/dry-config verification")
        script_path = str(ROOT / "scripts" / "run_local_bonsai_integrated.ps1").replace("'", "''")
        command = f"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) {{ throw ($parseErrors | Out-String) }}
$fn = @($ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-BrainProbeUrls' }}, $true))
if ($fn.Count -ne 1) {{ throw 'Expected exactly one brain probe URL helper.' }}
Invoke-Expression $fn[0].Extent.Text
$urls = Get-BrainProbeUrls 'http://127.0.0.1:8990/v1' 8990
$mismatchRejected = $false
try {{ Get-BrainProbeUrls 'http://127.0.0.1:8991/v1' 8990 | Out-Null }} catch {{ $mismatchRejected = $true }}
[Console]::Out.WriteLine((@{{health=$urls.HealthUrl;models=$urls.ModelsUrl;mismatchRejected=$mismatchRejected}} | ConvertTo-Json -Compress))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, errors="replace", check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["health"], "http://127.0.0.1:8990/health")
        self.assertEqual(payload["models"], "http://127.0.0.1:8990/v1/models")
        self.assertTrue(payload["mismatchRejected"])

    def test_screen_watch_stays_opt_in_and_never_spawns_vision_worker(self) -> None:
        source = (ROOT / "scripts" / "run_integrated_profile.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($EnableScreenWatch)", source)
        screen_block = source.split("if ($EnableScreenWatch)", 1)[1].split("# Arguments contain", 1)[0]
        self.assertIn("--vision-url $VisionUrl --vision-model $VisionModel", screen_block)
        self.assertNotIn("Start-Process", screen_block)
        self.assertNotIn("CUDA_VISIBLE_DEVICES", screen_block)
        self.assertNotIn("8983", screen_block)

    def test_holder_defaults_and_shared_readiness_probe(self) -> None:
        with mock.patch.object(hold_supervised_brain, "load_runtime_manifest", return_value=FIXTURE):
            defaults = hold_supervised_brain._manifest_defaults()
        self.assertEqual(defaults["port"], 8990)
        self.assertEqual(defaults["llm_exe"], "fixture/prism.exe")
        self.assertEqual(defaults["model"], "fixture/hikari.gguf")
        self.assertEqual(defaults["alias"], "local-bonsai2")
        self.assertEqual(defaults["ctx_size"], 65536)
        self.assertEqual(defaults["max_tokens"], 2048)
        self.assertEqual(defaults["gpu_layers"], 99)
        self.assertEqual(defaults["device"], "CUDA1")
        self.assertEqual(defaults["threads"], 12)
        self.assertEqual(defaults["gpu_layers"], 99)
        holder_source = (ROOT / "scripts" / "hold_supervised_brain.py").read_text(encoding="utf-8")
        self.assertIn("return model_ready(args.port, args.alias)", holder_source)
        self.assertIn("require_free_ports([args.port])", holder_source)
        self.assertIn('"--reasoning", args.reasoning, "--no-webui"', holder_source)
        self.assertIn('parser.add_argument("--reasoning", choices=("on", "off", "auto"), default="off")', holder_source)
        self.assertEqual(hold_supervised_brain._repo_path("fixture/model.gguf"), ROOT / "fixture/model.gguf")
        absolute_fixture = ROOT / "fixture" / "model.gguf"
        self.assertEqual(hold_supervised_brain._repo_path(str(absolute_fixture)), absolute_fixture)
        self.assertTrue(hold_supervised_brain._is_valid_api_url("http://127.0.0.1:8990/v1", 8990))
        self.assertFalse(hold_supervised_brain._is_valid_api_url("http://user:pass@127.0.0.1:8990/v1", 8990))
        self.assertFalse(hold_supervised_brain._is_valid_api_url("http://127.0.0.1:8991/v1", 8990))
        self.assertNotIn("_served_alias_matches", holder_source)

    def test_holder_enforces_configured_generation_limit_in_llama_server(self) -> None:
        args = mock.Mock(
            llm_exe="llama-server.exe", model="brain.gguf", alias="local-qwen3-omni",
            port=8990, threads=12, ctx_size=12288, max_tokens=512,
            gpu_layers=99, device="CUDA0,CUDA1", reasoning="auto",
            transformers_server_script="", transformers_python="",
        )
        command = hold_supervised_brain._worker_command(args, mmproj="projector.gguf")
        self.assertEqual(command[command.index("--n-predict") + 1], "512")
        self.assertEqual(command[command.index("--ctx-size") + 1], "12288")
        self.assertEqual(command[command.index("--mmproj") + 1], "projector.gguf")


if __name__ == "__main__":
    unittest.main()
