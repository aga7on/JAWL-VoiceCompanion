$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
& $pythonExe -m unittest discover -s (Join-Path $companionRoot 'tests') -p 'test_e2e.py' -v
