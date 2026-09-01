$ErrorActionPreference = 'Stop'
$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'

# Fail before Python starts when the requested local port belongs to another
# service. This avoids a confusing HTTP 426 from a WebSocket-only listener.
$requestedPort = 8765
for ($index = 0; $index -lt $args.Count; $index++) {
    if ($args[$index] -eq '--port' -and $index + 1 -lt $args.Count) {
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
        throw "Port $requestedPort is already used by $ownerName (PID $($listener.OwningProcess)). Use --port 8766 or another free loopback port."
    }
}

python -m jawl_voicecompanion @args
