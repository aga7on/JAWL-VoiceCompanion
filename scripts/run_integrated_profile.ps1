param(
    [int]$JawlConsolePort,
    [int]$ControlPort,
    [int]$PresentationPort,
    [int]$RunSeconds,
    [ValidateRange(10,600)]
    [int]$StartupTimeoutSeconds = 180,
    [ValidateRange(30,900)]
    [int]$JawlChatTimeoutSeconds = 120,
    [ValidateRange(30,900)]
    [int]$JawlRequestTimeoutSeconds = 0,
    [switch]$NoBrowser,
    [switch]$StartDesktopShell,
    [switch]$StartLocalAudio,
    [switch]$UseVoiceMem,
    [switch]$RunBrowserVoiceE2E,
    [switch]$SyncProfile,
    [switch]$AllowBusyStartup,
    [string[]]$BrowserVoiceWav = @(),
    [string[]]$BrowserVoiceExpected = @(),
[int]$TtsPort,
[ValidateSet('tera', 'voxcpm', 'omnivoice')]
[string]$TtsProvider,
[string]$TeraPython,
[string]$TeraRelease,
[int]$VoxCPMPort = 9891,
[int]$OmniVoicePort = 9890,
[string]$VoxCPMReferenceWav = '',
[string]$OmniVoiceRefWav = 'G:\AI\JAWL-VoiceCompanion\runtime\models\asr\voice_ref_aleksandra.wav',
[string]$OmniVoiceRefText = 'Сначала подготовься. Покажи, чего ты стоишь. В таком виде у тебя нет шансов против демонов. Неплохо. Но прекрасный принц.',
[switch]$EnableProsodyPlanner,
[switch]$EnableStreamingAsr,
[string]$StreamingAsrExe = 'G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe',
[string]$StreamingAsrModel = 'G:\AI\JAWL-VoiceCompanion\runtime\models\asr\gigaam-v3-e2e-rnnt-q8_0.gguf',
[string]$ProsodyModel = 'gemma-3-1b-it',
[string]$ProsodyUrl = 'http://127.0.0.1:8987/v1',
[string]$SensoryFile = '',
[switch]$EnableScreenWatch,
[switch]$EnableScreenOcr,
[switch]$Eg2Vision,
[switch]$EnableAmbientAudio,
[switch]$EnableVoiceDeliveryCues,
[switch]$StartAmbientAudio,
[string]$AmbientAudioDevice = '',
[ValidateSet('eg2', 'qwen-omni')]
[string]$AudioDescriber = 'eg2',
[string]$AudioDescriberUrl = '',
[string]$AudioDescriberModel = 'local-qwen3-omni',
[switch]$EnableSensoryWorker,
[string]$VisionUrl,
[string]$VisionModel,
[int]$ScreenWatchInterval = 30,
[ValidateSet('eg2', 'qwen')]
[string]$VisualDescriber = 'eg2',
[string]$VisualDescriberUrl = '',
[string]$VisualDescriberModel = 'qwen3.5-0.8b',
[switch]$ManageVisualQwenServer,
[int]$VisualDescriberPort = 8994,
[ValidateRange(1,64)]
[int]$VisualDescriberThreads = 4,
[string]$VisualDescriberServerPath = 'runtime\gemma4-e4b-cpu\llama.cpp\llama-server.exe',
[string]$VisualDescriberModelPath = 'runtime\vlm-cpu-bench\models\qwen3.5-0.8b\Qwen3.5-0.8B-Q4_K_M.gguf',
[string]$VisualDescriberMmprojPath = 'runtime\vlm-cpu-bench\models\qwen3.5-0.8b\mmproj-F16.gguf',
[string]$VisualDescriberRoi = '0,0,1,1',
[int]$VisualDescriberDisplayIndex = 0,
[double]$VisualDescriberActiveInterval = 1.0,
[double]$VisualDescriberStaticInterval = 4.0,
[double]$VisualDescriberPeriodic = 4.0,
[double]$VisualDescriberMaxAge = 6.0,
[int]$HostosLevel = -1,
[int]$AmbientTriageSeconds = 0,
[string]$JawlEventDir = '',
    [string]$ResourceTelemetryPath = '',
    [ValidateRange(0.05,60)]
    [double]$ResourceTelemetryIntervalSeconds = 0.25,
[switch]$UseOpenCodeRelay,
    [ValidateRange(0,3)]
    [int]$NativeAccessLevel = 0,
    [switch]$EnableDebugBroker,
    [switch]$EnableNativeBrowser,
    [ValidateRange(0,1048576)]
    [int]$NativeContextWindowTokens = 0,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')]
    [string]$ProfileName = 'daily',
    [ValidateLength(0,200)]
    [string]$JawlModelOverride = '',
    [string]$JawlSourceRoot = '',
    [string]$JawlTemperatureOverride = '',
    [switch]$NoLive2D,
    [switch]$EnableSupervisor,
    [switch]$SuperviseBrainWorker,
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
if ($StartAmbientAudio -and -not $EnableAmbientAudio) { throw '-StartAmbientAudio requires -EnableAmbientAudio.' }
if ($EnableScreenOcr -and -not $EnableScreenWatch -and $VisualDescriber -ne 'qwen') {
    throw '-EnableScreenOcr requires -EnableScreenWatch or -VisualDescriber qwen.'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:JAWL_TEMPERATURE_OVERRIDE = $JawlTemperatureOverride.Trim()
$env:JAWL_NATIVE_BROWSER_ENABLED = $(if ($EnableNativeBrowser) { '1' } else { '0' })
$env:JAWL_CONTEXT_WINDOW_TOKENS = [string]$NativeContextWindowTokens
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$manifestArgs = @('--repo-root', $repo)
if ($PSBoundParameters.ContainsKey('ManifestPath')) { $manifestArgs += @('--manifest', $ManifestPath) }
$manifestJson = & python -X utf8 (Join-Path $repo 'scripts\resolve_runtime_manifest.py') @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Runtime manifest resolution failed.' }
$runtimeManifest = $manifestJson | ConvertFrom-Json
if (-not $PSBoundParameters.ContainsKey('AmbientAudioDevice')) {
    $AmbientAudioDevice = [string]$runtimeManifest.audio.loopback_output_device_name
}

function Resolve-LauncherRuntimeDefaults {
    param([object]$Manifest, [System.Collections.IDictionary]$Bound)
    $values = @{
        JawlConsolePort = $Manifest.ports.jawl_console
        ControlPort = $Manifest.ports.control
        PresentationPort = $Manifest.ports.presentation
        RunSeconds = $Manifest.launch.run_seconds
        ProfileName = $Manifest.profile
        TtsPort = $Manifest.ports.tera_tts
        TtsProvider = $Manifest.launch.tts_provider
        TeraPython = $Manifest.models.tera_python
        TeraRelease = $Manifest.models.tera_release
        VisionUrl = $Manifest.vision.url
        VisionModel = $Manifest.vision.model
    }
    foreach ($name in @($values.Keys)) {
        if ($Bound.Keys -contains $name) { $values[$name] = $Bound[$name] }
        if ($null -eq $values[$name] -or [string]::IsNullOrWhiteSpace([string]$values[$name])) {
            throw "Runtime manifest is missing required setting: $name"
        }
    }
    return $values
}

$runtimeDefaults = Resolve-LauncherRuntimeDefaults $runtimeManifest $PSBoundParameters
foreach ($name in $runtimeDefaults.Keys) { Set-Variable -Name $name -Value $runtimeDefaults[$name] }
function Assert-EffectivePorts([object[]]$Ports, [int[]]$ReservedPorts) {
    foreach ($entry in $Ports) {
        if ($entry.Port -lt 1 -or $entry.Port -gt 65535 -or $entry.Port -eq 8765 -or
            $ReservedPorts -contains $entry.Port) {
            throw ("{0} port is invalid or reserved: {1}" -f $entry.Name, $entry.Port)
        }
    }
    $duplicates = @($Ports | Group-Object { $_.Port } | Where-Object Count -gt 1)
    if ($duplicates.Count) { throw 'Integrated profile service ports must be distinct.' }
}
if ($RunSeconds -lt 0) { throw 'RunSeconds cannot be negative.' }
$effectiveTtsPort = if ($TtsProvider -eq 'voxcpm') { $VoxCPMPort } elseif ($TtsProvider -eq 'omnivoice') { $OmniVoicePort } else { $TtsPort }
$effectivePorts = @(
    @{ Name = 'JAWL console'; Port = $JawlConsolePort },
    @{ Name = 'Companion control'; Port = $ControlPort },
    @{ Name = 'Companion presentation'; Port = $PresentationPort },
    @{ Name = 'TTS'; Port = $effectiveTtsPort }
)
if ($ManageVisualQwenServer) { $effectivePorts += @{ Name = 'Visual Qwen'; Port = $VisualDescriberPort } }
Assert-EffectivePorts $effectivePorts (@(8765) + @($runtimeManifest.ports.reserved))
$env:JAWL_MODEL_OVERRIDE = $JawlModelOverride.Trim()
$sourceRoot = [IO.Path]::GetFullPath((Join-Path $repo 'runtime\jawl-sources'))
$sourceCandidate = if ($JawlSourceRoot) { [IO.Path]::GetFullPath($JawlSourceRoot) } else { Join-Path $sourceRoot 'jawl-20260906-daily-v2' }
if (-not (Test-Path -LiteralPath $sourceCandidate -PathType Container)) {
    throw 'JawlSourceRoot must be an existing snapshot inside runtime/jawl-sources.'
}
$source = (Resolve-Path -LiteralPath $sourceCandidate).Path
if (-not $source.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'JawlSourceRoot must resolve inside runtime/jawl-sources.'
}
$env:JAWL_SOURCE_ROOT = $source
$py = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'
$browserPy = (Get-Command python -ErrorAction Stop).Source
$profileHome = Join-Path (Join-Path $repo 'runtime\instances') $ProfileName
$logDir = Join-Path $profileHome 'logs\integrated'
$profileLockPath = Join-Path $profileHome 'run.lock'
$supervisorStopPath = Join-Path (Join-Path $repo 'runtime\instances') 'supervisor.stop'
$supervisorPidPath = Join-Path (Join-Path $repo 'runtime\instances') 'supervisor.pid'
$portFile = Join-Path $profileHome 'data\interfaces\host\terminal\terminal.port'
$launcherStopRequestPath = Join-Path $profileHome 'data\interfaces\launcher-stop.request'
$launcherStopStatusPath = Join-Path $profileHome 'data\interfaces\launcher-stop.status'
function Resolve-RepoPath([string]$PathValue) {
    if ([IO.Path]::IsPathRooted($PathValue)) { return $PathValue }
    return Join-Path $repo $PathValue
}
$teraPy = Resolve-RepoPath $TeraPython
$teraRelease = Resolve-RepoPath $TeraRelease
$visualQwenExe = Resolve-RepoPath $VisualDescriberServerPath
$visualQwenModel = Resolve-RepoPath $VisualDescriberModelPath
$visualQwenMmproj = Resolve-RepoPath $VisualDescriberMmprojPath
$voxcpmPy = 'G:\AI\VoxCPM\.venv\Scripts\python.exe'
$voxcpmModelDir = 'G:\AI\VoxCPM\models\models--openbmb--VoxCPM2\snapshots\32279effe8c19989596f05d353d1447f51d9e915'
$omniPy = 'G:\AI\OmniVoice\venv\Scripts\python.exe'
$omniModelDir = 'G:\AI\OmniVoice\models\k2-fsa-OmniVoice'
$ttsWorkerName = if ($TtsProvider -eq 'voxcpm') { 'VoxCPM2' } elseif ($TtsProvider -eq 'omnivoice') { 'OmniVoice' } else { 'TeraTTSv2' }
$ttsWorkerPort = if ($TtsProvider -eq 'voxcpm') { $VoxCPMPort } elseif ($TtsProvider -eq 'omnivoice') { $OmniVoicePort } else { $TtsPort }
$asrPy = 'G:\AI\JAWL-VoiceCompanion\runtime\vision-venv\Scripts\python.exe'
$voicememPy = 'G:\AI\VoiceMem\.venv\Scripts\python.exe'
$voicememMemoryRoot = Join-Path $profileHome 'data\sensory\voicemem'

if (-not (Test-Path -LiteralPath $py)) { throw "Owned runtime Python is missing: $py" }
if (-not (Test-Path -LiteralPath $source)) { throw "Pinned JAWL source is missing: $source" }
if ($StartLocalAudio -and -not $UseVoiceMem) {
    throw 'StartLocalAudio requires -UseVoiceMem: the audio route is intentionally fail-closed without the sensory sidecar.'
}
# Lock before prepare/configure, not merely before starting processes: a
# second launcher must not rewrite the configuration of a running profile.
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$profileLock = $null
try {
    $profileLock = [IO.File]::Open($profileLockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
} catch [IO.IOException] {
    throw "Managed profile is already running: $ProfileName. Stop it before starting another launcher."
}
try {
    $lockText = "pid=$PID`nstarted=$([DateTime]::UtcNow.ToString('o'))`nprofile=$ProfileName`n"
    $lockBytes = [Text.UTF8Encoding]::new($false).GetBytes($lockText)
    $profileLock.SetLength(0)
    $profileLock.Write($lockBytes, 0, $lockBytes.Length)
    $profileLock.Flush()
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $launcherStopRequestPath) | Out-Null
    Remove-Item -LiteralPath $launcherStopRequestPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $launcherStopStatusPath -Force -ErrorAction SilentlyContinue
& $browserPy (Join-Path $repo 'scripts\verify_jawl_snapshot.py') --source $source | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Pinned JAWL source verification failed; refusing to start.' }
$env:JAWL_PROFILE_NAME = $ProfileName
$prepareArgs = @()
if ($SyncProfile) { $prepareArgs += '--sync' }
& $py (Join-Path $repo 'scripts\prepare_daily_profile.py') @prepareArgs | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Owned JAWL profile preparation failed; refusing to start.' }
$nativeProfileArgs = @(
    '--profile', $ProfileName,
    '--access-level', [string]$NativeAccessLevel,
    '--terminal-history-limit', '200',
    '--terminal-context-limit', '200'
)
if ($EnableNativeBrowser) { $nativeProfileArgs += '--enable-browser' }
if ($NativeContextWindowTokens -gt 0) { $nativeProfileArgs += @('--context-window-tokens', [string]$NativeContextWindowTokens) }
if ($env:JAWL_MODEL_OVERRIDE) { $nativeProfileArgs += @('--model-override', $env:JAWL_MODEL_OVERRIDE) }
if ($env:JAWL_TEMPERATURE_OVERRIDE) { $nativeProfileArgs += @('--temperature-override', $env:JAWL_TEMPERATURE_OVERRIDE) }
if ($EnableDebugBroker) { $nativeProfileArgs += '--enable-debug-broker' }
& $py (Join-Path $repo 'scripts\configure_profile_native.py') @nativeProfileArgs | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Owned JAWL native profile configuration failed; refusing to start.' }
if ($JawlRequestTimeoutSeconds -gt 0) {
    $settingsPath = Join-Path $profileHome 'config\settings.yaml'
    $settingsText = [IO.File]::ReadAllText($settingsPath, [Text.UTF8Encoding]::new($false))
    $settingsText = [regex]::Replace(
        $settingsText,
        '(?m)^(\s+request_timeout_seconds:\s*)\d+(\s*)$',
        ('${1}' + $JawlRequestTimeoutSeconds + '${2}')
    )
    [IO.File]::WriteAllText($settingsPath, $settingsText, [Text.UTF8Encoding]::new($false))
}
$dynamicContextBudgetChars = 0
if (-not [string]::IsNullOrWhiteSpace($env:JAWL_DYNAMIC_CONTEXT_BUDGET_CHARS)) {
    if (-not [int]::TryParse($env:JAWL_DYNAMIC_CONTEXT_BUDGET_CHARS, [ref]$dynamicContextBudgetChars) -or
        $dynamicContextBudgetChars -lt 2000 -or $dynamicContextBudgetChars -gt 100000) {
        throw 'JAWL_DYNAMIC_CONTEXT_BUDGET_CHARS must be an integer from 2000 to 100000.'
    }
    $settingsPath = Join-Path $profileHome 'config\settings.yaml'
    $settingsText = [IO.File]::ReadAllText($settingsPath, [Text.UTF8Encoding]::new($false))
    $updatedSettingsText = [regex]::Replace(
        $settingsText,
        '(?m)^(\s+max_dynamic_chars:\s*)\d+(\s*)$',
        ('${1}' + $dynamicContextBudgetChars + '${2}'),
        [Text.RegularExpressions.RegexOptions]::None
    )
    if ($updatedSettingsText -eq $settingsText) { throw 'Could not apply the requested dynamic context budget.' }
    [IO.File]::WriteAllText($settingsPath, $updatedSettingsText, [Text.UTF8Encoding]::new($false))
    Write-Host ("Applied per-run dynamic context budget: {0} chars." -f $dynamicContextBudgetChars)
}
& $py (Join-Path $repo 'scripts\preflight_jawl_runtime.py') | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Owned JAWL profile preflight failed.' }

$env:JAWL_INSTANCE_ID = $ProfileName
$env:JAWL_INSTANCE_HOME = $profileHome
$env:JAWL_DATA_DIR = Join-Path $profileHome 'data'
$env:JAWL_CONFIG_DIR = Join-Path $profileHome 'config'
$env:JAWL_LOG_DIR = Join-Path $profileHome 'logs'
$env:JAWL_CACHE_DIR = Join-Path $profileHome 'cache'
$env:JAWL_PROMPT_DIR = Join-Path $profileHome 'prompts'
$env:JAWL_SANDBOX_DIR = Join-Path $profileHome 'sandbox'
$env:JAWL_ENV_FILE = Join-Path $profileHome '.env'
$env:JAWL_INSTANCES_ROOT = Join-Path $repo 'runtime\instances'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:LLM_API_URL) { $env:LLM_API_URL = 'https://opencode.ai/zen/v1' }
 $loopbackProvider = $env:LLM_API_URL -match '^https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)'
if (-not $env:LLM_REASONING_EFFORT -and $loopbackProvider) { $env:LLM_REASONING_EFFORT = 'none' }
if (-not $env:LLM_API_KEY_1 -and $loopbackProvider) {
    # Local OpenAI-compatible workers do not authenticate. JAWL still expects
    # a non-empty key field, so use a process-local marker never sent remotely.
    $env:LLM_API_KEY_1 = 'local-loopback'
}
if (-not $env:LLM_API_KEY_1 -and -not $UseOpenCodeRelay) {
    throw 'Live JAWL provider is not configured: set LLM_API_KEY_1 in the process environment. No credential is read or stored by this launcher.'
}
# OpenCode Zen free tier toggle: the Console only serves "-free"/contributor
# models (and big-pickle) to OpenCode clients. The loopback relay injects the
# required x-opencode-session header and replaces Authorization from the
# user's own auth.json; paid models work directly without the relay.
if ($UseOpenCodeRelay) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'opencode_header_relay.py'))) {
        throw 'OpenCode relay script is missing'
    }
    if (-not (Test-Path -LiteralPath "$env:USERPROFILE\.local\share\opencode\auth.json")) {
        throw 'OpenCode auth.json is missing; the relay needs the user key.'
    }
    $relayPort = 8891
    $env:OPENCODE_RELAY_KEY = (Get-Content "$env:USERPROFILE\.local\share\opencode\auth.json" -Raw | ConvertFrom-Json).opencode.key
    if (-not $env:OPENCODE_RELAY_SESSION) {
        # Stable per-profile session marker, not a secret.
        $env:OPENCODE_RELAY_SESSION = 'a7c3f2e1-9b84-4d02-8f61-3c5a9e2b7d40'
    }
    $relayProc = $null
    $relayOwned = $false
    if (-not (Test-NetConnection 127.0.0.1 -Port 8891 -WarningAction SilentlyContinue -InformationLevel Quiet)) {
        $relayProc = Start-Process -FilePath $py -ArgumentList @('-B', (Join-Path $PSScriptRoot 'opencode_header_relay.py'), '--port', '8891', '--upstream', 'https://opencode.ai/zen') -WindowStyle Hidden -PassThru
        $relayOwned = $true
        Write-Host "OpenCode relay starting (pid $($relayProc.Id)) on http://127.0.0.1:8891/"
        $relayDeadline = (Get-Date).AddSeconds(20)
        do {
            Start-Sleep -Milliseconds 500
            $relayUp = Test-NetConnection 127.0.0.1 -Port 8891 -WarningAction SilentlyContinue -InformationLevel Quiet
        } until ($relayUp -or (Get-Date) -gt $relayDeadline)
        if (-not $relayUp) { throw 'OpenCode relay did not start on 8891' }
    }
    $env:LLM_API_URL = 'http://127.0.0.1:8891/v1'
    if (-not $env:LLM_API_KEY_1 -or $env:LLM_API_KEY_1 -eq 'local-loopback') { $env:LLM_API_KEY_1 = 'relay-injected' }
}
# The JAWL web console protects mutating control routes with a console token.
# Generate one for this owned process tree only; do not expose it in argv/logs.
if (-not $env:CONSOLE_TOKEN) { $env:CONSOLE_TOKEN = [Guid]::NewGuid().ToString('N') }
function New-RuntimeProcess {
    param([string]$FileName, [string]$Arguments, [string]$WorkingDirectory, [hashtable]$Environment, [string]$LogName)
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FileName
    $info.Arguments = $Arguments
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($entry in $Environment.GetEnumerator()) { $info.Environment[$entry.Key] = [string]$entry.Value }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $process.EnableRaisingEvents = $true
    $log = Join-Path $logDir $LogName
    [void]$process.Start()
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    $process | Add-Member -NotePropertyName OutputTask -NotePropertyValue $outTask
    $process | Add-Member -NotePropertyName ErrorTask -NotePropertyValue $errTask
    $process | Add-Member -NotePropertyName LogPath -NotePropertyValue $log
    return $process
}

function Save-RuntimeLog($process) {
    if (-not $process) { return }
    $process.WaitForExit(5000) | Out-Null
    $text = $process.OutputTask.Result + "`n" + $process.ErrorTask.Result
    [IO.File]::WriteAllText($process.LogPath, $text, [Text.UTF8Encoding]::new($false))
}

function Format-EnvironmentDiagnostic {
    param([System.Collections.IDictionary]$Environment)

    foreach ($name in @($Environment.Keys | Sort-Object)) {
        $configured = $null -ne $Environment[$name] -and
            -not [string]::IsNullOrEmpty([string]$Environment[$name])
        $state = if ($configured) { '<configured>' } else { '<unset>' }
        "ENV $name=$state"
    }
}

function Assert-PortAvailable([int]$Port, [string]$Name) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() } catch { throw "$Name port is unavailable: $Port" } finally { $listener.Stop() }
}

function Stop-OwnedProcessTree($process) {
    if (-not $process) { return }
    $rootId = $process.Id
    try { $expectedStartTicks = $process.StartTime.ToUniversalTime().Ticks } catch { return }
    $current = Get-Process -Id $rootId -ErrorAction SilentlyContinue
    if (-not $current) { return }
    try {
        if ($current.StartTime.ToUniversalTime().Ticks -ne $expectedStartTicks) { return }
    } catch { return }
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ParentProcessId -eq $rootId })
    foreach ($child in $children) {
        $childProcess = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        if (-not $childProcess) { continue }
        try {
            $childCreatedAt = [Management.ManagementDateTimeConverter]::ToDateTime([string]$child.CreationDate)
            if ([Math]::Abs(($childProcess.StartTime.ToUniversalTime() - $childCreatedAt.ToUniversalTime()).TotalSeconds) -gt 2) { continue }
        } catch { continue }
        Stop-OwnedProcessTree $childProcess
    }
    $current = Get-Process -Id $rootId -ErrorAction SilentlyContinue
    if ($current) {
        try {
            if ($current.StartTime.ToUniversalTime().Ticks -eq $expectedStartTicks) {
                Stop-Process -Id $rootId -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
}

function Wait-JawlHeartbeatReady([string]$LogPath, [datetime]$StartedAt, [int]$TimeoutSeconds, $Process, [switch]$AllowBusy) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $cycleStarted = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) { throw 'JAWL console exited before the startup heartbeat completed.' }
        if (Test-Path -LiteralPath $LogPath) {
            $lines = @(Get-Content -LiteralPath $LogPath -Tail 240 -ErrorAction SilentlyContinue)
            foreach ($line in $lines) {
                $timestamp = [regex]::Match($line, '^(?<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})')
                if (-not $timestamp.Success) { continue }
                try { $lineAt = [datetime]::ParseExact($timestamp.Groups['ts'].Value, 'yyyy-MM-dd HH:mm:ss.fff', [Globalization.CultureInfo]::InvariantCulture) } catch { continue }
                if ($lineAt -lt $StartedAt.AddSeconds(-2)) { continue }
                if ($line -match 'System\] JAWL started successfully') {
                    $cycleStarted = $true
                    if ($AllowBusy -and (Test-Path -LiteralPath $portFile)) { return }
                    continue
                }
                if ($cycleStarted -and $line -match '\[ReAct\] (Empty actions list received|Duplicate successful action batch)\..*Concluding cycle') {
                    return
                }
                if ($cycleStarted -and (Test-Path -LiteralPath $portFile) -and $line -match '\[Agent Action Result\].*\(Success\):') {
                    # A working/resumed Goal need not become idle before the
                    # UI can attach. A validated native action plus the live
                    # terminal channel proves startup progress.
                    return
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "JAWL startup heartbeat did not complete within $TimeoutSeconds seconds; refusing to expose Companion as ready. Inspect $LogPath."
}

Assert-PortAvailable $JawlConsolePort 'JAWL console'
Assert-PortAvailable $ControlPort 'Companion control'
Assert-PortAvailable $PresentationPort 'Companion presentation'
if ($VisualDescriber -eq 'qwen') {
    if ($ManageVisualQwenServer -and [string]::IsNullOrWhiteSpace($VisualDescriberUrl)) {
        $VisualDescriberUrl = "http://127.0.0.1:$VisualDescriberPort/v1"
    }
    if ([string]::IsNullOrWhiteSpace($VisualDescriberUrl)) {
        throw 'VisualDescriber=qwen requires a local server URL or -ManageVisualQwenServer.'
    }
    $visualUri = [Uri]$VisualDescriberUrl
    if ($visualUri.Scheme -ne 'http' -or $visualUri.DnsSafeHost -notin @('127.0.0.1', 'localhost', '::1') -or
        $visualUri.AbsolutePath.TrimEnd('/') -ne '/v1' -or $visualUri.Query -or $visualUri.Fragment -or $visualUri.UserInfo) {
        throw 'Visual Qwen URL must be a loopback /v1 URL.'
    }
    if ($ManageVisualQwenServer) {
        if ($VisualDescriberPort -lt 1 -or $VisualDescriberPort -gt 65535) { throw 'VisualDescriberPort is invalid.' }
        if ($visualUri.Port -ne $VisualDescriberPort) {
            throw 'Managed Visual Qwen URL port must match VisualDescriberPort.'
        }
        foreach ($path in @($visualQwenExe, $visualQwenModel, $visualQwenMmproj)) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Visual Qwen resource is missing: $path" }
        }
        Assert-PortAvailable $VisualDescriberPort 'Visual Qwen'
    }
} elseif ($ManageVisualQwenServer) {
    throw '-ManageVisualQwenServer requires -VisualDescriber qwen.'
}
if ($StartLocalAudio) {
    # Idempotent audio worker startup: if a healthy worker already owns the
    # port (leftover from a previous run or manual boot), reuse it instead of
    # failing the whole profile. This makes relaunch after a partial stop safe.
    # GigaAM (crispasr file mode) is the only ASR engine and runs as a
    # per-utterance CLI, so only the TTS worker owns a port here.
    foreach ($audio in @(@{Name=$ttsWorkerName;Port=$ttsWorkerPort})) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $audio.Port)
        try { $listener.Start(); $listener.Stop(); $free = $true } catch { $free = $false }
        if (-not $free) { Write-Host ("Reusing already-running {0} on port {1}." -f $audio.Name, $audio.Port) }
    }
}
if ($UseVoiceMem -and -not (Test-Path -LiteralPath $voicememPy -PathType Leaf)) { throw "VoiceMem runtime is missing: $voicememPy" }

$jawl = $null
$companion = $null
$desktopShell = $null
$visualQwenServer = $null
$tera = $null
$sensory = $null
$supervisor = $null
$resourceMonitor = $null
$resourceTelemetryStopPath = $null
$resourceReadyPath = $null
try {
    $audioArgs = ''
    if ($StartLocalAudio) {
        if ($TtsProvider -eq 'voxcpm') {
            $audioResources = @($voxcpmPy, $voxcpmModelDir)
        } elseif ($TtsProvider -eq 'omnivoice') {
            # ADR-045 voice lane: k2-fsa OmniVoice (RU realtime, RTF ~0.1
            # measured on GPU 1 next to the Hikari brain). The reference
            # sample fixes the voice; text is the only per-request input.
            $audioResources = @($omniPy, $omniModelDir, (Join-Path $repo 'scripts\omnivoice_server.py'))
            if ($OmniVoiceRefWav) { $audioResources += $OmniVoiceRefWav }
        } else {
            $audioResources = @($teraPy, $teraRelease)
        }
        if ($EnableStreamingAsr) {
            foreach ($path in @($StreamingAsrExe, $StreamingAsrModel)) {
                if (-not (Test-Path -LiteralPath $path)) { throw "Streaming ASR resource is missing: $path" }
            }
        }
        if ($VoxCPMReferenceWav) {
            if (-not (Test-Path -LiteralPath $VoxCPMReferenceWav -PathType Leaf)) { throw "VoxCPM reference audio is missing: $VoxCPMReferenceWav" }
            $audioResources += $VoxCPMReferenceWav
        }
        foreach ($path in $audioResources) { if (-not (Test-Path -LiteralPath $path)) { throw "Local audio resource is missing: $path" } }
        # Start only the workers whose ports are actually free; healthy leftover
        # workers are reused so a relaunch does not spawn duplicates.
        # GigaAM (crispasr file mode) is the only ASR engine and it is a
        # per-utterance CLI, so there is no ASR server port to manage.
        $ttsAlready = $false
        $audioChecks = @(@{Name=$ttsWorkerName;Port=$ttsWorkerPort})
        foreach ($audio in $audioChecks) {
            $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $audio.Port)
            try { $probe.Start(); $probe.Stop(); $probeFree = $true } catch { $probeFree = $false }
            if (-not $probeFree) {
                if ($audio.Name -eq $ttsWorkerName) { $ttsAlready = $true }
            }
        }
        if (-not $ttsAlready) {
            if ($TtsProvider -eq 'voxcpm') {
                $voxArgs = "scripts\voxcpm_server.py --device cuda:0 --port $VoxCPMPort --threads 24 --inference-timesteps 10"
                if ($VoxCPMReferenceWav) { $voxArgs += " --reference-wav `"$VoxCPMReferenceWav`"" }
                $tera = New-RuntimeProcess $voxcpmPy $voxArgs $repo @{CUDA_VISIBLE_DEVICES = '1'} 'voxcpm-tts.log'
            } elseif ($TtsProvider -eq 'omnivoice') {
                # The worker pins itself to cuda:1 (the free lane next to the
                # Hikari brain, live-verified 13.9/16 GB coexistence). The
                # reference sample fixes the voice (owner-selected); text is
                # the only per-request input.
                $omniArgs = "scripts\omnivoice_server.py --host 127.0.0.1 --port $OmniVoicePort --device cuda:1 --ref-audio `"$OmniVoiceRefWav`""
                if ($OmniVoiceRefText) { $omniArgs += " --ref-text `"$OmniVoiceRefText`"" }
                $tera = New-RuntimeProcess $omniPy $omniArgs $repo @{} 'omnivoice-tts.log'
            } else {
                $tera = New-RuntimeProcess $teraPy "scripts\teratts_server.py --release-dir `"$teraRelease`" --voice ru_f1 --model distilled --threads 24 --host 127.0.0.1 --port $TtsPort" $repo @{} 'tera-tts.log'
            }
        }
        $audioDeadline = [DateTime]::UtcNow.AddSeconds(300)
        while ([DateTime]::UtcNow -lt $audioDeadline) {
            if ($tera -and $tera.HasExited) { throw "$ttsWorkerName exited during integrated startup." }
            try { $teraHealth = Invoke-RestMethod "http://127.0.0.1:$ttsWorkerPort/health" -TimeoutSec 2 } catch { $teraHealth = $null }
            if ($teraHealth.status -eq 'ok') { break }
            Start-Sleep -Seconds 1
        }
        if ($teraHealth.status -ne 'ok') { throw 'Local TTS worker did not become healthy.' }
        $audioArgs = " --tts-provider $TtsProvider --tts-url http://127.0.0.1:$ttsWorkerPort"
        if ($EnableSensoryWorker -and $SensoryFile) {
            $sensoryArgs = "scripts\sensory_worker.py --duration 0 --out `"$SensoryFile`" --crispasr-exe `"$StreamingAsrExe`" --gigaam-model `"$StreamingAsrModel`""
            $sensory = New-RuntimeProcess $asrPy $sensoryArgs $repo @{} 'sensory.log'
        }
        if ($EnableProsodyPlanner -and $TtsProvider -eq 'tera') {
            $audioArgs += " --prosody-planner --prosody-url $ProsodyUrl --prosody-model $ProsodyModel"
        }
        if ($EnableStreamingAsr) {
            if (-not (Test-Path -LiteralPath $StreamingAsrExe -PathType Leaf)) { throw "Streaming ASR executable is missing: $StreamingAsrExe" }
            if (-not (Test-Path -LiteralPath $StreamingAsrModel -PathType Leaf)) { throw "Streaming ASR model is missing: $StreamingAsrModel" }
            $audioArgs += " --streaming-asr --streaming-asr-exe `"$StreamingAsrExe`" --streaming-asr-model `"$StreamingAsrModel`" --streaming-asr-backend gigaam"
        }
    }
    # Ambient loopback ASR can run without a TTS worker. Validate and pass its
    # per-utterance GigaAM executable/model independently of StartLocalAudio.
    if ($EnableStreamingAsr -and -not $StartLocalAudio) {
        foreach ($path in @($StreamingAsrExe, $StreamingAsrModel)) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Streaming ASR resource is missing: $path" }
        }
        $audioArgs += " --streaming-asr --streaming-asr-exe `"$StreamingAsrExe`" --streaming-asr-model `"$StreamingAsrModel`" --streaming-asr-backend gigaam"
    }
$jawlEnv = @{}
    $jawlEnv['JAWL_COMPANION_UI_URL'] = "http://127.0.0.1:$ControlPort"
    foreach ($name in 'JAWL_INSTANCE_ID','JAWL_INSTANCE_HOME','JAWL_DATA_DIR','JAWL_CONFIG_DIR','JAWL_LOG_DIR','JAWL_CACHE_DIR','JAWL_PROMPT_DIR','JAWL_SANDBOX_DIR','JAWL_ENV_FILE','JAWL_INSTANCES_ROOT','PYTHONIOENCODING','LLM_API_URL','LLM_MAX_OUTPUT_TOKENS','CONSOLE_TOKEN') {
        # Optional provider tuning variables may be absent. Do not turn an
        # unset value into a launcher failure; required credentials are
        # validated explicitly below.
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($null -ne $value) { $jawlEnv[$name] = $value }
    }
    # The pinned source is hash-verified and must remain immutable while it is
    # running; Python bytecode caches would otherwise invalidate its manifest.
    $jawlEnv['LLM_REASONING_EFFORT'] = $env:LLM_REASONING_EFFORT
    $jawlEnv['PYTHONDONTWRITEBYTECODE'] = '1'
    # Credentials cross the process boundary only through the environment;
    # they are never placed in command-line arguments or runtime logs.
    $jawlEnv['LLM_API_KEY_1'] = $env:LLM_API_KEY_1
    # Run from the isolated profile home. JAWL has a few relative diagnostic
    # paths; keeping the source tree as cwd would mutate the pinned snapshot.
    $jawlEnv['PYTHONPATH'] = $source
    $jawlEnv['JAWL_SOURCE_ROOT'] = $source
    if ($EnableSupervisor) { $jawlEnv['JAWL_SUPERVISED'] = '1' }

    if ($EnableSupervisor) {
        $registerArgs = @(
            (Join-Path $repo 'scripts\register_supervised_profile.py'),
            '--profile', $ProfileName,
            '--display-name', "JAWL supervised $ProfileName",
            '--source', $source,
            '--instances-root', (Join-Path $repo 'runtime\instances'),
            '--sandbox-root', $env:JAWL_SANDBOX_DIR,
            '--python', $py
        )
        & $py @registerArgs | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Native supervised profile registration failed.' }
        $supervisorEnv = @{}
        foreach ($entry in $jawlEnv.GetEnumerator()) { $supervisorEnv[$entry.Key] = $entry.Value }
        $supervisorEntry = Join-Path $repo 'scripts\run_owned_jawl_supervisor.py'
        $supervisor = New-RuntimeProcess $py "-B `"$supervisorEntry`" --root `"$source`" --interval 1" $profileHome $supervisorEnv 'supervisor.log'
        $supervisorDeadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path -LiteralPath $supervisorPidPath) -and [DateTime]::UtcNow -lt $supervisorDeadline) {
            if ($supervisor.HasExited) { throw 'Native instance supervisor exited during startup.' }
            Start-Sleep -Milliseconds 100
        }
        if ($supervisor.HasExited -or -not (Test-Path -LiteralPath $supervisorPidPath)) { throw 'Native instance supervisor did not publish readiness.' }
    }
    $startupStartedAt = Get-Date
    $consoleEntry = Join-Path $repo 'scripts\run_owned_jawl_console.py'
    $jawl = New-RuntimeProcess $py "-B `"$consoleEntry`" --host 127.0.0.1 --port $JawlConsolePort --no-browser --keep-agent" $profileHome $jawlEnv 'jawl-console.log'
    $consoleUrl = "http://127.0.0.1:$JawlConsolePort"
    $consoleHeaders = @{ 'X-Console-Token' = $env:CONSOLE_TOKEN }
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            Invoke-RestMethod "$consoleUrl/api/agent/status" -Headers $consoleHeaders -TimeoutSec 2 | Out-Null
            $admission = Invoke-RestMethod "$consoleUrl/api/companion/admission-capabilities" -Headers $consoleHeaders -TimeoutSec 2
            if ($admission.feature -ne 'http-turn-admission-v1' -or $admission.cancel_before_dispatch -ne $true) {
                throw 'Owned JAWL admission capability is missing.'
            }
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'JAWL console did not become ready.' }
    $agentStatus = Invoke-RestMethod "$consoleUrl/api/agent/status" -Headers $consoleHeaders -TimeoutSec 10
    if ($agentStatus.running -ne $true -and $agentStatus.starting -ne $true) {
        Invoke-RestMethod "$consoleUrl/api/agent/start" -Method Post -Headers $consoleHeaders -TimeoutSec 120 | Out-Host
    }
    for ($i = 0; $i -lt 120; $i++) {
        if (Test-Path -LiteralPath $portFile) { break }
        if ($jawl.HasExited) { throw 'JAWL console exited while starting the agent.' }
        if ($EnableSupervisor -and $supervisor.HasExited) { throw 'Native instance supervisor exited while starting the agent.' }
        try {
            $agentStatus = Invoke-RestMethod "$consoleUrl/api/agent/status" -Headers $consoleHeaders -TimeoutSec 2
            if ($agentStatus.running -ne $true -and $agentStatus.starting -ne $true -and -not $EnableSupervisor) {
                throw "JAWL agent failed to start; inspect $env:JAWL_LOG_DIR\startup\startup_error.log"
            }
        } catch [System.Management.Automation.RuntimeException] { throw }
        catch { }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Path -LiteralPath $portFile)) { throw "JAWL terminal port file was not ready: $portFile" }
    Wait-JawlHeartbeatReady (Join-Path $env:JAWL_LOG_DIR 'main.log') $startupStartedAt $StartupTimeoutSeconds $jawl -AllowBusy:$AllowBusyStartup

    $companionEnv = @{
        PYTHONPATH = Join-Path $repo 'src'
        PYTHONIOENCODING = 'utf-8'
        JAWL_WEB_TOKEN = $env:CONSOLE_TOKEN
        JAWL_LAUNCHER_STOP_REQUEST = $launcherStopRequestPath
        JAWL_LAUNCHER_STOP_STATUS = $launcherStopStatusPath
    }
    if ($env:JAWL_CONFIG_DIR) { $companionEnv.JAWL_CONFIG_DIR = $env:JAWL_CONFIG_DIR }
    if ($env:JAWL_ENV_FILE) { $companionEnv.JAWL_ENV_FILE = $env:JAWL_ENV_FILE }
    if ($env:JAWL_LOG_DIR) { $companionEnv.JAWL_LOG_DIR = $env:JAWL_LOG_DIR }
    if ($env:JAWL_SCREEN_TARGET_TITLE) { $companionEnv.JAWL_SCREEN_TARGET_TITLE = $env:JAWL_SCREEN_TARGET_TITLE }
    $companionArgs = "-u -m jawl_voicecompanion --host 127.0.0.1 --port $ControlPort --presentation-host 127.0.0.1 --presentation-port $PresentationPort --jawl-port-file `"$portFile`" --jawl-web-url $consoleUrl --jawl-chat-timeout $JawlChatTimeoutSeconds --jawl-hostos-control$audioArgs"
    # Unified config hub: the companion edits the profile config in place with
    # revision semantics; both paths are optional so tests without a profile pass.
    if ($env:JAWL_CONFIG_DIR) { $companionArgs += " --jawl-config-dir `"$env:JAWL_CONFIG_DIR`"" }
    if ($env:JAWL_ENV_FILE) { $companionArgs += " --jawl-env-file `"$env:JAWL_ENV_FILE`"" }
    if ($env:JAWL_LOG_DIR) { $companionArgs += " --jawl-log-dir `"$env:JAWL_LOG_DIR`"" }
    # ADR-045: Live2D assets are removed; the 3D VRM avatar lives in the
    # Electron desktop shell. $NoLive2D stays accepted as a no-op for older
    # command lines.
    if ($UseVoiceMem) { $companionArgs += " --voicemem-python `"$voicememPy`" --voicemem-memory-root `"$voicememMemoryRoot`" --voicemem-local-memory --voicemem-warmup text --voicemem-timeout 120" }
    if ($SuperviseBrainWorker) {
        # One executable entry (ADR-041 stage 2): the Companion process owns
        # the local brain worker via RuntimeSupervisor (health, bounded
        # restarts, fail-closed, Job Object KILL_ON_JOB_CLOSE). The wrapper
        # sets LLM_API_URL and JAWL_MODEL_OVERRIDE; the worker command and
        # model paths come from the entry's CLI defaults (manifest wiring).
        $companionArgs += " --supervise-workers"
        Write-Host 'Brain worker ownership: companion entry (supervised).'
    }
    if ($SensoryFile) {
        $companionArgs += " --ambient-memory --sensory-file `"$SensoryFile`""
        if ($AmbientTriageSeconds -gt 0) { $companionArgs += " --ambient-triage-interval $AmbientTriageSeconds" }
    }
    if ($EnableAmbientAudio) {
        # Explicit opt-in for bounded Windows system-audio loopback. Capture
        # stays stopped for browser-controlled profiles unless StartAmbientAudio
        # is also requested. Ambient memory owns the bounded evidence store.
        $companionArgs += " --ambient-audio --ambient-memory"
        if (-not [string]::IsNullOrWhiteSpace($AmbientAudioDevice)) {
            $companionArgs += " --ambient-audio-device `"$AmbientAudioDevice`""
        }
        if ($AudioDescriber -eq 'qwen-omni') {
            if ([string]::IsNullOrWhiteSpace($AudioDescriberUrl)) { throw 'AudioDescriberUrl is required for qwen-omni.' }
            $companionArgs += " --audio-describer qwen-omni --audio-describer-url `"$AudioDescriberUrl`" --audio-describer-model `"$AudioDescriberModel`""
        }
        if ($StartAmbientAudio) { $companionArgs += ' --ambient-audio-autostart' }
    }
    if ($EnableVoiceDeliveryCues) {
        $companionArgs += ' --voice-delivery-cues'
    }
    if ($EnableScreenWatch) {
        # Screen capture remains explicit opt-in. By default the launcher
        # connects to the configured external vision endpoint; -Eg2Vision
        # keeps the same capture/watch loop on the local EmbeddingGemma 2
        # describer without starting any VLM worker.
        if (-not $JawlEventDir) { $JawlEventDir = Join-Path $profileHome "sandbox\_system\instances\$ProfileName\.jawl_events" }
        New-Item -ItemType Directory -Force -Path $JawlEventDir | Out-Null
        $screenArgs = " --hostos-live --screen-enabled"
        if (-not $Eg2Vision) { $screenArgs += " --vision-url $VisionUrl --vision-model $VisionModel" }
        if ($EnableScreenOcr) { $screenArgs += ' --screen-ocr' }
        $screenArgs += " --screen-watch --screen-watch-interval $ScreenWatchInterval --jawl-event-dir `"$JawlEventDir`""
        $companionArgs += $screenArgs
        if ($HostosLevel -ge 0) { $companionArgs += " --hostos-level $HostosLevel" }
        else { $companionArgs += " --hostos-level 1" }
    } elseif ($HostosLevel -ge 0) {
        $companionArgs += " --hostos-level $HostosLevel"
    }
    if ($VisualDescriber -eq 'qwen') {
        # Selecting the Qwen visual sensor is the explicit screen-capture
        # opt-in. Avoid requiring the legacy ScreenWatch worker, which would
        # start another perception loop against the same display.
        if (-not $EnableScreenWatch) { $companionArgs += ' --hostos-live --screen-enabled' }
        if ($EnableScreenOcr -and -not $EnableScreenWatch) { $companionArgs += ' --screen-ocr' }
        $visualUrl = $VisualDescriberUrl
        $companionArgs += " --visual-describer qwen --visual-describer-url `"$visualUrl`" --visual-describer-model `"$VisualDescriberModel`" --visual-describer-roi `"$VisualDescriberRoi`" --visual-describer-display-index $VisualDescriberDisplayIndex --visual-describer-active-interval $VisualDescriberActiveInterval --visual-describer-static-interval $VisualDescriberStaticInterval --visual-describer-periodic $VisualDescriberPeriodic --visual-describer-max-age $VisualDescriberMaxAge"
    }
    if ($VisualDescriber -eq 'qwen') {
        $visualOrigin = $visualUri.GetLeftPart([UriPartial]::Authority)
        $visualHealthUrl = "$visualOrigin/health"
        $visualModelsUrl = "$visualOrigin/v1/models"
        if ($ManageVisualQwenServer) {
            # Recheck immediately before launch; the earlier preflight can be
            # separated from this point by a lengthy TTS startup.
            Assert-PortAvailable $VisualDescriberPort 'Visual Qwen launch'
            $visualQwenArgs = '-m "{0}" --mmproj "{1}" --alias "{2}" --host 127.0.0.1 --port {3} -c 4096 -np 1 -ngl 0 --no-mmproj-offload --jinja --reasoning off -t {4} -tb {4} --cache-ram 0 --no-cache-prompt --no-cache-idle-slots --metrics --no-webui' -f `
                $visualQwenModel, $visualQwenMmproj, $VisualDescriberModel, $VisualDescriberPort, $VisualDescriberThreads
            $visualQwenServer = New-RuntimeProcess $visualQwenExe $visualQwenArgs $repo @{} 'visual-qwen.log'
        }
        $visualDeadline = [DateTime]::UtcNow.AddSeconds(240)
        $visualReady = $false
        while ([DateTime]::UtcNow -lt $visualDeadline) {
            if ($visualQwenServer -and $visualQwenServer.HasExited) { throw "Visual Qwen exited during startup (exit $($visualQwenServer.ExitCode))." }
            try {
                $visualHealth = Invoke-RestMethod $visualHealthUrl -TimeoutSec 2
                $visualServed = Invoke-RestMethod $visualModelsUrl -TimeoutSec 2
                $visualReady = $visualHealth.status -eq 'ok' -and @($visualServed.data | Where-Object { $_.id -eq $VisualDescriberModel }).Count -gt 0
            } catch { $visualReady = $false }
            if ($visualReady) { break }
            Start-Sleep -Seconds 1
        }
        if (-not $visualReady) { throw "Visual Qwen did not become healthy and serve model $VisualDescriberModel." }
        if ($ManageVisualQwenServer) {
            $probeImage = Join-Path $repo 'runtime\vlm-cpu-bench\video\frame-01.jpg'
            if (-not (Test-Path -LiteralPath $probeImage -PathType Leaf)) { throw "Visual Qwen probe image is missing: $probeImage" }
            $imageData = [Convert]::ToBase64String([IO.File]::ReadAllBytes($probeImage))
            $probePayload = @{
                model = $VisualDescriberModel
                messages = @(@{ role = 'user'; content = @(
                    @{ type = 'text'; text = 'Describe the visible scene briefly.' },
                    @{ type = 'image_url'; image_url = @{ url = "data:image/jpeg;base64,$imageData" } }
                ) })
                max_tokens = 16
                temperature = 0
                stream = $false
            } | ConvertTo-Json -Depth 10 -Compress
            $probeResponse = Invoke-RestMethod "$visualOrigin/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $probePayload -TimeoutSec 90
            if ([string]::IsNullOrWhiteSpace([string]$probeResponse.choices[0].message.content)) {
                throw 'Visual Qwen image probe returned an empty caption.'
            }
            Write-Host "Visual Qwen ready on CPU (port $VisualDescriberPort, threads $VisualDescriberThreads); image probe passed."
        } else {
            Write-Host "External Visual Qwen ready at $VisualDescriberUrl serving $VisualDescriberModel."
        }
    }
    # Arguments contain local paths/options and loopback URLs; environment
    # values, including credentials, are represented only by configured state.
    $debugDump = @("PY=$py", "ARGS=$companionArgs") + @(Format-EnvironmentDiagnostic -Environment $companionEnv)
    [IO.File]::WriteAllLines((Join-Path $logDir 'companion-debug.txt'), $debugDump)
    $companion = New-RuntimeProcess $py $companionArgs $repo $companionEnv 'companion.log'
    $companionReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($companion.HasExited) { throw 'Companion exited during startup; inspect companion.log.' }
        try { $health = Invoke-RestMethod "http://127.0.0.1:$ControlPort/api/health" -TimeoutSec 2; if ($health.status -in @('ready', 'degraded', 'ok')) { $companionReady = $true; break } } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $companionReady) { throw "Companion health did not become available on port $ControlPort." }
    $companionRuntimeInstanceId = [string]$health.runtime_instance_id
    if ([string]::IsNullOrWhiteSpace($companionRuntimeInstanceId)) {
        throw 'Companion health did not include a runtime instance id.'
    }
    if ($StartDesktopShell) {
        $desktopDir = Join-Path $repo 'desktop'
        $electronExe = Join-Path $desktopDir 'node_modules\electron\dist\electron.exe'
        if (-not (Test-Path -LiteralPath $electronExe -PathType Leaf)) {
            throw "Desktop shell dependencies are missing: $electronExe. Run npm ci in desktop/ first."
        }
        $desktopStdout = Join-Path $logDir 'desktop.log'
        $desktopStderr = Join-Path $logDir 'desktop-error.log'
        # A Node tooling process can export ELECTRON_RUN_AS_NODE=1 into the
        # launcher environment. Electron inherits it and executes main.js as
        # plain Node, where Electron APIs such as ipcMain are unavailable.
        # Clear it only for this child launch, then restore this process state.
        $electronRunAsNode = [Environment]::GetEnvironmentVariable('ELECTRON_RUN_AS_NODE', 'Process')
        try {
            Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
            $desktopShell = Start-Process -FilePath $electronExe -ArgumentList @('"' + $desktopDir + '"') `
                -WorkingDirectory $desktopDir -PassThru `
                -RedirectStandardOutput $desktopStdout -RedirectStandardError $desktopStderr
        } finally {
            if ($null -ne $electronRunAsNode) {
                [Environment]::SetEnvironmentVariable('ELECTRON_RUN_AS_NODE', $electronRunAsNode, 'Process')
            }
        }
        Start-Sleep -Milliseconds 1500
        if ($desktopShell.HasExited) {
            throw "Desktop shell exited during startup (exit $($desktopShell.ExitCode)); inspect $desktopStderr."
        }
        Write-Host "Desktop shell started (pid $($desktopShell.Id))."
    }
    $supervisorText = if ($EnableSupervisor) { " supervisor=$($supervisor.Id)" } else { '' }
    Write-Host "Integrated profile ready: control=$ControlPort presentation=$PresentationPort jawl_console=$JawlConsolePort$supervisorText"
    if ($RunBrowserVoiceE2E) {
        if ($BrowserVoiceWav.Count -lt 3) {
            $BrowserVoiceWav = @(
                (Join-Path $repo 'runtime\synthetic-questions\question-01.wav'),
                (Join-Path $repo 'runtime\synthetic-questions\question-02.wav'),
                (Join-Path $repo 'runtime\synthetic-questions\question-03.wav')
            )
        }
        if ($BrowserVoiceExpected.Count -eq 0) {
            # Keep semantic assertions language-correct even under Windows
            # PowerShell's legacy source-code page.
            $BrowserVoiceExpected = @(
                (-join ([char[]](0x0441,0x0442,0x0430,0x0442,0x0443,0x0441))),
                (-join ([char[]](0x043A,0x043E,0x0440,0x043E,0x0442,0x043A,0x0438,0x0435))),
                (-join ([char[]](0x0442,0x0435,0x0441,0x0442,0x043E,0x0432,0x044B,0x0439)))
            )
        }
        if ($BrowserVoiceExpected.Count -ne $BrowserVoiceWav.Count) {
            throw 'BrowserVoiceExpected must contain one value per BrowserVoiceWav.'
        }
        $voiceArgs = @((Join-Path $repo 'scripts\run_browser_voice_e2e.py'), '--live', '--ui', 'app', '--url', "http://127.0.0.1:$ControlPort", '--report', (Join-Path $repo 'runtime\browser-voice-e2e.json'), '--evidence-dir', (Join-Path $repo 'runtime\browser-evidence\voice'))
        for ($index = 0; $index -lt $BrowserVoiceWav.Count; $index++) {
            $voiceArgs += @('--wav', (Resolve-Path -LiteralPath $BrowserVoiceWav[$index]).Path, "--expected=$($BrowserVoiceExpected[$index])")
        }
        & $browserPy @voiceArgs
        if ($LASTEXITCODE -ne 0) { throw "Browser voice E2E failed with exit code $LASTEXITCODE." }
    }
    if (-not [string]::IsNullOrWhiteSpace($ResourceTelemetryPath)) {
        $resourceOutput = [IO.Path]::GetFullPath((Resolve-RepoPath $ResourceTelemetryPath))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resourceOutput) | Out-Null
        $resourceTelemetryStopPath = "$resourceOutput.stop"
        $resourceReadyPath = "$resourceOutput.ready"
        Remove-Item -LiteralPath $resourceTelemetryStopPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $resourceReadyPath -Force -ErrorAction SilentlyContinue
        $launcherProcess = Get-Process -Id $PID -ErrorAction Stop
        $launcherCreatedAt = ($launcherProcess.StartTime.ToUniversalTime().Ticks - 621355968000000000) / 10000000.0
        $monitorScript = Join-Path $PSScriptRoot 'run_process_tree_monitor.py'
        $monitorArgs = '-B "{0}" --root-pid {1} --root-created-at {2} --root-label "integrated-profile:{3}" --creation-tolerance-seconds 0.005 --output "{4}" --ready-file "{5}" --stop-file "{6}" --interval-seconds {7}' -f `
            $monitorScript, $PID, $launcherCreatedAt.ToString('R', [Globalization.CultureInfo]::InvariantCulture), $ProfileName, $resourceOutput, $resourceReadyPath, $resourceTelemetryStopPath, $ResourceTelemetryIntervalSeconds.ToString('R', [Globalization.CultureInfo]::InvariantCulture)
        $resourceMonitor = New-RuntimeProcess $py $monitorArgs $repo @{} 'process-tree-monitor.log'
        $monitorDeadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path -LiteralPath $resourceReadyPath -PathType Leaf) -and
            [DateTime]::UtcNow -lt $monitorDeadline -and -not $resourceMonitor.HasExited) {
            Start-Sleep -Milliseconds 100
        }
        if ($resourceMonitor.HasExited -or -not (Test-Path -LiteralPath $resourceReadyPath -PathType Leaf)) {
            throw 'Process-tree resource telemetry did not start; inspect process-tree-monitor.log.'
        }
        Write-Host "Process-tree telemetry sampling exact launcher tree to $resourceOutput every $ResourceTelemetryIntervalSeconds s."
    }
    Write-Host 'Press Ctrl+C to stop the complete profile.'
    $startedAt = Get-Date
    while (-not $companion.HasExited -and -not $jawl.HasExited -and
        (-not $EnableSupervisor -or -not $supervisor.HasExited) -and
        (-not $visualQwenServer -or -not $visualQwenServer.HasExited) -and
        (-not $desktopShell -or -not $desktopShell.HasExited) -and
        (-not $resourceMonitor -or -not $resourceMonitor.HasExited)) {
        if (Test-Path -LiteralPath $launcherStopRequestPath -PathType Leaf) {
            try {
                $stopRequest = Get-Content -LiteralPath $launcherStopRequestPath -Raw | ConvertFrom-Json
                if ($stopRequest.schema_version -eq 1 -and
                    [string]$stopRequest.runtime_instance_id -ceq $companionRuntimeInstanceId) {
                    $stopStatus = @{
                        schema_version = 1
                        runtime_instance_id = $companionRuntimeInstanceId
                        request_id = [string]$stopRequest.request_id
                        status = 'stopping'
                        acknowledged_at = [DateTime]::UtcNow.ToString('o')
                    }
                    if ([string]::IsNullOrWhiteSpace($stopStatus.request_id)) { throw 'Managed stop request has no request id.' }
                    $statusTempPath = "$launcherStopStatusPath.$([guid]::NewGuid().ToString('N')).tmp"
                    [IO.File]::WriteAllText($statusTempPath, ($stopStatus | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
                    Move-Item -LiteralPath $statusTempPath -Destination $launcherStopStatusPath -Force
                    Write-Host 'Managed profile stop requested by the companion UI.'
                    break
                }
            } catch { }
        }
        if ($RunSeconds -gt 0 -and ((Get-Date) - $startedAt).TotalSeconds -ge $RunSeconds) { break }
        Start-Sleep -Seconds 1
    }
    if ($companion.HasExited) { throw 'Companion process exited unexpectedly.' }
    if ($visualQwenServer -and $visualQwenServer.HasExited) { throw 'Visual Qwen exited unexpectedly; the integrated profile is stopping.' }
    if ($desktopShell -and $desktopShell.HasExited) { throw 'Desktop shell exited unexpectedly; the integrated profile is stopping.' }
    if ($resourceMonitor -and $resourceMonitor.HasExited) { throw 'Process-tree resource telemetry exited unexpectedly; the integrated profile is stopping.' }
} finally {
    if ($resourceMonitor) {
        if (-not $resourceMonitor.HasExited -and $resourceTelemetryStopPath) {
            try { [IO.File]::WriteAllText($resourceTelemetryStopPath, "stop`n", [Text.UTF8Encoding]::new($false)) } catch { }
            $resourceMonitor.WaitForExit(5000) | Out-Null
            if (-not $resourceMonitor.HasExited) {
                # The monitor is this launcher’s exact child process; retain the
                # ownership/time check before any bounded forced cleanup.
                Stop-OwnedProcessTree $resourceMonitor
                $resourceMonitor.WaitForExit(5000) | Out-Null
            }
        }
        Save-RuntimeLog $resourceMonitor
        if ($resourceTelemetryStopPath) { Remove-Item -LiteralPath $resourceTelemetryStopPath -Force -ErrorAction SilentlyContinue }
        if ($resourceReadyPath) { Remove-Item -LiteralPath $resourceReadyPath -Force -ErrorAction SilentlyContinue }
    }
    try { Invoke-RestMethod "http://127.0.0.1:$JawlConsolePort/api/agent/stop" -Method Post -Headers $consoleHeaders -TimeoutSec 20 | Out-Null } catch { }
    if ($EnableSupervisor) {
        try { [IO.File]::WriteAllText($supervisorStopPath, "stop`n", [Text.UTF8Encoding]::new($false)) } catch { }
    }
    if ($desktopShell -and -not $desktopShell.HasExited) {
        Stop-OwnedProcessTree $desktopShell
        $desktopShell.WaitForExit(10000) | Out-Null
    }
    $ownedProcesses = @($companion, $visualQwenServer, $jawl, $tera, $sensory, $supervisor) | Where-Object { $_ }
    $shutdownDeadline = [DateTime]::UtcNow.AddSeconds(25)
    while (@($ownedProcesses | Where-Object { -not $_.HasExited }).Count -gt 0 -and
        [DateTime]::UtcNow -lt $shutdownDeadline) {
        Start-Sleep -Milliseconds 250
    }
    foreach ($process in $ownedProcesses) {
        if ($process -and -not $process.HasExited) { Stop-OwnedProcessTree $process; $process.WaitForExit(5000) | Out-Null }
        Save-RuntimeLog $process
    }
    Remove-Item -LiteralPath $launcherStopRequestPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $launcherStopStatusPath -Force -ErrorAction SilentlyContinue
    if ($relayOwned -and $relayProc -and -not $relayProc.HasExited) {
        # The relay belongs to this launch only when this launch started it;
        # an externally started relay is deliberately left running.
        Stop-OwnedProcessTree $relayProc
        $relayProc.WaitForExit(5000) | Out-Null
    }
    if ($EnableSupervisor) {
        # A force-killed Windows interpreter cannot run the supervisor finally
        # block. Remove only exact stale markers after the owned process tree
        # has stopped; never touch a live PID or a foreign lock.
        $supervisorLive = $false
        if (Test-Path -LiteralPath $supervisorPidPath) {
            try {
                $markerPid = [int](Get-Content -LiteralPath $supervisorPidPath -Raw)
                $supervisorLive = $null -ne (Get-Process -Id $markerPid -ErrorAction SilentlyContinue)
            } catch { $supervisorLive = $false }
        }
        if (-not $supervisorLive) {
            foreach ($marker in @($supervisorPidPath, (Join-Path (Join-Path $repo 'runtime\instances') 'supervisor.lock'))) {
                if (Test-Path -LiteralPath $marker) {
                    try { [IO.File]::Delete($marker) } catch { }
                }
            }
        }
    }
}
} finally {
    # Preparation/provider failures can happen before the process-loop
    # finally is entered. Release only a relay this launcher actually owns.
    if ($relayOwned -and $relayProc -and -not $relayProc.HasExited) {
        try { $relayProc.Kill(); $relayProc.WaitForExit(5000) | Out-Null } catch { }
    }
    if ($profileLock) { $profileLock.Dispose() }
}
