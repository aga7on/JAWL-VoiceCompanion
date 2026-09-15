param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')]
    [string]$ProfileName = 'p1-provider-recovery-live',
    [ValidateRange(1025,65535)] [int]$RelayPort = 11437,
    [ValidateRange(1025,65535)] [int]$ControlPort = 2480,
    [ValidateRange(1025,65535)] [int]$PresentationPort = 8879,
    [ValidateRange(1025,65535)] [int]$JawlConsolePort = 8855,
    [string]$Upstream = 'http://127.0.0.1:11434'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = 'C:\Python314\python.exe'
$relayScript = Join-Path $root 'scripts\opencode_header_relay.py'
$integrated = Join-Path $root 'scripts\run_integrated_profile.ps1'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python runtime is missing: $python" }
if (-not (Test-Path -LiteralPath $relayScript -PathType Leaf)) { throw 'Relay script is missing.' }
if (-not (Test-Path -LiteralPath $integrated -PathType Leaf)) { throw 'Integrated profile launcher is missing.' }
if ($RelayPort -eq 11434 -or $ControlPort -in @(2367,8770) -or $JawlConsolePort -eq 8770) {
    throw 'Refusing baseline control/provider ports in disposable recovery launcher.'
}

function Assert-FreePort([int]$Port, [string]$Name) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "$Name port is already listening: $Port"
    }
}

foreach ($port in @(
    @{ Value = $RelayPort; Name = 'relay' },
    @{ Value = $ControlPort; Name = 'control' },
    @{ Value = $PresentationPort; Name = 'presentation' },
    @{ Value = $JawlConsolePort; Name = 'JAWL console' }
)) { Assert-FreePort $port.Value $port.Name }

$env:LLM_API_URL = "http://127.0.0.1:$RelayPort/v1"
$env:LLM_REASONING_EFFORT = 'none'
$env:OPENCODE_RELAY_KEY = 'local'
$relayOut = Join-Path $root "runtime\relay-provider-$ProfileName.out.log"
$relayErr = Join-Path $root "runtime\relay-provider-$ProfileName.err.log"
$relay = Start-Process -FilePath $python -ArgumentList @(
    $relayScript, '--port', [string]$RelayPort, '--upstream', $Upstream,
    '--key-env', 'OPENCODE_RELAY_KEY', '--timeout', '180'
) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $relayOut -RedirectStandardError $relayErr -PassThru

try {
    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Get-NetTCPConnection -LocalPort $RelayPort -State Listen -ErrorAction SilentlyContinue)) {
        if ($relay.HasExited) { throw 'Disposable provider relay exited during startup.' }
        if ((Get-Date) -gt $deadline) { throw "Relay did not become ready on $RelayPort." }
        Start-Sleep -Milliseconds 250
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $integrated `
        -ProfileName $ProfileName -ControlPort $ControlPort -PresentationPort $PresentationPort `
        -JawlConsolePort $JawlConsolePort -NativeAccessLevel 3 -StartupTimeoutSeconds 240 `
        -JawlChatTimeoutSeconds 300 -JawlRequestTimeoutSeconds 300 -AllowBusyStartup `
        -NoBrowser -NoLive2D -SyncProfile
    if ($LASTEXITCODE -ne 0) { throw "Integrated recovery profile exited with $LASTEXITCODE." }
} finally {
    if ($relay -and -not $relay.HasExited) {
        Stop-Process -Id $relay.Id -Force -ErrorAction SilentlyContinue
    }
}
