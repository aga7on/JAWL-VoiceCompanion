$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'

Push-Location $companionRoot
try {
    python -m compileall -q src tests
    python -m unittest discover -s tests -p 'test_[!e]*.py' -v
    python -m unittest discover -s tests -p 'test_e2e.py' -v
    git diff --check
} finally {
    Pop-Location
}
