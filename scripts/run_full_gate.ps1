$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
# The pinned JAWL snapshot is an immutable test input.  Some integration tests
# import it through PYTHONPATH; prevent those imports from creating bytecode
# files that are absent from SOURCE_MANIFEST.json.
$env:PYTHONDONTWRITEBYTECODE = '1'
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Python 3.10+ was not found. Create .venv and install requirements-dev.txt.' }
    $pythonExe = $pythonCommand.Source
}

function Invoke-CheckedPython {
    param([string[]]$Arguments)

    $ErrorActionPreference = 'Continue'
    & $pythonExe @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Python gate command failed with exit code ${exitCode}: $pythonExe $($Arguments -join ' ')"
    }
    Write-Host "PASS $pythonExe $($Arguments -join ' ')"
}

function Invoke-CheckedGit {
    param([string[]]$Arguments)

    $ErrorActionPreference = 'Continue'
    & git @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Git gate command failed with exit code ${exitCode}: git $($Arguments -join ' ')"
    }
    Write-Host "PASS git $($Arguments -join ' ')"
}

function Invoke-CheckedNode {
    param([string[]]$Arguments)

    $ErrorActionPreference = 'Continue'
    & node @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Node gate command failed with exit code ${exitCode}: node $($Arguments -join ' ')"
    }
    Write-Host "PASS node $($Arguments -join ' ')"
}

function Invoke-CheckedPowerShellParse {
    param([string]$Path)

    $resolved = (Resolve-Path -LiteralPath (Join-Path $companionRoot $Path)).Path
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($resolved, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) {
        throw "PowerShell parse gate failed for ${Path}: $($errors[0].Message)"
    }
    Write-Host "PASS PowerShell parse $Path"
}

Push-Location $companionRoot
try {
    # Keep imports of the pinned JAWL runtime from falling back to its legacy
    # repo-relative logs. The snapshot is an immutable input to the gate.
    $gateHome = Join-Path $companionRoot 'runtime\instances\_regression-gate'
    # JAWL instance IDs are intentionally user-visible and must start with an
    # alphanumeric character; keep the regression profile disposable without
    # violating the native validator.
    $env:JAWL_INSTANCE_ID = 'regression-gate'
    $env:JAWL_INSTANCE_HOME = $gateHome
    $env:JAWL_DATA_DIR = Join-Path $gateHome 'data'
    $env:JAWL_CONFIG_DIR = Join-Path $gateHome 'config'
    $env:JAWL_LOG_DIR = Join-Path $gateHome 'logs'
    $env:JAWL_CACHE_DIR = Join-Path $gateHome 'cache'
    $env:JAWL_PROMPT_DIR = Join-Path $gateHome 'prompts'
    $env:JAWL_SANDBOX_DIR = Join-Path $gateHome 'sandbox'
    New-Item -ItemType Directory -Force -Path $env:JAWL_LOG_DIR, $env:JAWL_DATA_DIR, $env:JAWL_CONFIG_DIR, $env:JAWL_CACHE_DIR, $env:JAWL_PROMPT_DIR, $env:JAWL_SANDBOX_DIR | Out-Null
    Invoke-CheckedPython @('-m', 'compileall', '-q', 'src', 'tests')
    Invoke-CheckedPython @('-m', 'py_compile', 'scripts/teratts_server.py', 'scripts/qwen3_tts_server.py', 'scripts/release_secret_scan.py', 'scripts/run_audio_pipeline_profile.py', 'scripts/run_browser_interaction_e2e.py', 'scripts/run_connected_daily_acceptance.py', 'scripts/run_goal_reconciliation_live.py', 'scripts/run_provider_failure_native_recovery.py', 'scripts/run_restart_inference_acceptance.py', 'scripts/register_supervised_profile.py', 'scripts/run_supervised_profile_acceptance.py', 'scripts/run_supervised_recovery_acceptance.py', 'scripts/run_unattended_goal_soak.py', 'scripts/run_unattended_provider_recovery.py', 'scripts/configure_profile_native.py', 'scripts/prepare_daily_profile.py', 'scripts/verify_jawl_snapshot.py')
    Invoke-CheckedPython @('scripts/verify_jawl_snapshot.py', '--source', 'runtime/jawl-sources/jawl-20260906-daily-v2')
    Invoke-CheckedPython @('scripts/release_secret_scan.py', '--report', 'runtime/release-secret-scan.json')
    Invoke-CheckedPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_[!e]*.py', '-v')
    Invoke-CheckedPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_e2e.py', '-v')
    Invoke-CheckedPython @('scripts/run_browser_interaction_e2e.py')
    Invoke-CheckedNode @('scripts/check_mic_gate.mjs')
    Invoke-CheckedPowerShellParse 'scripts/run_integrated_profile.ps1'
    Invoke-CheckedPowerShellParse 'scripts/run_long_unattended_acceptance.ps1'
    Invoke-CheckedGit @('diff', '--check')
} finally {
    Pop-Location
}
