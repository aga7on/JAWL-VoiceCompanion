# VoiceMem/reflection consolidation runner: one pass over the dialogue history.
param(
    [int]$MaxSegments = 3,
    [string]$RelayUrl = 'http://127.0.0.1:8891/v1',
    [string]$Model = 'big-pickle'
)
$ErrorActionPreference = 'Stop'
$repo = 'G:\AI\JAWL-VoiceCompanion'
$python = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'
$script = Join-Path $repo 'scripts\voice_reflection.py'
$log = Join-Path $repo 'runtime\reflection.log'
$env:REFLECTION_RELAY_URL = $RelayUrl
$env:REFLECTION_MODEL = $Model
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -LiteralPath $log -Value "[$stamp] reflection pass" -Encoding UTF8
& $python $script --max-segments $MaxSegments 2>&1 | Add-Content -LiteralPath $log -Encoding UTF8
