param(
    [string]$ReleaseDir = 'G:\AI\tts_models\TeraSpace__TeraTTSv2',
    [string]$Voice = 'ru_f1',
    [ValidateSet('distilled', 'teacher')]
    [string]$Model = 'distilled',
    [int]$Port = 9889,
    [int]$Threads = 24
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ReleaseDir -PathType Container)) {
    throw "TeraTTS release directory was not found: $ReleaseDir"
}
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535' }
if ($Threads -lt 1) { throw 'Threads must be positive' }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $ownerName = if ($owner) { $owner.ProcessName } else { 'unknown process' }
    throw "TeraTTS port $Port is already used by $ownerName (PID $($listener.OwningProcess)). Choose another -Port."
}

python (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\teratts_server.py') `
    --release-dir $ReleaseDir --voice $Voice --model $Model --port $Port --threads $Threads
exit $LASTEXITCODE
