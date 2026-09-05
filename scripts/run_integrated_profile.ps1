param(
    [int]$JawlConsolePort = 8770,
    [int]$ControlPort = 2367,
    [int]$PresentationPort = 8766,
    [int]$RunSeconds = 0,
    [switch]$NoBrowser,
    [switch]$StartLocalAudio,
    [switch]$UseVoiceMem,
    [switch]$RunBrowserVoiceE2E,
    [string[]]$BrowserVoiceWav = @(),
    [int]$TtsPort = 9889,
    [int]$AsrPort = 8984
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'runtime\jawl-sources\jawl-20260905-daily-v1'
$py = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'
$browserPy = (Get-Command python -ErrorAction Stop).Source
$profileHome = Join-Path $repo 'runtime\instances\daily'
$logDir = Join-Path $profileHome 'logs\integrated'
$portFile = Join-Path $profileHome 'data\interfaces\host\terminal\terminal.port'
$teraPy = 'G:\AI\tts_env\Scripts\python.exe'
$teraRelease = 'G:\AI\tts_models\TeraSpace__TeraTTSv2'
$asrServer = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe'
$asrModel = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf'
$asrMmproj = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf'
$voicememPy = 'G:\AI\VoiceMem\.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $py)) { throw "Owned runtime Python is missing: $py" }
if (-not (Test-Path -LiteralPath $source)) { throw "Pinned JAWL source is missing: $source" }
& $py (Join-Path $repo 'scripts\prepare_daily_profile.py') | Out-Host
& $py (Join-Path $repo 'scripts\preflight_jawl_runtime.py') | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Owned JAWL profile preflight failed.' }

$env:JAWL_INSTANCE_ID = 'daily'
$env:JAWL_INSTANCE_HOME = $profileHome
$env:JAWL_DATA_DIR = Join-Path $profileHome 'data'
$env:JAWL_CONFIG_DIR = Join-Path $profileHome 'config'
$env:JAWL_LOG_DIR = Join-Path $profileHome 'logs'
$env:JAWL_PROMPT_DIR = Join-Path $profileHome 'prompts'
$env:JAWL_SANDBOX_DIR = Join-Path $profileHome 'sandbox'
$env:JAWL_ENV_FILE = Join-Path $profileHome '.env'
$env:JAWL_INSTANCES_ROOT = Join-Path $repo 'runtime\instances'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:LLM_API_URL) { $env:LLM_API_URL = 'https://opencode.ai/zen/v1' }
 $loopbackProvider = $env:LLM_API_URL -match '^https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)'
if (-not $env:LLM_API_KEY_1 -and $loopbackProvider) {
    # Local OpenAI-compatible workers do not authenticate. JAWL still expects
    # a non-empty key field, so use a process-local marker never sent remotely.
    $env:LLM_API_KEY_1 = 'local-loopback'
}
if (-not $env:LLM_API_KEY_1) {
    throw 'Live JAWL provider is not configured: set LLM_API_KEY_1 in the process environment. No credential is read or stored by this launcher.'
}
# The JAWL web console protects mutating control routes with a console token.
# Generate one for this owned process tree only; do not expose it in argv/logs.
if (-not $env:CONSOLE_TOKEN) { $env:CONSOLE_TOKEN = [Guid]::NewGuid().ToString('N') }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

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

Assert-PortAvailable $JawlConsolePort 'JAWL console'
Assert-PortAvailable $ControlPort 'Companion control'
Assert-PortAvailable $PresentationPort 'Companion presentation'
if ($StartLocalAudio) {
    Assert-PortAvailable $TtsPort 'TeraTTSv2'
    Assert-PortAvailable $AsrPort 'Qwen3-ASR'
}
if ($UseVoiceMem -and -not (Test-Path -LiteralPath $voicememPy -PathType Leaf)) { throw "VoiceMem runtime is missing: $voicememPy" }

$jawl = $null
$companion = $null
$tera = $null
$asr = $null
try {
    $audioArgs = ''
    if ($StartLocalAudio) {
        foreach ($path in @($teraPy, $teraRelease, $asrServer, $asrModel, $asrMmproj)) { if (-not (Test-Path -LiteralPath $path)) { throw "Local audio resource is missing: $path" } }
        $tera = New-RuntimeProcess $teraPy "scripts\teratts_server.py --release-dir `"$teraRelease`" --voice ru_f1 --model distilled --threads 24 --host 127.0.0.1 --port $TtsPort" $repo @{} 'tera-tts.log'
        $asr = New-RuntimeProcess $asrServer "--model `"$asrModel`" --mmproj `"$asrMmproj`" --alias Qwen3-ASR-0.6B --host 127.0.0.1 --port $AsrPort --threads 12 --threads-batch 12 --ctx-size 4096 --parallel 1 --gpu-layers 0 --no-mmproj-offload" (Split-Path -Parent $asrServer) @{} 'qwen3-asr.log'
        $audioDeadline = [DateTime]::UtcNow.AddSeconds(180)
        while ([DateTime]::UtcNow -lt $audioDeadline) {
            if ($tera.HasExited) { throw 'TeraTTSv2 exited during integrated startup.' }
            if ($asr.HasExited) { throw 'Qwen3-ASR exited during integrated startup.' }
            try { $teraHealth = Invoke-RestMethod "http://127.0.0.1:$TtsPort/health" -TimeoutSec 2 } catch { $teraHealth = $null }
            try { $asrHealth = Invoke-RestMethod "http://127.0.0.1:$AsrPort/health" -TimeoutSec 2 } catch { $asrHealth = $null }
            if ($teraHealth.status -eq 'ok' -and $asrHealth.status -in @('ok', 'no slot available')) { break }
            Start-Sleep -Seconds 1
        }
        if ($teraHealth.status -ne 'ok' -or $asrHealth.status -notin @('ok', 'no slot available')) { throw 'Local audio workers did not become healthy.' }
        $audioArgs = " --asr-url http://127.0.0.1:$AsrPort/v1 --asr-model Qwen3-ASR-0.6B --tts-url http://127.0.0.1:$TtsPort --tts-provider tera"
    }
    $jawlEnv = @{}
    foreach ($name in 'JAWL_INSTANCE_ID','JAWL_INSTANCE_HOME','JAWL_DATA_DIR','JAWL_CONFIG_DIR','JAWL_LOG_DIR','JAWL_PROMPT_DIR','JAWL_SANDBOX_DIR','JAWL_ENV_FILE','JAWL_INSTANCES_ROOT','PYTHONIOENCODING','LLM_API_URL','CONSOLE_TOKEN') { $jawlEnv[$name] = (Get-Item "Env:$name").Value }
    # Credentials cross the process boundary only through the environment;
    # they are never placed in command-line arguments or runtime logs.
    $jawlEnv['LLM_API_KEY_1'] = $env:LLM_API_KEY_1
    $jawl = New-RuntimeProcess $py "-m src.web.server --host 127.0.0.1 --port $JawlConsolePort --no-browser --keep-agent" $source $jawlEnv 'jawl-console.log'
    $consoleUrl = "http://127.0.0.1:$JawlConsolePort"
    $consoleHeaders = @{ 'X-Console-Token' = $env:CONSOLE_TOKEN }
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-RestMethod "$consoleUrl/api/agent/status" -Headers $consoleHeaders -TimeoutSec 2 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'JAWL console did not become ready.' }
    Invoke-RestMethod "$consoleUrl/api/agent/start" -Method Post -Headers $consoleHeaders -TimeoutSec 120 | Out-Host
    for ($i = 0; $i -lt 120; $i++) {
        if (Test-Path -LiteralPath $portFile) { break }
        if ($jawl.HasExited) { throw 'JAWL console exited while starting the agent.' }
        try {
            $agentStatus = Invoke-RestMethod "$consoleUrl/api/agent/status" -Headers $consoleHeaders -TimeoutSec 2
            if ($agentStatus.running -ne $true -and $agentStatus.starting -ne $true) {
                throw "JAWL agent failed to start; inspect $env:JAWL_LOG_DIR\startup\startup_error.log"
            }
        } catch [System.Management.Automation.RuntimeException] { throw }
        catch { }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Path -LiteralPath $portFile)) { throw "JAWL terminal port file was not ready: $portFile" }

    $companionEnv = @{
        PYTHONPATH = Join-Path $repo 'src'
        PYTHONIOENCODING = 'utf-8'
        JAWL_WEB_TOKEN = $env:CONSOLE_TOKEN
    }
    $companionArgs = "-m jawl_voicecompanion --host 127.0.0.1 --port $ControlPort --presentation-host 127.0.0.1 --presentation-port $PresentationPort --jawl-port-file `"$portFile`" --jawl-web-url $consoleUrl --jawl-hostos-control$audioArgs"
    if ($UseVoiceMem) { $companionArgs += " --voicemem-python `"$voicememPy`" --voicemem-local-memory --voicemem-warmup text" }
    $companion = New-RuntimeProcess $py $companionArgs $repo $companionEnv 'companion.log'
    $companionReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($companion.HasExited) { throw 'Companion exited during startup; inspect companion.log.' }
        try { $health = Invoke-RestMethod "http://127.0.0.1:$ControlPort/api/health" -TimeoutSec 2; if ($health.status -in @('ok', 'degraded')) { $companionReady = $true; break } } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $companionReady) { throw "Companion health did not become available on port $ControlPort." }
    Write-Host "Integrated profile ready: control=$ControlPort presentation=$PresentationPort jawl_console=$JawlConsolePort"
    if ($RunBrowserVoiceE2E) {
        if ($BrowserVoiceWav.Count -lt 3) {
            $BrowserVoiceWav = @(
                (Join-Path $repo 'runtime\synthetic-questions\question-01.wav'),
                (Join-Path $repo 'runtime\synthetic-questions\question-02.wav'),
                (Join-Path $repo 'runtime\synthetic-questions\question-03.wav')
            )
        }
        $voiceArgs = @((Join-Path $repo 'scripts\run_browser_voice_e2e.py'), '--live', '--url', "http://127.0.0.1:$ControlPort", '--report', (Join-Path $repo 'runtime\browser-voice-e2e.json'), '--evidence-dir', (Join-Path $repo 'runtime\browser-evidence\voice'))
        foreach ($wav in $BrowserVoiceWav) { $voiceArgs += @('--wav', (Resolve-Path -LiteralPath $wav).Path) }
        & $browserPy @voiceArgs
        if ($LASTEXITCODE -ne 0) { throw "Browser voice E2E failed with exit code $LASTEXITCODE." }
    }
    Write-Host 'Press Ctrl+C to stop the complete profile.'
    $startedAt = Get-Date
    while (-not $companion.HasExited -and -not $jawl.HasExited) {
        if ($RunSeconds -gt 0 -and ((Get-Date) - $startedAt).TotalSeconds -ge $RunSeconds) { break }
        Start-Sleep -Seconds 1
    }
    if ($companion.HasExited) { throw 'Companion process exited unexpectedly.' }
} finally {
    try { Invoke-RestMethod "http://127.0.0.1:$JawlConsolePort/api/agent/stop" -Method Post -Headers $consoleHeaders -TimeoutSec 20 | Out-Null } catch { }
    foreach ($process in @($companion, $jawl, $tera, $asr)) {
        if ($process -and -not $process.HasExited) { $process.WaitForExit(25000) | Out-Null }
        if ($process -and -not $process.HasExited) { Stop-OwnedProcessTree $process; $process.WaitForExit(5000) | Out-Null }
        Save-RuntimeLog $process
    }
}
