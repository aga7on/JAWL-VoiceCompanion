$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'

function Invoke-CheckedPython {
    param([string[]]$Arguments)

    $ErrorActionPreference = 'Continue'
    & python @Arguments 2>$null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Python gate command failed with exit code ${exitCode}: python $($Arguments -join ' ')"
    }
    Write-Host "PASS python $($Arguments -join ' ')"
}

function Invoke-CheckedGit {
    param([string[]]$Arguments)

    $ErrorActionPreference = 'Continue'
    & git @Arguments 2>$null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Git gate command failed with exit code ${exitCode}: git $($Arguments -join ' ')"
    }
    Write-Host "PASS git $($Arguments -join ' ')"
}

Push-Location $companionRoot
try {
    Invoke-CheckedPython @('-m', 'compileall', '-q', 'src', 'tests')
    Invoke-CheckedPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_[!e]*.py', '-v')
    Invoke-CheckedPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_e2e.py', '-v')
    Invoke-CheckedGit @('diff', '--check')
} finally {
    Pop-Location
}
