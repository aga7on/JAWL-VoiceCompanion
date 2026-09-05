$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Python 3.10+ was not found.' }
    $pythonExe = $pythonCommand.Source
}
Push-Location $companionRoot
try {
    & $pythonExe scripts/run_native_gateway_profile.py @args
    if ($LASTEXITCODE -ne 0) { throw "Native Gateway profile failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
