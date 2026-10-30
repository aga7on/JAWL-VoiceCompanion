$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }

# Fail before Python starts when the requested local port belongs to another
# service. This avoids a confusing HTTP 426 from a WebSocket-only listener.
$requestedPort = 2367
$requestedHost = '127.0.0.1'
$lanMode = $false
for ($index = 0; $index -lt $args.Count; $index++) {
    if ($args[$index] -eq '--lan') {
        $lanMode = $true
    } elseif ($args[$index] -eq '--host' -and $index + 1 -lt $args.Count) {
        $requestedHost = [string]$args[$index + 1]
    } elseif ($args[$index] -like '--host=*') {
        $requestedHost = [string]$args[$index].Substring(7)
    } elseif ($args[$index] -eq '--port' -and $index + 1 -lt $args.Count) {
        [int]::TryParse($args[$index + 1], [ref]$requestedPort) | Out-Null
    } elseif ($args[$index] -like '--port=*') {
        [int]::TryParse($args[$index].Substring(7), [ref]$requestedPort) | Out-Null
    }
}
if ($requestedPort -ge 1 -and $requestedPort -le 65535) {
    $listener = Get-NetTCPConnection -LocalPort $requestedPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $ownerName = if ($owner) { $owner.ProcessName } else { 'unknown process' }
        throw "Port $requestedPort is already used by $ownerName (PID $($listener.OwningProcess)). Use another port."
    }
}

if ($lanMode -and $requestedHost -eq '127.0.0.1') {
    Write-Verbose 'LAN mode is enabled but the control host is still loopback; use --host with a private LAN IP to allow tablet access.'
}

& $pythonExe -m jawl_voicecompanion @args
