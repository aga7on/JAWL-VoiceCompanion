$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
& $pythonExe (Join-Path $PSScriptRoot 'run_restart_soak.py') @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
