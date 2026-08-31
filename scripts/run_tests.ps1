$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
python -m unittest discover -s (Join-Path $companionRoot 'tests') -p 'test_*.py' -v
