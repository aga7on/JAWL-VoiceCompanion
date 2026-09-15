param(
    [int]$JawlConsolePort = 8770,
    [int]$ControlPort = 2367,
    [int]$PresentationPort = 8766,
    [int]$RunSeconds = 0,
    [ValidateRange(10,600)]
    [int]$StartupTimeoutSeconds = 180,
    [ValidateRange(30,900)]
    [int]$JawlChatTimeoutSeconds = 120,
    [ValidateRange(30,900)]
    [int]$JawlRequestTimeoutSeconds = 0,
    [switch]$NoBrowser,
    [switch]$StartLocalAudio,
    [switch]$UseVoiceMem,
    [switch]$RunBrowserVoiceE2E,
    [switch]$SyncProfile,
    [switch]$AllowBusyStartup,
    [ValidateSet('gigaam', 'qwen', 'whisper')]
    [string]$AsrBackend = 'gigaam',
    [string[]]$BrowserVoiceWav = @(),
    [string[]]$BrowserVoiceExpected = @(),
[int]$TtsPort = 9889,
[ValidateSet('tera', 'voxcpm')]
[string]$TtsProvider = 'tera',
[int]$VoxCPMPort = 9891,
[string]$VoxCPMReferenceWav = '',
[switch]$EnableProsodyPlanner,
[switch]$EnableStreamingAsr,
[string]$StreamingAsrExe = 'G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe',
[string]$StreamingAsrModel = 'G:\AI\VLM-RealTime-Bench\models\gigaam\gigaam-v3-e2e-rnnt-q8_0.gguf',
[string]$ProsodyModel = 'gemma-3-1b-it',
[string]$ProsodyUrl = 'http://127.0.0.1:8987/v1',
[string]$SensoryFile = '',
[switch]$EnableScreenWatch,
[switch]$EnableSensoryWorker,
[string]$VisionUrl = 'http://127.0.0.1:8986/v1',
[string]$VisionModel = 'bonsai',
[int]$ScreenWatchInterval = 15,
[int]$HostosLevel = -1,
[int]$AmbientTriageSeconds = 0,
[string]$JawlEventDir = '',
[int]$AsrPort = 8984,
[switch]$UseOpenCodeRelay,
    [ValidateRange(0,3)]
    [int]$NativeAccessLevel = 0,
    [switch]$EnableDebugBroker,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')]
    [string]$ProfileName = 'daily',
    [ValidateLength(0,200)]
    [string]$JawlModelOverride = '',
    [string]$JawlTemperatureOverride = '',
    [switch]$NoLive2D,
    [switch]$EnableSupervisor
)

$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:JAWL_MODEL_OVERRIDE = $JawlModelOverride.Trim()
$env:JAWL_TEMPERATURE_OVERRIDE = $JawlTemperatureOverride.Trim()
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'runtime\jawl-sources\jawl-20260906-daily-v2'
$py = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'
$browserPy = (Get-Command python -ErrorAction Stop).Source
$profileHome = Join-Path (Join-Path $repo 'runtime\instances') $ProfileName
$logDir = Join-Path $profileHome 'logs\integrated'
$profileLockPath = Join-Path $profileHome 'run.lock'
$supervisorStopPath = Join-Path (Join-Path $repo 'runtime\instances') 'supervisor.stop'
$supervisorPidPath = Join-Path (Join-Path $repo 'runtime\instances') 'supervisor.pid'
$portFile = Join-Path $profileHome 'data\interfaces\host\terminal\terminal.port'
$teraPy = 'G:\AI\tts_env\Scripts\python.exe'
$teraRelease = 'G:\AI\tts_models\TeraSpace__TeraTTSv2'
$voxcpmPy = 'G:\AI\VoxCPM\.venv\Scripts\python.exe'
$voxcpmModelDir = 'G:\AI\VoxCPM\models\models--openbmb--VoxCPM2\snapshots\32279effe8c19989596f05d353d1447f51d9e915'
$ttsWorkerName = if ($TtsProvider -eq 'voxcpm') { 'VoxCPM2' } else { 'TeraTTSv2' }
$ttsWorkerPort = if ($TtsProvider -eq 'voxcpm') { $VoxCPMPort } else { $TtsPort }
$asrPy = 'G:\AI\JAWL-VoiceCompanion\runtime\vision-venv\Scripts\python.exe'
$asrServerScript = Join-Path $repo 'scripts\asr_whisper_server.py'
$whisperModel = (Join-Path $repo 'runtime\models\whisper-turbo')
$qwenAsrServer = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe'
$qwenAsrModel = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf'
$qwenAsrMmproj = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf'
$voicememPy = 'G:\AI\VoiceMem\.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $py)) { throw "Owned runtime Python is missing: $py" }
if (-not (Test-Path -LiteralPath $source)) { throw "Pinned JAWL source is missing: $source" }
if ($StartLocalAudio -and -not $UseVoiceMem) {
    throw 'StartLocalAudio requires -UseVoiceMem: the audio route is intentionally fail-closed without the sensory sidecar.'
}
& $browserPy (Join-Path $repo 'scripts\verify_jawl_snapshot.py') --source $source | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Pinned JAWL source verification failed; refusing to start.' }
$env:JAWL_PROFILE_NAME = $ProfileName
$prepareArgs = @()
if ($SyncProfile) { $prepareArgs += '--sync' }
& $py (Join-Path $repo 'scripts\prepare_daily_profile.py') @prepareArgs | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Owned JAWL profile preparation failed; refusing to start.' }
$nativeProfileArgs = @('--profile', $ProfileName, '--access-level', [string]$NativeAccessLevel)
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
if (-not $env:LLM_API_KEY_1) {
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
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
# Keep one launcher per managed profile. FileShare.None is released by the OS
# when the launcher exits, including an interrupted PowerShell session, so a
# stale lock file never blocks recovery. This protects the profile data and
# prevents two companions from consuming the same JAWL terminal concurrently.
$profileLock = $null
try {
    $profileLock = [IO.File]::Open($profileLockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $lockText = "pid=$PID`nstarted=$([DateTime]::UtcNow.ToString('o'))`nprofile=$ProfileName`n"
    $lockBytes = [Text.UTF8Encoding]::new($false).GetBytes($lockText)
    $profileLock.SetLength(0)
    $profileLock.Write($lockBytes, 0, $lockBytes.Length)
    $profileLock.Flush()
} catch [IO.IOException] {
    throw "Managed profile is already running: $ProfileName ($profileLockPath). Stop the existing profile before starting another one."
}

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

function Assert-PortAvailable([int]$Port, [string]$Name) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() } catch { throw "$Name port is unavailable: $Port" } finally { $listener.Stop() }
}

function Stop-OwnedProcessTree($process) {
    if (-not $process) { return }
    $rootId = $process.Id
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ParentProcessId -eq $rootId })
    foreach ($child in $children) {
        Stop-OwnedProcessTree (Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue)
    }
    $current = Get-Process -Id $rootId -ErrorAction SilentlyContinue
    if ($current) { Stop-Process -Id $rootId -Force -ErrorAction SilentlyContinue }
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
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "JAWL startup heartbeat did not complete within $TimeoutSeconds seconds; refusing to expose Companion as ready. Inspect $LogPath."
}

Assert-PortAvailable $JawlConsolePort 'JAWL console'
Assert-PortAvailable $ControlPort 'Companion control'
Assert-PortAvailable $PresentationPort 'Companion presentation'
if ($StartLocalAudio) {
    # Idempotent audio worker startup: if a healthy worker already owns the
    # port (leftover from a previous run or manual boot), reuse it instead of
    # failing the whole profile. This makes relaunch after a partial stop safe.
    $asrWorkerName = if ($AsrBackend -eq 'qwen') { 'Qwen3-ASR-0.6B' } else { 'whisper-ASR' }
    foreach ($audio in @(@{Name=$ttsWorkerName;Port=$ttsWorkerPort}, @{Name=$asrWorkerName;Port=$AsrPort})) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $audio.Port)
        try { $listener.Start(); $listener.Stop(); $free = $true } catch { $free = $false }
        if (-not $free) { Write-Host ("Reusing already-running {0} on port {1}." -f $audio.Name, $audio.Port) }
    }
}
if ($UseVoiceMem -and -not (Test-Path -LiteralPath $voicememPy -PathType Leaf)) { throw "VoiceMem runtime is missing: $voicememPy" }

$jawl = $null
$companion = $null
$tera = $null
$asr = $null
$sensory = $null
$supervisor = $null
try {
    $audioArgs = ''
    if ($StartLocalAudio) {
        if ($TtsProvider -eq 'voxcpm') {
            $audioResources = @($voxcpmPy, $voxcpmModelDir)
        } else {
            $audioResources = @($teraPy, $teraRelease)
        }
        if ($AsrBackend -eq 'qwen') {
            $audioResources += @($qwenAsrServer, $qwenAsrModel, $qwenAsrMmproj)
        } elseif ($AsrBackend -eq 'whisper') {
            $audioResources += @($asrPy, $asrServerScript, $whisperModel)
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
        $ttsAlready = $false
        $asrAlready = $false
        $asrWorkerName = if ($AsrBackend -eq 'qwen') { 'Qwen3-ASR-0.6B' } elseif ($AsrBackend -eq 'gigaam') { 'GigaAM-batch' } else { 'whisper-ASR' }
        $audioChecks = @(@{Name=$ttsWorkerName;Port=$ttsWorkerPort})
        if ($AsrBackend -ne 'gigaam') { $audioChecks += @{Name=$asrWorkerName;Port=$AsrPort} }
        foreach ($audio in $audioChecks) {
            $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $audio.Port)
            try { $probe.Start(); $probe.Stop(); $probeFree = $true } catch { $probeFree = $false }
            if (-not $probeFree) {
                if ($audio.Name -eq $ttsWorkerName) { $ttsAlready = $true } else { $asrAlready = $true }
            }
        }
        if (-not $ttsAlready) {
            if ($TtsProvider -eq 'voxcpm') {
                $voxArgs = "scripts\voxcpm_server.py --device cuda:0 --port $VoxCPMPort --threads 24 --inference-timesteps 10"
                if ($VoxCPMReferenceWav) { $voxArgs += " --reference-wav `"$VoxCPMReferenceWav`"" }
                $tera = New-RuntimeProcess $voxcpmPy $voxArgs $repo @{CUDA_VISIBLE_DEVICES = '1'} 'voxcpm-tts.log'
            } else {
                $tera = New-RuntimeProcess $teraPy "scripts\teratts_server.py --release-dir `"$teraRelease`" --voice ru_f1 --model distilled --threads 24 --host 127.0.0.1 --port $TtsPort" $repo @{} 'tera-tts.log'
            }
        }
        if (-not $asrAlready -and $AsrBackend -ne 'gigaam') {
            if ($AsrBackend -eq 'qwen') {
                $qwenArgs = "--model `"$qwenAsrModel`" --mmproj `"$qwenAsrMmproj`" --alias Qwen3-ASR-0.6B --host 127.0.0.1 --port $AsrPort --threads 12 --threads-batch 12 --ctx-size 4096 --parallel 1 --gpu-layers 0 --no-mmproj-offload"
                $asr = New-RuntimeProcess $qwenAsrServer $qwenArgs (Split-Path -Parent $qwenAsrServer) @{} 'qwen-asr.log'
            } else {
                $asr = New-RuntimeProcess $asrPy "scripts\asr_whisper_server.py --model `"$whisperModel`" --language ru --threads 12 --beam-size 5 --host 127.0.0.1 --port $AsrPort" $repo @{} 'whisper-asr.log'
            }
        }
        $audioDeadline = [DateTime]::UtcNow.AddSeconds(300)
        while ([DateTime]::UtcNow -lt $audioDeadline) {
            if ($tera -and $tera.HasExited) { throw "$ttsWorkerName exited during integrated startup." }
            if ($asr -and $asr.HasExited) { throw "$asrWorkerName exited during integrated startup." }
            try { $teraHealth = Invoke-RestMethod "http://127.0.0.1:$ttsWorkerPort/health" -TimeoutSec 2 } catch { $teraHealth = $null }
            try { $asrHealth = Invoke-RestMethod "http://127.0.0.1:$AsrPort/health" -TimeoutSec 2 } catch { $asrHealth = $null }
            if ($teraHealth.status -eq 'ok' -and ($AsrBackend -eq 'gigaam' -or $asrHealth.status -eq 'ok')) { break }
            Start-Sleep -Seconds 1
        }
        if ($teraHealth.status -ne 'ok') { throw 'Local TTS worker did not become healthy.' }
        if ($AsrBackend -ne 'gigaam' -and $asrHealth.status -ne 'ok') { throw 'Local ASR worker did not become healthy.' }
        if ($EnableSensoryWorker -and $SensoryFile) {
            $sensoryArgs = "scripts\sensory_worker.py --duration 0 --out `"$SensoryFile`""
            $sensory = New-RuntimeProcess $asrPy $sensoryArgs $repo @{} 'sensory.log'
        }
        $asrModelName = if ($AsrBackend -eq 'whisper') { 'whisper-turbo' } else { 'Qwen3-ASR-0.6B' }
        $audioArgs = " --asr-url http://127.0.0.1:$AsrPort/v1 --asr-model $asrModelName --tts-provider $TtsProvider --tts-url http://127.0.0.1:$ttsWorkerPort"
        if ($EnableProsodyPlanner -and $TtsProvider -eq 'tera') {
            $audioArgs += " --prosody-planner --prosody-url $ProsodyUrl --prosody-model $ProsodyModel"
        }
        if ($EnableStreamingAsr) {
            if (-not (Test-Path -LiteralPath $StreamingAsrExe -PathType Leaf)) { throw "Streaming ASR executable is missing: $StreamingAsrExe" }
            if (-not (Test-Path -LiteralPath $StreamingAsrModel -PathType Leaf)) { throw "Streaming ASR model is missing: $StreamingAsrModel" }
            $audioArgs += " --streaming-asr --streaming-asr-exe `"$StreamingAsrExe`" --streaming-asr-model `"$StreamingAsrModel`" --streaming-asr-backend gigaam"
        }
    }
    $jawlEnv = @{}
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
        $supervisor = New-RuntimeProcess $py "-m src.instances.supervisor --root `"$source`" --interval 1" $profileHome $supervisorEnv 'supervisor.log'
        $supervisorDeadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path -LiteralPath $supervisorPidPath) -and [DateTime]::UtcNow -lt $supervisorDeadline) {
            if ($supervisor.HasExited) { throw 'Native instance supervisor exited during startup.' }
            Start-Sleep -Milliseconds 100
        }
        if ($supervisor.HasExited -or -not (Test-Path -LiteralPath $supervisorPidPath)) { throw 'Native instance supervisor did not publish readiness.' }
    }
    $startupStartedAt = Get-Date
    $jawl = New-RuntimeProcess $py "-m src.web.server --host 127.0.0.1 --port $JawlConsolePort --no-browser --keep-agent" $profileHome $jawlEnv 'jawl-console.log'
    $consoleUrl = "http://127.0.0.1:$JawlConsolePort"
    $consoleHeaders = @{ 'X-Console-Token' = $env:CONSOLE_TOKEN }
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-RestMethod "$consoleUrl/api/agent/status" -Headers $consoleHeaders -TimeoutSec 2 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 1 }
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
    }
    $companionArgs = "-u -m jawl_voicecompanion --host 127.0.0.1 --port $ControlPort --presentation-host 127.0.0.1 --presentation-port $PresentationPort --jawl-port-file `"$portFile`" --jawl-web-url $consoleUrl --jawl-chat-timeout $JawlChatTimeoutSeconds --jawl-hostos-control$audioArgs"
    if (-not $NoLive2D) {
        $companionArgs += " --live2d-assets `"$(Join-Path $repo 'runtime\live2d')`" --live2d-model `"mao_pro/mao_pro.model3.json`" --live2d-runtime `"live2d-runtime.js`""
    }
    if ($UseVoiceMem) { $companionArgs += " --voicemem-python `"$voicememPy`" --voicemem-local-memory --voicemem-warmup text --voicemem-timeout 120" }
    if ($SensoryFile) {
        $companionArgs += " --ambient-memory --sensory-file `"$SensoryFile`""
        if ($AmbientTriageSeconds -gt 0) { $companionArgs += " --ambient-triage-interval $AmbientTriageSeconds" }
    }
    if ($EnableScreenWatch) {
        if (-not $JawlEventDir) { $JawlEventDir = Join-Path $profileHome 'sandbox\_system\instances\daily\.jawl_events' }
        New-Item -ItemType Directory -Force -Path $JawlEventDir | Out-Null
        $companionArgs += " --hostos-live --screen-enabled --vision-url $VisionUrl --vision-model $VisionModel --screen-watch --screen-watch-interval $ScreenWatchInterval --jawl-event-dir `"$JawlEventDir`""
        if ($HostosLevel -ge 0) { $companionArgs += " --hostos-level $HostosLevel" }
        else { $companionArgs += " --hostos-level 1" }
    } elseif ($HostosLevel -ge 0) {
        $companionArgs += " --hostos-level $HostosLevel"
    }
    $debugDump = @("PY=$py", "ARGS=$companionArgs") + @($companionEnv.GetEnumerator() | ForEach-Object { "ENV $($_.Key)=$($_.Value)" })
    [IO.File]::WriteAllLines((Join-Path $logDir 'companion-debug.txt'), $debugDump)
    $companion = New-RuntimeProcess $py $companionArgs $repo $companionEnv 'companion.log'
    $companionReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($companion.HasExited) { throw 'Companion exited during startup; inspect companion.log.' }
        try { $health = Invoke-RestMethod "http://127.0.0.1:$ControlPort/api/health" -TimeoutSec 2; if ($health.status -in @('ok', 'degraded')) { $companionReady = $true; break } } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $companionReady) { throw "Companion health did not become available on port $ControlPort." }
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
        $voiceArgs = @((Join-Path $repo 'scripts\run_browser_voice_e2e.py'), '--live', '--url', "http://127.0.0.1:$ControlPort", '--report', (Join-Path $repo 'runtime\browser-voice-e2e.json'), '--evidence-dir', (Join-Path $repo 'runtime\browser-evidence\voice'))
        for ($index = 0; $index -lt $BrowserVoiceWav.Count; $index++) {
            $voiceArgs += @('--wav', (Resolve-Path -LiteralPath $BrowserVoiceWav[$index]).Path, "--expected=$($BrowserVoiceExpected[$index])")
        }
        & $browserPy @voiceArgs
        if ($LASTEXITCODE -ne 0) { throw "Browser voice E2E failed with exit code $LASTEXITCODE." }
    }
    Write-Host 'Press Ctrl+C to stop the complete profile.'
    $startedAt = Get-Date
    while (-not $companion.HasExited -and -not $jawl.HasExited -and (-not $EnableSupervisor -or -not $supervisor.HasExited)) {
        if ($RunSeconds -gt 0 -and ((Get-Date) - $startedAt).TotalSeconds -ge $RunSeconds) { break }
        Start-Sleep -Seconds 1
    }
    if ($companion.HasExited) { throw 'Companion process exited unexpectedly.' }
} finally {
    try { Invoke-RestMethod "http://127.0.0.1:$JawlConsolePort/api/agent/stop" -Method Post -Headers $consoleHeaders -TimeoutSec 20 | Out-Null } catch { }
    if ($EnableSupervisor) {
        try { [IO.File]::WriteAllText($supervisorStopPath, "stop`n", [Text.UTF8Encoding]::new($false)) } catch { }
    }
    foreach ($process in @($companion, $jawl, $tera, $asr, $sensory, $supervisor)) {
        if ($process -and -not $process.HasExited) { $process.WaitForExit(25000) | Out-Null }
        if ($process -and -not $process.HasExited) { Stop-OwnedProcessTree $process; $process.WaitForExit(5000) | Out-Null }
        Save-RuntimeLog $process
    }
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
    if ($profileLock) { $profileLock.Dispose() }
}
