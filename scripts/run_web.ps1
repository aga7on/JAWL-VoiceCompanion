$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
python -m jawl_voicecompanion @args
