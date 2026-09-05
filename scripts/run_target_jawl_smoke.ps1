[CmdletBinding()]
param(
    [switch]$Live,
    [string]$CompanionUrl = 'http://127.0.0.1:2367',
    [string]$PresentationUrl = 'http://127.0.0.1:8766',
    [string]$JawlUrl = 'http://127.0.0.1:8773',
    [string]$JawlRoot,
    [string]$JawlPython,
    [string]$ConfigDir,
    [string]$DataDir,
    [string]$LogDir,
    [string]$PromptDir,
    [string]$SandboxDir,
    [string]$RuntimeRoot,
    [string]$ReportPath,
    [string]$RunId,
    [int]$WaitSeconds = 90
)

$ErrorActionPreference = 'Stop'

function Get-LoopbackUri([string]$Value, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is required"
    }
    try {
        $uri = [Uri]$Value
    } catch {
        throw "$Name must be a valid URL"
    }
    if ($uri.Scheme -ne 'http' -or -not $uri.IsLoopback) {
        throw "Refusing non-loopback $Name; use an http://127.0.0.1, localhost, or [::1] URL"
    }
    return $uri
}

function Get-RequiredPath([string]$Value, [string]$Name, [switch]$File) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name must be supplied explicitly; no unsafe default is available"
    }
    $pathType = if ($File) { 'Leaf' } else { 'Container' }
    if (-not (Test-Path -LiteralPath $Value -PathType $pathType)) {
        throw "Missing owned ${Name}: $Value"
    }
    $item = Get-Item -LiteralPath $Value -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse-point ${Name}: $Value"
    }
    return $item.FullName.TrimEnd('\')
}

function Test-PathWithin([string]$Child, [string]$Parent) {
    $childValue = $Child.TrimEnd('\')
    $parentValue = $Parent.TrimEnd('\')
    return [String]::Equals($childValue, $parentValue, [StringComparison]::OrdinalIgnoreCase) -or
        $childValue.StartsWith($parentValue + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparseAncestors([string]$Path, [string]$Name) {
    $currentPath = [IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($currentPath)) {
        if (Test-Path -LiteralPath $currentPath) {
            $current = Get-Item -LiteralPath $currentPath -Force
            if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing reparse-point ancestor of ${Name}: $($current.FullName)"
            }
            $nextPath = Split-Path -Parent $currentPath
        } else {
            $nextPath = Split-Path -Parent $currentPath
        }
        if ([string]::IsNullOrWhiteSpace($nextPath) -or $nextPath -eq $currentPath) {
            break
        }
        $currentPath = $nextPath
    }
}

function Get-Port([Uri]$Uri) {
    if ($Uri.Port -lt 1 -or $Uri.Port -gt 65535) {
        throw "Invalid port in URL: $($Uri.AbsoluteUri)"
    }
    return $Uri.Port
}

function Quote-ProcessArgument([string]$Value) {
    if ($Value -match '"') {
        throw 'Process argument contains an unsupported quote character'
    }
    return '"' + $Value + '"'
}

function Test-PortFree([int]$Port) {
    return -not @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $Port })
}

function Get-ProcessIdentity([int]$ProcessId) {
    if ($ProcessId -le 0) {
        return $null
    }
    $item = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $item -or [string]::IsNullOrWhiteSpace($item.ExecutablePath) -or
        [string]::IsNullOrWhiteSpace($item.CreationDate)) {
        return $null
    }
    try {
        if ($item.CreationDate -is [DateTime]) {
            $createdUtc = ([DateTime]$item.CreationDate).ToUniversalTime()
        } elseif ($item.CreationDate -is [DateTimeOffset]) {
            $createdUtc = ([DateTimeOffset]$item.CreationDate).UtcDateTime
        } else {
            $createdUtc = [Management.ManagementDateTimeConverter]::ToDateTime([string]$item.CreationDate).ToUniversalTime()
        }
        $executablePath = (Get-Item -LiteralPath $item.ExecutablePath -Force -ErrorAction Stop).FullName
    } catch {
        return $null
    }
    return [pscustomobject]@{
        ProcessId = [int]$item.ProcessId
        ParentProcessId = [int]$item.ParentProcessId
        ExecutablePath = $executablePath
        CreationUtc = $createdUtc
        Depth = 0
    }
}

function Test-ProcessIdentity($Expected) {
    $actual = Get-ProcessIdentity ([int]$Expected.ProcessId)
    if ($null -eq $actual) {
        return $false
    }
    return $actual.ProcessId -eq $Expected.ProcessId -and
        $actual.CreationUtc.Ticks -eq $Expected.CreationUtc.Ticks -and
        [String]::Equals($actual.ExecutablePath, $Expected.ExecutablePath, [StringComparison]::OrdinalIgnoreCase)
}

function Get-DescendantProcessIdentities($RootIdentity) {
    $snapshot = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $queue = [System.Collections.Generic.Queue[object]]::new()
    $queue.Enqueue([pscustomobject]@{ Identity = $RootIdentity; Depth = 0 })
    $seen = [System.Collections.Generic.HashSet[int]]::new()
    [void]$seen.Add([int]$RootIdentity.ProcessId)
    $result = [System.Collections.Generic.List[object]]::new()
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        if (-not (Test-ProcessIdentity $parent.Identity)) {
            continue
        }
        foreach ($item in ($snapshot | Where-Object { [int]$_.ParentProcessId -eq $parent.Identity.ProcessId })) {
            $childId = [int]$item.ProcessId
            if (-not $seen.Add($childId)) {
                continue
            }
            $identity = Get-ProcessIdentity $childId
            if ($null -ne $identity) {
                $identity.Depth = $parent.Depth + 1
                $result.Add($identity)
                $queue.Enqueue([pscustomobject]@{ Identity = $identity; Depth = $identity.Depth })
            }
        }
    }
    return $result
}

function Stop-VerifiedProcess($Identity) {
    if ($null -eq $Identity -or -not (Test-ProcessIdentity $Identity)) {
        return
    }
    Stop-Process -Id ([int]$Identity.ProcessId) -Force -ErrorAction SilentlyContinue
}

function Add-VerifiedDescendants($RootIdentity) {
    if ($null -eq $RootIdentity -or -not (Test-ProcessIdentity $RootIdentity)) {
        return
    }
    foreach ($identity in @(Get-DescendantProcessIdentities $RootIdentity)) {
        $duplicate = @($script:ownedIdentities | Where-Object {
            $_.ProcessId -eq $identity.ProcessId -and
            $_.CreationUtc.Ticks -eq $identity.CreationUtc.Ticks
        }).Count -gt 0
        if (-not $duplicate) {
            $script:ownedIdentities.Add($identity)
        }
    }
}

function Write-OutcomeReport([string]$Path, [string]$Status, [string]$Failure) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $report = [ordered]@{
        schema_version = 1
        profile = 'target-jawl-smoke'
        run_id = $script:runIdValue
        status = $Status
        failure = $Failure
        live_opt_in = [bool]$Live
        native_process_started = ($null -ne $script:process)
        generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    }
    $json = $report | ConvertTo-Json -Depth 3
    $stream = $null
    $writer = $null
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
        $writer.Write($json)
        $writer.Flush()
    } finally {
        if ($null -ne $writer) {
            $writer.Dispose()
        } elseif ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

$script:process = $null
$script:profileProcess = $null
$script:stdoutDrain = $null
$script:stderrDrain = $null
$script:profileStdoutDrain = $null
$script:profileStderrDrain = $null
$script:rootIdentity = $null
$script:profileIdentity = $null
$script:ownedIdentities = [System.Collections.Generic.List[object]]::new()
$script:runIdValue = if ([string]::IsNullOrWhiteSpace($RunId)) { [Guid]::NewGuid().ToString('N') } else { $RunId }
$resolvedReportPath = $null
$reportPathValidated = $false
$failureMessage = $null
$outcomeStatus = 'failed'

try {
    if (-not $Live) {
        throw 'Refusing to launch native JAWL. Live execution requires explicit -Live plus an owner-approved isolated runtime; this invocation started no process.'
    }
    if ($script:runIdValue -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$') {
        throw 'RunId must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
    }
    if ($WaitSeconds -lt 1 -or $WaitSeconds -gt 600) {
        throw 'WaitSeconds must be between 1 and 600'
    }

    $companionUri = Get-LoopbackUri $CompanionUrl 'CompanionUrl'
    $presentationUri = Get-LoopbackUri $PresentationUrl 'PresentationUrl'
    $jawlUri = Get-LoopbackUri $JawlUrl 'JawlUrl'
    $jawlPort = Get-Port $jawlUri

    $resolvedRuntimeRoot = Get-RequiredPath $RuntimeRoot 'RuntimeRoot'
    Assert-NoReparseAncestors $resolvedRuntimeRoot 'RuntimeRoot'
    foreach ($protectedRoot in @('G:\AI\JAWL-Coding', 'G:\AI\VoiceMem', 'G:\RE')) {
        if (Test-PathWithin $resolvedRuntimeRoot $protectedRoot.TrimEnd('\')) {
            throw "Refusing RuntimeRoot under protected tree: $protectedRoot"
        }
    }
    $markerPath = Join-Path $resolvedRuntimeRoot '.jawl-owned-runtime-v1'
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "Refusing live native launch: create the owner-approved marker $markerPath only after the runtime/config/data layout and native loader have been reviewed"
    }
    Assert-NoReparseAncestors $markerPath 'owned-runtime marker'

    $resolvedJawlRoot = Get-RequiredPath $JawlRoot 'JawlRoot'
    $resolvedJawlPython = Get-RequiredPath $JawlPython 'JawlPython' -File
    Assert-NoReparseAncestors $resolvedJawlRoot 'JawlRoot'
    Assert-NoReparseAncestors $resolvedJawlPython 'JawlPython'
    $protectedJawlRoot = 'G:\AI\JAWL-Coding'.TrimEnd('\')
    if (Test-PathWithin $resolvedJawlRoot $protectedJawlRoot) {
        throw "Refusing protected upstream JawlRoot: $resolvedJawlRoot"
    }
    if (-not (Test-PathWithin $resolvedJawlPython $resolvedJawlRoot)) {
        throw 'JawlPython must be inside the explicitly owned JawlRoot'
    }
    if ((Test-PathWithin $resolvedRuntimeRoot $resolvedJawlRoot) -or
        (Test-PathWithin $resolvedJawlRoot $resolvedRuntimeRoot)) {
        throw 'JawlRoot and RuntimeRoot must be separate trees; the native source tree must not receive runtime state'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedJawlRoot 'src\web') -PathType Container)) {
        throw "JawlRoot does not contain the expected native src\web package: $resolvedJawlRoot"
    }
    $sharedEnv = Join-Path $resolvedJawlRoot '.env'
    if (Test-Path -LiteralPath $sharedEnv) {
        throw "Refusing live native launch: native loader reads the shared $sharedEnv before instance settings; remove it or use an owner-approved runtime with a reviewed loader"
    }

    $resolvedDirs = @{}
    foreach ($entry in @(
        @{ Name = 'ConfigDir'; Value = $ConfigDir },
        @{ Name = 'DataDir'; Value = $DataDir },
        @{ Name = 'LogDir'; Value = $LogDir },
        @{ Name = 'PromptDir'; Value = $PromptDir },
        @{ Name = 'SandboxDir'; Value = $SandboxDir }
    )) {
        $resolvedDirs[$entry.Name] = Get-RequiredPath $entry.Value $entry.Name
        Assert-NoReparseAncestors $resolvedDirs[$entry.Name] $entry.Name
        if (-not (Test-PathWithin $resolvedDirs[$entry.Name] $resolvedRuntimeRoot)) {
            throw "$($entry.Name) must be inside the explicitly owned RuntimeRoot"
        }
    }

    $instanceHome = Join-Path $resolvedRuntimeRoot 'instance'
    $instancesRoot = Join-Path $resolvedRuntimeRoot 'instances'
    $tempRoot = Join-Path $resolvedRuntimeRoot 'temp'
    $reportRoot = Join-Path $resolvedRuntimeRoot 'reports'
    $homeRoot = Join-Path $resolvedRuntimeRoot 'home'
    $profileRoot = Join-Path $resolvedRuntimeRoot 'profile'
    $appDataRoot = Join-Path $resolvedRuntimeRoot 'appdata'
    $localAppDataRoot = Join-Path $resolvedRuntimeRoot 'localappdata'
    foreach ($directory in @($instanceHome, $instancesRoot, $tempRoot, $reportRoot,
            $homeRoot, $profileRoot, $appDataRoot, $localAppDataRoot)) {
        Assert-NoReparseAncestors $directory 'derived runtime directory'
    }
    foreach ($directory in @($instanceHome, $instancesRoot, $tempRoot, $reportRoot,
            $homeRoot, $profileRoot, $appDataRoot, $localAppDataRoot)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $instanceEnv = Join-Path $instanceHome 'instance.env'
    Assert-NoReparseAncestors $instanceEnv 'instance dotenv'
    if (Test-Path -LiteralPath $instanceEnv) {
        throw "Refusing live native launch: unexpected instance dotenv exists at $instanceEnv; its contents are not inspected or trusted"
    }
    $candidateReportPath = if ([string]::IsNullOrWhiteSpace($ReportPath)) {
        Join-Path $reportRoot "target-jawl-smoke-$($script:runIdValue).json"
    } else {
        $candidate = Get-RequiredPath (Split-Path -Parent $ReportPath) 'ReportPath parent'
        $leaf = Split-Path -Leaf $ReportPath
        Join-Path $candidate $leaf
    }
    if (-not (Test-PathWithin $candidateReportPath $resolvedRuntimeRoot)) {
        throw 'ReportPath must be inside the explicitly owned RuntimeRoot'
    }
    Assert-NoReparseAncestors $candidateReportPath 'ReportPath'
    if (Test-Path -LiteralPath $candidateReportPath) {
        throw "Refusing to overwrite existing report: $candidateReportPath"
    }
    $resolvedReportPath = $candidateReportPath
    $reportPathValidated = $true
    if (-not (Test-PortFree $jawlPort)) {
        throw "Refusing to run target smoke: JAWL port $jawlPort is already in use; no process was stopped"
    }

    $token = [Guid]::NewGuid().ToString('N')
    $systemRoot = [Environment]::GetEnvironmentVariable('SystemRoot')
    if ([string]::IsNullOrWhiteSpace($systemRoot)) {
        throw 'SystemRoot is unavailable; refusing to construct a child environment'
    }
    $pythonDirectory = Split-Path -Parent $resolvedJawlPython
    $safeEnvironment = @{
        SystemRoot = $systemRoot
        SystemDrive = [Environment]::GetEnvironmentVariable('SystemDrive')
        PATH = "$pythonDirectory;$systemRoot\System32"
        TEMP = $tempRoot
        TMP = $tempRoot
        HOME = $homeRoot
        USERPROFILE = $profileRoot
        APPDATA = $appDataRoot
        LOCALAPPDATA = $localAppDataRoot
        PYTHONNOUSERSITE = '1'
        PYTHONUNBUFFERED = '1'
        JAWL_INSTANCE_ID = "native-target-smoke-$($script:runIdValue)"
        JAWL_INSTANCE_HOME = $instanceHome
        JAWL_INSTANCES_ROOT = $instancesRoot
        JAWL_DATA_DIR = $resolvedDirs.DataDir
        JAWL_CONFIG_DIR = $resolvedDirs.ConfigDir
        JAWL_LOG_DIR = $resolvedDirs.LogDir
        JAWL_PROMPT_DIR = $resolvedDirs.PromptDir
        JAWL_SANDBOX_DIR = $resolvedDirs.SandboxDir
        JAWL_ENV_FILE = $instanceEnv
        LLM_API_URL = 'http://127.0.0.1:1/v1'
        CONSOLE_TOKEN = $token
        NO_PROXY = '127.0.0.1,localhost,::1'
    }
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $resolvedJawlPython
    $startInfo.WorkingDirectory = $resolvedJawlRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Arguments = "-m src.web --host 127.0.0.1 --port $jawlPort --no-browser"
    $startInfo.EnvironmentVariables.Clear()
    foreach ($name in $safeEnvironment.Keys) {
        if ($null -ne $safeEnvironment[$name]) {
            $startInfo.EnvironmentVariables[$name] = [string]$safeEnvironment[$name]
        }
    }

    $script:process = [Diagnostics.Process]::Start($startInfo)
    $script:stdoutDrain = $script:process.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null)
    $script:stderrDrain = $script:process.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)

    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $script:rootIdentity = Get-ProcessIdentity ([int]$script:process.Id)
        if ($null -ne $script:rootIdentity -and
            [String]::Equals($script:rootIdentity.ExecutablePath, $resolvedJawlPython, [StringComparison]::OrdinalIgnoreCase)) {
            $script:ownedIdentities.Add($script:rootIdentity)
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($null -eq $script:rootIdentity -or -not (Test-ProcessIdentity $script:rootIdentity)) {
        throw 'Native JAWL process identity/creation time could not be verified; refusing unverified cleanup'
    }
    Add-VerifiedDescendants $script:rootIdentity

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri ($jawlUri.AbsoluteUri.TrimEnd('/') + '/api/agent/status') `
                -Headers @{ 'X-Console-Token' = $token } -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            # Native startup may need time to initialize its owned state.
        }
        if (-not (Test-ProcessIdentity $script:rootIdentity)) {
            throw "JAWL target process exited early with code $($script:process.ExitCode)"
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        throw "JAWL target process did not become ready within $WaitSeconds seconds"
    }

    $startResponse = Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri ($jawlUri.AbsoluteUri.TrimEnd('/') + '/api/agent/start') `
        -Headers @{ 'X-Console-Token' = $token } `
        -ContentType 'application/json' -Body '{}' -TimeoutSec 10
    if ($startResponse.StatusCode -ne 200) {
        throw "JAWL agent start returned HTTP $($startResponse.StatusCode)"
    }
    $running = $false
    $runningDeadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $runningDeadline) {
        try {
            $status = Invoke-RestMethod -Method Get -Uri ($jawlUri.AbsoluteUri.TrimEnd('/') + '/api/agent/status') `
                -Headers @{ 'X-Console-Token' = $token } -TimeoutSec 3
            if ($status.running -eq $true) {
                $running = $true
                break
            }
        } catch {
            # Native startup may briefly replace the status response.
        }
        if (-not (Test-ProcessIdentity $script:rootIdentity)) {
            throw 'JAWL target process exited while starting the agent'
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $running) {
        throw "JAWL agent did not become running within $WaitSeconds seconds"
    }

    $nativePolicy = $false
    $policyDeadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $policyDeadline) {
        try {
            $policy = Invoke-RestMethod -Method Get -Uri ($jawlUri.AbsoluteUri.TrimEnd('/') + '/api/hostos/policy') `
                -Headers @{ 'X-Console-Token' = $token } -TimeoutSec 3
            if ($policy.ok -eq $true -and $policy.native -eq $true -and $null -ne $policy.policy) {
                $nativePolicy = $true
                break
            }
        } catch {
            # Native HostOS can initialize after the web process and agent task.
        }
        if (-not (Test-ProcessIdentity $script:rootIdentity)) {
            throw 'JAWL target process exited while initializing native policy'
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $nativePolicy) {
        throw "JAWL native policy did not become ready within $WaitSeconds seconds"
    }

    Add-VerifiedDescendants $script:rootIdentity

    $profileScript = Join-Path $PSScriptRoot 'run_target_release_profile.py'
    if (-not (Test-Path -LiteralPath $profileScript -PathType Leaf)) {
        throw "Missing target release profile: $profileScript"
    }
    Assert-NoReparseAncestors $profileScript 'target release profile'
    $profileReportPath = Join-Path $reportRoot "target-release-profile-$($script:runIdValue).json"
    Assert-NoReparseAncestors $profileReportPath 'target release profile report'
    if (Test-Path -LiteralPath $profileReportPath) {
        throw "Refusing to overwrite existing profile report: $profileReportPath"
    }
    $profileInfo = [Diagnostics.ProcessStartInfo]::new()
    $profileInfo.FileName = $resolvedJawlPython
    $profileInfo.WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $profileInfo.UseShellExecute = $false
    $profileInfo.CreateNoWindow = $true
    $profileInfo.RedirectStandardOutput = $true
    $profileInfo.RedirectStandardError = $true
    $profileInfo.Arguments = @(
        (Quote-ProcessArgument $profileScript),
        '--live',
        '--url', (Quote-ProcessArgument $CompanionUrl),
        '--presentation-url', (Quote-ProcessArgument $PresentationUrl),
        '--require-jawl-url', (Quote-ProcessArgument $JawlUrl),
        '--report', (Quote-ProcessArgument $profileReportPath)
    ) -join ' '
    $profileInfo.EnvironmentVariables.Clear()
    foreach ($name in $safeEnvironment.Keys) {
        if ($null -ne $safeEnvironment[$name]) {
            $profileInfo.EnvironmentVariables[$name] = [string]$safeEnvironment[$name]
        }
    }
    $script:profileProcess = [Diagnostics.Process]::Start($profileInfo)
    $script:profileStdoutDrain = $script:profileProcess.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null)
    $script:profileStderrDrain = $script:profileProcess.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $script:profileIdentity = Get-ProcessIdentity ([int]$script:profileProcess.Id)
        if ($null -ne $script:profileIdentity -and
            [String]::Equals($script:profileIdentity.ExecutablePath, $resolvedJawlPython, [StringComparison]::OrdinalIgnoreCase)) {
            $script:profileIdentity.Depth = 100
            $script:ownedIdentities.Add($script:profileIdentity)
            break
        }
        if ($script:profileProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 100
    }
    $profileDeadline = (Get-Date).AddSeconds($WaitSeconds)
    while (-not $script:profileProcess.HasExited -and (Get-Date) -lt $profileDeadline) {
        if ($null -eq $script:profileIdentity -or -not (Test-ProcessIdentity $script:profileIdentity)) {
            throw 'Target release profile process identity/creation time could not be verified'
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $script:profileProcess.HasExited) {
        throw "Target release profile did not exit within $WaitSeconds seconds"
    }
    if ($script:profileProcess.ExitCode -ne 0) {
        throw "Target release profile failed with exit code $($script:profileProcess.ExitCode)"
    }

    $outcomeStatus = 'passed'
} catch {
    $failureMessage = $_.Exception.Message
} finally {
    Add-VerifiedDescendants $script:rootIdentity
    Add-VerifiedDescendants $script:profileIdentity
    if ($null -ne $script:rootIdentity -and (Test-ProcessIdentity $script:rootIdentity)) {
        try {
            Invoke-WebRequest -UseBasicParsing -Method Post `
                -Uri (($jawlUri.AbsoluteUri.TrimEnd('/') + '/api/agent/stop')) `
                -Headers @{ 'X-Console-Token' = $token } `
                -ContentType 'application/json' -Body '{}' -TimeoutSec 5 | Out-Null
        } catch {
            # Verified process cleanup below remains bounded to this run.
        }
    }
    Add-VerifiedDescendants $script:rootIdentity
    Add-VerifiedDescendants $script:profileIdentity
    foreach ($identity in ($script:ownedIdentities | Sort-Object Depth -Descending)) {
        Stop-VerifiedProcess $identity
    }
    foreach ($drain in @($script:stdoutDrain, $script:stderrDrain, $script:profileStdoutDrain, $script:profileStderrDrain)) {
        if ($null -ne $drain) {
            try {
                [void]$drain.Wait(5000)
            } catch {
                # Output is intentionally discarded and never printed or persisted.
            }
        }
    }
    if ($reportPathValidated) {
        try {
            Write-OutcomeReport $resolvedReportPath $outcomeStatus $failureMessage
        } catch {
            if ([string]::IsNullOrWhiteSpace($failureMessage)) {
                $failureMessage = "Unable to write redacted outcome report: $($_.Exception.Message)"
                $outcomeStatus = 'failed'
            }
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($failureMessage)) {
    throw $failureMessage
}
Write-Output "PASS target JAWL native status smoke; run_id=$($script:runIdValue); report=$resolvedReportPath"
