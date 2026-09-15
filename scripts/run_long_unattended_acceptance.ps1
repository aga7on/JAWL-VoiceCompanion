[CmdletBinding()]
param(
    [ValidateRange(30,28800)]
    [int]$DurationSeconds = 28800,
    [ValidateRange(30,1800)]
    [int]$GoalTimeoutSeconds = 300,
    [ValidateRange(0,3600)]
    [int]$IntervalSeconds = 30,
    [ValidateRange(30,600)]
    [int]$StartupTimeoutSeconds = 180,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')]
    [string]$ProfileName = '',
    [int]$JawlConsolePort = 8770,
    [int]$ControlPort = 2368,
    [int]$PresentationPort = 8767,
    [string]$Model = 'qwen3.8-27b-abliterated:latest',
    [string]$JawlTemperatureOverride = '0.2',
    [string]$Report = ''
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'
$integrated = Join-Path $repo 'scripts\run_integrated_profile.ps1'
$soak = Join-Path $repo 'scripts\run_unattended_goal_soak.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Owned runtime Python is missing: $python" }
if (-not (Test-Path -LiteralPath $integrated -PathType Leaf)) { throw "Integrated launcher is missing: $integrated" }
if (-not (Test-Path -LiteralPath $soak -PathType Leaf)) { throw "Unattended soak harness is missing: $soak" }

if (-not $ProfileName) {
    $ProfileName = 'qwen-ollama-unattended-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
}
if (-not $Report) {
    $Report = Join-Path $repo (Join-Path 'runtime' ($ProfileName + '.json'))
}
$runDir = Join-Path $repo (Join-Path 'runtime\long-soak' $ProfileName)
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$profileStdout = Join-Path $runDir 'integrated-profile.stdout.log'
$profileStderr = Join-Path $runDir 'integrated-profile.stderr.log'
$soakStdout = Join-Path $runDir 'soak.stdout.log'
$soakStderr = Join-Path $runDir 'soak.stderr.log'
$summaryPath = Join-Path $runDir 'orchestrator-summary.json'

function Test-LoopbackPort([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    $async = $null
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($async)
        return $client.Connected
    } catch { return $false }
    finally { $client.Close() }
}

function Assert-FreePort([int]$Port, [string]$Name) {
    if (Test-LoopbackPort $Port) { throw "$Name port is already in use: $Port" }
}

function Get-DescendantProcessIds([int]$RootId) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $ids = New-Object System.Collections.Generic.List[int]
    $ids.Add($RootId)
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $all) {
            $id = [int]$process.ProcessId
            if ($ids.Contains([int]$process.ParentProcessId) -and -not $ids.Contains($id)) {
                $ids.Add($id)
                $changed = $true
            }
        }
    }
    return @($ids)
}

function Stop-OwnedProfileTree([int]$RootId) {
    $ids = @(Get-DescendantProcessIds $RootId)
    # Children first; the root is the exact PowerShell process started below.
    foreach ($id in ($ids | Sort-Object -Descending)) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}

foreach ($port in @(
    @{ Port = $JawlConsolePort; Name = 'JAWL console' },
    @{ Port = $ControlPort; Name = 'Companion control' },
    @{ Port = $PresentationPort; Name = 'Companion presentation' }
)) { Assert-FreePort $port.Port $port.Name }
if (@($JawlConsolePort, $ControlPort, $PresentationPort) -contains 11434 -or
    @($JawlConsolePort, $ControlPort, $PresentationPort) -contains 8765) {
    throw 'Refusing to use Ollama 11434 or FoxMCP 8765 as a disposable profile port.'
}

$startedAt = [DateTime]::UtcNow
$profileProcess = $null
$soakProcess = $null
$exitCode = 1
$failure = $null
$profilePortsClosed = $false
try {
    # Local provider only. No remote credential is read or written by this runner.
    $env:LLM_API_URL = 'http://127.0.0.1:11434/v1'
    $env:LLM_API_KEY_1 = 'local-loopback'
    $env:LLM_REASONING_EFFORT = 'none'

    $profileArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $integrated,
        '-ProfileName', $ProfileName,
        '-JawlConsolePort', [string]$JawlConsolePort,
        '-ControlPort', [string]$ControlPort,
        '-PresentationPort', [string]$PresentationPort,
        '-NoBrowser', '-NoLive2D',
        '-NativeAccessLevel', '3',
        '-JawlModelOverride', $Model,
        '-JawlTemperatureOverride', $JawlTemperatureOverride,
        '-JawlChatTimeoutSeconds', [string]$GoalTimeoutSeconds,
        '-JawlRequestTimeoutSeconds', [string]$GoalTimeoutSeconds
    )
    $profileProcess = Start-Process -FilePath (Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe') `
        -ArgumentList $profileArgs -WorkingDirectory $repo -WindowStyle Hidden `
        -RedirectStandardOutput $profileStdout -RedirectStandardError $profileStderr -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    $health = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($profileProcess.HasExited) { throw "Integrated profile exited during startup; inspect $profileStderr" }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$ControlPort/api/health" -TimeoutSec 3
            if ($health.status -in @('ok', 'degraded')) { break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $health -or $health.status -notin @('ok', 'degraded')) {
        throw "Companion health did not become available within $StartupTimeoutSeconds seconds."
    }

    # Scope the soak protocol prompt to this disposable profile only; daily
    # profiles never see it. JAWL re-reads the custom prompt dir every cycle,
    # so copying right after the health gate covers every goal.
    $soakPromptSource = Join-Path $repo 'config\jawl\prompts\soak\ZZ_SOAK_GOALS.md'
    if (Test-Path -LiteralPath $soakPromptSource -PathType Leaf) {
        $soakPromptTarget = Join-Path $repo ("runtime\instances\" + $ProfileName + "\prompts\custom\ZZ_SOAK_GOALS.md")
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $soakPromptTarget) | Out-Null
        Copy-Item -LiteralPath $soakPromptSource -Destination $soakPromptTarget -Force
    }

    $soakArgs = @(
        $soak, '--live', '--url', "http://127.0.0.1:$ControlPort",
        '--profile', $ProfileName,
        '--duration-seconds', [string]$DurationSeconds,
        '--cycles', '0',
        '--goal-timeout', [string]$GoalTimeoutSeconds,
        '--poll-seconds', '2',
        '--interval-seconds', [string]$IntervalSeconds,
        '--http-timeout', '30',
        '--report', $Report
    )
    $soakProcess = Start-Process -FilePath $python -ArgumentList $soakArgs `
        -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $soakStdout `
        -RedirectStandardError $soakStderr -PassThru -Wait
    $exitCode = $soakProcess.ExitCode
    if ($exitCode -ne 0) { throw "Unattended soak failed with exit code $exitCode; inspect $Report and $soakStderr" }
}
catch {
    $failure = $_.Exception.Message
    if ($exitCode -eq 0) { $exitCode = 1 }
}
finally {
    if ($profileProcess -and -not $profileProcess.HasExited) {
        Stop-OwnedProfileTree $profileProcess.Id
    }
    Start-Sleep -Seconds 2
    $openProfilePorts = @($JawlConsolePort, $ControlPort, $PresentationPort) |
        Where-Object { Test-LoopbackPort $_ }
    $profilePortsClosed = ($openProfilePorts.Count -eq 0)
    if (-not $profilePortsClosed -and -not $failure) {
        $failure = 'owned profile ports remained open after cleanup'
        $exitCode = 1
    }
    $summary = [ordered]@{
        schema_version = 1
        test = 'orchestrated_long_unattended_acceptance'
        profile = $ProfileName
        model = $Model
        temperature_override = $JawlTemperatureOverride
        provider = 'http://127.0.0.1:11434/v1'
        duration_requested_seconds = $DurationSeconds
        profile_ports_closed = $profilePortsClosed
        report = (Resolve-Path -LiteralPath $Report -ErrorAction SilentlyContinue).Path
        exit_code = $exitCode
        failure = $failure
        started_at = $startedAt.ToString('o')
        finished_at = [DateTime]::UtcNow.ToString('o')
        profile_stdout = $profileStdout
        profile_stderr = $profileStderr
        soak_stdout = $soakStdout
        soak_stderr = $soakStderr
    }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
}

Write-Output ($summary | ConvertTo-Json -Compress)
exit $exitCode
