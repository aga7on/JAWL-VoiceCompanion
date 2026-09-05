$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
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

Push-Location $companionRoot
try {
    Invoke-CheckedPython @('-m', 'compileall', '-q', 'src', 'tests')
    Invoke-CheckedPython @('-m', 'py_compile', 'scripts/teratts_server.py', 'scripts/qwen3_tts_server.py', 'scripts/run_audio_pipeline_profile.py', 'scripts/run_browser_interaction_e2e.py')
    Invoke-CheckedPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_[!e]*.py', '-v')
    Invoke-CheckedPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_e2e.py', '-v')
    Invoke-CheckedPython @('scripts/run_browser_interaction_e2e.py')
    Invoke-CheckedNode @('scripts/check_mic_gate.mjs')
    Invoke-CheckedGit @('diff', '--check')
} finally {
    Pop-Location
}
