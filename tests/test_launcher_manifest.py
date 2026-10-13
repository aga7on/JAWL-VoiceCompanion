"""Fixture-only coverage for the shared launcher runtime manifest defaults."""

from __future__ import annotations

import base64
import copy
import importlib
import json
from pathlib import Path
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
        configure = source.index("scripts\\configure_profile_native.py")
        self.assertLess(lock, prepare)
        self.assertLess(prepare, configure)
        self.assertIn("$env:JAWL_PROFILE_NAME = $ProfileName", source[:prepare])
        self.assertIn("@('--profile', $ProfileName", source)
        self.assertIn('instances\\$ProfileName\\.jawl_events', source)
        self.assertNotIn("instances\\daily\\.jawl_events", source)

    def test_wrapper_forwards_disposable_profile_no_browser_and_temperature(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell required")
        path = str(ROOT / "scripts" / "run_local_bonsai_integrated.ps1").replace("'", "''")
        command = f"""
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw 'Invalid launcher syntax' }}
$ProfileName = 'b0-fixture'; $NoBrowser = $true; $RunSeconds = 1
$JawlConsolePort=2770; $ControlPort=2467; $PresentationPort=2766; $TtsPort=2889
$TtsProvider='tera'; $VisionUrl='http://127.0.0.1:8986/v1'; $VisionModel='fixture'; $ModelAlias='fixture'
$assignment = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$integratedArgs'}}, $true))[0]
Invoke-Expression $assignment.Extent.Text
$noBrowser = @($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -like 'if ($NoBrowser)*'}}, $true))[0]
Invoke-Expression $noBrowser.Extent.Text
[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($integratedArgs) -Compress))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(result.stdout.strip())
        self.assertEqual(arguments[arguments.index("-ProfileName") + 1], "b0-fixture")
        self.assertEqual(arguments[arguments.index("-JawlTemperatureOverride") + 1], "0.3")
        self.assertIn("-NoBrowser", arguments)
        source = (ROOT / "scripts" / "run_local_bonsai_integrated.ps1").read_text(encoding="utf-8")
        self.assertNotIn("apply_llm_overrides.py", source)

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
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, timeout=30)
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
            ], cwd=temporary, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Brain port is unavailable", result.stderr)
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
            ], cwd=temporary, capture_output=True, text=True, timeout=30)
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
            self.assertEqual(defaults["PresentationPort"], 8766)
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
            capture_output=True, text=True, check=False, timeout=30,
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
        self.assertIn('"--reasoning", "off", "--no-webui"', holder_source)
        self.assertEqual(hold_supervised_brain._repo_path("fixture/model.gguf"), ROOT / "fixture/model.gguf")
        absolute_fixture = ROOT / "fixture" / "model.gguf"
        self.assertEqual(hold_supervised_brain._repo_path(str(absolute_fixture)), absolute_fixture)
        self.assertTrue(hold_supervised_brain._is_valid_api_url("http://127.0.0.1:8990/v1", 8990))
        self.assertFalse(hold_supervised_brain._is_valid_api_url("http://user:pass@127.0.0.1:8990/v1", 8990))
        self.assertFalse(hold_supervised_brain._is_valid_api_url("http://127.0.0.1:8991/v1", 8990))
        self.assertNotIn("_served_alias_matches", holder_source)


if __name__ == "__main__":
    unittest.main()
