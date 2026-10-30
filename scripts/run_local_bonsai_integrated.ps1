param(
    [int]$RunSeconds,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')]
    [string]$ProfileName,
    [switch]$NoBrowser,
    [switch]$NoLocalAudio,
    [switch]$SyncProfile,
    [switch]$StartDesktopShell,
    [string]$ReportPath = '',
    [string]$BrainLogPath = '',
    [int]$JawlConsolePort,
    [int]$ControlPort,
    # ADR-052: accepted as a no-op for older callers - single origin now.
    [int]$PresentationPort,
    [int]$TtsPort,
    [ValidateSet('tera', 'omnivoice', 'voxcpm')]
    [string]$TtsProvider,
    [switch]$NoStreamingAsr,
    [string]$OmniVoiceRefWav = 'G:\AI\JAWL-VoiceCompanion\runtime\models\asr\voice_ref_aleksandra.wav',
    [string]$OmniVoiceRefText = (-join ([char[]](0x421,0x43d,0x430,0x447,0x430,0x43b,0x430,0x20,0x43f,0x43e,0x434,0x433,0x43e,0x442,0x43e,0x432,0x44c,0x441,0x44f,0x2e,0x20,0x41f,0x43e,0x43a,0x430,0x436,0x438,0x2c,0x20,0x447,0x435,0x433,0x43e,0x20,0x442,0x44b,0x20,0x441,0x442,0x43e,0x438,0x448,0x44c,0x2e,0x20,0x412,0x20,0x442,0x430,0x43a,0x43e,0x43c,0x20,0x432,0x438,0x434,0x435,0x20,0x443,0x20,0x442,0x435,0x431,0x44f,0x20,0x43d,0x435,0x442,0x20,0x448,0x430,0x43d,0x441,0x43e,0x432,0x20,0x43f,0x440,0x43e,0x442,0x438,0x432,0x20,0x434,0x435,0x43c,0x43e,0x43d,0x43e,0x432,0x2e,0x20,0x41d,0x435,0x43f,0x43b,0x43e,0x445,0x43e,0x2e,0x20,0x41d,0x43e,0x20,0x43f,0x440,0x435,0x43a,0x440,0x430,0x441,0x43d,0x44b,0x439,0x20,0x43f,0x440,0x438,0x43d,0x446,0x2e))),
    [switch]$RunBrowserVoiceE2E,
    [switch]$EnableAmbientAudio,
    [switch]$StartAmbientAudio,
    [string]$AmbientAudioDevice = '',
    [ValidateSet('eg2', 'qwen-omni')]
    [string]$AudioDescriber = 'eg2',
    [string]$AudioDescriberUrl = '',
    [string]$AudioDescriberModel = 'local-qwen3-omni',
    [switch]$EnableScreenWatch,
    [switch]$EnableScreenOcr,
    [switch]$Eg2Vision,
    [string]$Model,
    [string]$ModelAlias,
    [int]$BrainPort,
    [string]$BrainUrl,
    [string]$BrainServer,
    [string]$BrainTransformersServerScript = '',
    [string]$BrainTransformersPython = '',
    [int]$BrainThreads,
    [int]$BrainContextSize,
    [int]$BrainMaxOutputTokens,
    [int]$BrainGpuLayers,
    [string]$BrainDevice,
    [ValidateSet('off', 'auto', 'on')]
    [string]$BrainReasoningMode = 'off',
    [string]$BrainMmproj = '',
    [string]$VisionUrl,
    [string]$VisionModel,
    [ValidateSet('eg2', 'qwen')]
    [string]$VisualDescriber = 'eg2',
    [string]$VisualDescriberUrl = '',
    [string]$VisualDescriberModel = 'qwen3.5-0.8b',
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
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
if ($StartAmbientAudio -and -not $EnableAmbientAudio) { throw '-StartAmbientAudio requires -EnableAmbientAudio.' }
$env:PYTHONDONTWRITEBYTECODE = '1'
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
    $brain = $Manifest.brain
    $models = $Manifest.models
    $ports = $Manifest.ports
    $launch = $Manifest.launch
    $vision = $Manifest.vision
    $values = @{
        RunSeconds = $launch.run_seconds
        ProfileName = $Manifest.profile
        JawlConsolePort = $ports.jawl_console
        ControlPort = $ports.control
        TtsPort = $ports.tera_tts
        TtsProvider = $launch.tts_provider
        Model = $models.bonsai_model
        ModelAlias = $brain.model
        BrainPort = $ports.brain_port
        BrainUrl = $brain.llm_url
        BrainServer = $models.brain_server_exe
        BrainThreads = $brain.threads
        BrainContextSize = $brain.context_size
        BrainMaxOutputTokens = $brain.max_output_tokens
        BrainGpuLayers = $brain.gpu_layers
        BrainDevice = $brain.device
        VisionUrl = $vision.url
        VisionModel = $vision.model
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
if (-not $PSBoundParameters.ContainsKey('BrainUrl') -and $PSBoundParameters.ContainsKey('BrainPort')) {
    $brainUri = [UriBuilder]::new([Uri]$BrainUrl)
    $brainUri.Port = $BrainPort
    $BrainUrl = $brainUri.Uri.AbsoluteUri.TrimEnd('/')
}
$server = $BrainServer
$model = $Model
foreach ($resource in @('server', 'model')) {
    $value = Get-Variable -Name $resource -ValueOnly
    if (-not [IO.Path]::IsPathRooted($value)) { Set-Variable -Name $resource -Value (Join-Path $repo $value) }
}
function Get-BrainProbeUrls([string]$BaseUrl, [int]$Port) {
    $uri = [Uri]$BaseUrl
    if ($uri.Scheme -ne 'http' -or $uri.DnsSafeHost -notin @('127.0.0.1', 'localhost', '::1') -or
        $uri.Port -ne $Port -or $uri.AbsolutePath.TrimEnd('/') -ne '/v1' -or
        $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
        throw 'Brain URL must be a loopback /v1 URL whose port matches BrainPort.'
    }
    $origin = $uri.GetLeftPart([UriPartial]::Authority)
    return @{ HealthUrl = "$origin/health"; ModelsUrl = "$origin/v1/models" }
}
$probeUrls = Get-BrainProbeUrls $BrainUrl $BrainPort
$brainHealth = $probeUrls.HealthUrl
$brainModels = $probeUrls.ModelsUrl
$report = if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    Join-Path $repo 'runtime\local-bonsai-integrated-profile.json'
} elseif ([IO.Path]::IsPathRooted($ReportPath)) {
    [IO.Path]::GetFullPath($ReportPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repo $ReportPath))
}
$startedAt = [DateTime]::UtcNow
$integratedExitCode = $null
$status = 'failed'

function Test-BrainIdentity {
    param([string]$HealthUrl, [string]$ModelsUrl, [string]$ExpectedAlias)
    try {
        $health = Invoke-RestMethod $HealthUrl -TimeoutSec 2
        if ($health.status -ne 'ok') { return $false }
        $served = Invoke-RestMethod $ModelsUrl -TimeoutSec 2
        return @($served.data | Where-Object { $_.id -eq $ExpectedAlias }).Count -gt 0
    } catch { return $false }
}

function Assert-PortAvailable([int]$Port, [string]$Name) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() } catch { throw "$Name port is unavailable: $Port" } finally { $listener.Stop() }
}

function Assert-EffectivePorts([object[]]$Ports, [int[]]$ReservedPorts) {
    foreach ($entry in $Ports) {
        if ($entry.Port -lt 1 -or $entry.Port -gt 65535 -or $entry.Port -eq 8765 -or
            $ReservedPorts -contains $entry.Port) {
            throw ("{0} port is invalid or reserved: {1}" -f $entry.Name, $entry.Port)
        }
    }
    $duplicates = @($Ports | Group-Object { $_.Port } | Where-Object Count -gt 1)
    if ($duplicates.Count) { throw 'Brain, JAWL console, control, presentation and TTS ports must be distinct.' }
}

function Wait-BrainHealthy([int]$Seconds, [string]$ExpectedAlias) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-BrainIdentity $brainHealth $brainModels $ExpectedAlias) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

if (-not (Test-Path -LiteralPath $server -PathType Leaf)) { throw "Local Bonsai resource is missing: $server" }
if ($BrainTransformersServerScript) {
    if (-not (Test-Path -LiteralPath $model -PathType Container)) { throw "Local Transformers checkpoint directory is missing: $model" }
    if (-not (Test-Path -LiteralPath $BrainTransformersServerScript -PathType Leaf)) { throw "Transformers server script is missing: $BrainTransformersServerScript" }
    if (-not (Test-Path -LiteralPath $BrainTransformersPython -PathType Leaf)) { throw "Transformers Python executable is missing: $BrainTransformersPython" }
} elseif (-not (Test-Path -LiteralPath $model -PathType Leaf)) {
    throw "Local Bonsai resource is missing: $model"
}
$reservedPorts = @(8765) + @($runtimeManifest.ports.reserved)
$effectiveTtsPort = if ($TtsProvider -eq 'omnivoice') { 9890 } elseif ($TtsProvider -eq 'voxcpm') { 9891 } else { $TtsPort }
$effectivePorts = @(
    @{ Name = 'Brain'; Port = $BrainPort },
    @{ Name = 'JAWL console'; Port = $JawlConsolePort },
    @{ Name = 'Companion control'; Port = $ControlPort },
    @{ Name = 'TTS'; Port = $effectiveTtsPort }
)
if ($VisualDescriber -eq 'qwen' -and -not $VisualDescriberUrl) { $effectivePorts += @{ Name = 'Visual Qwen'; Port = $VisualDescriberPort } }
Assert-EffectivePorts $effectivePorts $reservedPorts
if ($RunSeconds -lt 0) { throw 'RunSeconds cannot be negative.' }
foreach ($setting in @(
    @{ Name = 'BrainThreads'; Value = $BrainThreads; Minimum = 1; Maximum = 128 },
    @{ Name = 'BrainContextSize'; Value = $BrainContextSize; Minimum = 512; Maximum = 1048576 },
    @{ Name = 'BrainMaxOutputTokens'; Value = $BrainMaxOutputTokens; Minimum = 1; Maximum = 65536 },
    @{ Name = 'BrainGpuLayers'; Value = $BrainGpuLayers; Minimum = 0; Maximum = 256 }
)) {
    if ($setting.Value -lt $setting.Minimum -or $setting.Value -gt $setting.Maximum) {
        throw ("{0} must be between {1} and {2}." -f $setting.Name, $setting.Minimum, $setting.Maximum)
    }
}
if ($BrainMaxOutputTokens -ge $BrainContextSize) { throw 'BrainMaxOutputTokens must be smaller than BrainContextSize.' }
# Fail on an existing listener before starting the holder, so a later profile
# port collision cannot leave an unowned brain worker behind.
Assert-PortAvailable $BrainPort 'Brain'
Assert-PortAvailable $JawlConsolePort 'JAWL console'
Assert-PortAvailable $ControlPort 'Companion control'
if ($VisualDescriber -eq 'qwen' -and -not $VisualDescriberUrl) {
    foreach ($path in @(
        (Join-Path $repo $VisualDescriberServerPath),
        (Join-Path $repo $VisualDescriberModelPath),
        (Join-Path $repo $VisualDescriberMmprojPath)
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Visual Qwen resource is missing: $path" }
    }
    Assert-PortAvailable $VisualDescriberPort 'Visual Qwen'
}

$holder = $null
try {
    if ([string]::IsNullOrWhiteSpace($BrainLogPath)) {
        $holderLog = Join-Path $repo 'runtime\supervised-brain-holder.log'
    } elseif ([IO.Path]::IsPathRooted($BrainLogPath)) {
        $holderLog = [IO.Path]::GetFullPath($BrainLogPath)
    } else {
        $holderLog = [IO.Path]::GetFullPath((Join-Path $repo $BrainLogPath))
    }
    $holderErrorLog = [IO.Path]::ChangeExtension($holderLog, '.err.log')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $holderLog) | Out-Null
    $holderArgs = @(
        '-X', 'utf8', ('"{0}"' -f (Join-Path $repo 'scripts\hold_supervised_brain.py')),
        '--port', [string]$BrainPort, '--llm-exe', ('"{0}"' -f $server), '--model', ('"{0}"' -f $model),
        '--alias', $ModelAlias, '--threads', [string]$BrainThreads,
        '--ctx-size', [string]$BrainContextSize, '--max-tokens', [string]$BrainMaxOutputTokens,
        '--gpu-layers', [string]$BrainGpuLayers, '--device', $BrainDevice, '--url', $BrainUrl,
        '--reasoning', $BrainReasoningMode
    )
    if ($BrainMmproj) { $holderArgs += @('--mmproj', ('"{0}"' -f $BrainMmproj)) }
    if ($BrainTransformersServerScript) {
        $holderArgs += @('--transformers-server-script', ('"{0}"' -f $BrainTransformersServerScript))
        if (-not $BrainTransformersPython) { throw '-BrainTransformersPython is required with -BrainTransformersServerScript.' }
        $holderArgs += @('--transformers-python', ('"{0}"' -f $BrainTransformersPython))
    }
    if ($PSBoundParameters.ContainsKey('ManifestPath')) { $holderArgs += @('--manifest', ('"{0}"' -f $ManifestPath)) }
    $holder = Start-Process -FilePath python -ArgumentList $holderArgs -WorkingDirectory $repo -PassThru -WindowStyle Hidden -RedirectStandardOutput $holderLog -RedirectStandardError $holderErrorLog
    if (-not (Wait-BrainHealthy 240 $ModelAlias)) {
        throw "Supervised brain did not become healthy and serve alias $ModelAlias (holder pid $($holder.Id))."
    }
    Write-Host "Supervised brain healthy on $BrainPort serving $ModelAlias (holder pid $($holder.Id))."
    $env:LLM_API_URL = $BrainUrl
    $env:JAWL_MODEL_OVERRIDE = $ModelAlias
    $env:LLM_MAX_OUTPUT_TOKENS = [string]$BrainMaxOutputTokens
    # The integrated launcher prepares and configures only the selected
    # profile, under its profile lock. Never pre-write the daily profile here.
    $integratedArgs = @(
        '-RunSeconds', [string]$RunSeconds,
        '-ProfileName', $ProfileName, '-JawlTemperatureOverride', '0.3', '-NativeContextWindowTokens', [string]$BrainContextSize,
        '-JawlConsolePort', [string]$JawlConsolePort, '-ControlPort', [string]$ControlPort,
        '-TtsPort', [string]$TtsPort,
        '-TtsProvider', $TtsProvider, '-VisionUrl', $VisionUrl, '-VisionModel', $VisionModel,
        # Do not expose the daily Companion while JAWL is still processing
        # SYSTEM_CORE_START; the first user turn must not queue behind startup.
        '-JawlModelOverride', $ModelAlias, '-StartupTimeoutSeconds', '600'
    )
    if (-not $NoLocalAudio) { $integratedArgs = @('-StartLocalAudio') + $integratedArgs }
    # System-audio perception uses the VoiceMem boundary even in a headless
    # profile. Keep it available without starting the local TTS worker when
    # the operator explicitly disabled local audio.
    if (-not $NoLocalAudio -or $EnableAmbientAudio) { $integratedArgs = @('-UseVoiceMem') + $integratedArgs }
    if ($NoBrowser) { $integratedArgs += '-NoBrowser' }
    if ($SyncProfile) { $integratedArgs += '-SyncProfile' }
    if ($StartDesktopShell) { $integratedArgs += '-StartDesktopShell' }
    if ($EnableAmbientAudio) {
        $integratedArgs += '-EnableAmbientAudio'
        if ($StartAmbientAudio) { $integratedArgs += '-StartAmbientAudio' }
        if (-not [string]::IsNullOrWhiteSpace($AmbientAudioDevice)) {
            $integratedArgs += @('-AmbientAudioDevice', $AmbientAudioDevice)
        }
        if ($AudioDescriber -eq 'qwen-omni') {
            if ([string]::IsNullOrWhiteSpace($AudioDescriberUrl)) { throw 'AudioDescriberUrl is required for qwen-omni.' }
            $integratedArgs += @('-AudioDescriber', 'qwen-omni', '-AudioDescriberUrl', $AudioDescriberUrl, '-AudioDescriberModel', $AudioDescriberModel)
        }
    }
    if ($EnableScreenWatch) { $integratedArgs += '-EnableScreenWatch' }
    if ($EnableScreenOcr) { $integratedArgs += '-EnableScreenOcr' }
    if ($Eg2Vision) { $integratedArgs += '-Eg2Vision' }
    if ($VisualDescriber -eq 'qwen') {
        $visualUrl = if ($VisualDescriberUrl) { $VisualDescriberUrl } else { "http://127.0.0.1:$VisualDescriberPort/v1" }
        $integratedArgs += @('-VisualDescriber', 'qwen', '-VisualDescriberUrl', $visualUrl, '-VisualDescriberModel', $VisualDescriberModel, '-VisualDescriberPort', [string]$VisualDescriberPort, '-VisualDescriberThreads', [string]$VisualDescriberThreads, '-VisualDescriberServerPath', $VisualDescriberServerPath, '-VisualDescriberModelPath', $VisualDescriberModelPath, '-VisualDescriberMmprojPath', $VisualDescriberMmprojPath, '-VisualDescriberRoi', $VisualDescriberRoi, '-VisualDescriberDisplayIndex', [string]$VisualDescriberDisplayIndex, '-VisualDescriberActiveInterval', [string]$VisualDescriberActiveInterval, '-VisualDescriberStaticInterval', [string]$VisualDescriberStaticInterval, '-VisualDescriberPeriodic', [string]$VisualDescriberPeriodic, '-VisualDescriberMaxAge', [string]$VisualDescriberMaxAge)
        if (-not $VisualDescriberUrl) { $integratedArgs += '-ManageVisualQwenServer' }
    }
    if ($TtsProvider -eq 'omnivoice') {
        if (-not (Test-Path -LiteralPath $OmniVoiceRefWav -PathType Leaf)) { throw "OmniVoice reference wav is missing: $OmniVoiceRefWav" }
        $integratedArgs += @('-OmniVoiceRefWav', $OmniVoiceRefWav, '-OmniVoiceRefText', $OmniVoiceRefText)
    }
    if (-not $NoStreamingAsr) { $integratedArgs += '-EnableStreamingAsr' }
    $integratedScript = Join-Path $repo 'scripts\run_integrated_profile.ps1'
    if ($PSBoundParameters.ContainsKey('ManifestPath')) { $integratedArgs += @('-ManifestPath', $ManifestPath) }
    if ($RunBrowserVoiceE2E) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $integratedScript @integratedArgs -RunBrowserVoiceE2E
    } else {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $integratedScript @integratedArgs
    }
    $integratedExitCode = $LASTEXITCODE
    if ($integratedExitCode -eq 0) { $status = 'passed' }
} finally {
    if ($holder -and -not $holder.HasExited) { try { $holder.Kill() } catch { } }
    if ($holder) { $holder.WaitForExit(10000) | Out-Null }
    $leaked = Test-BrainIdentity $brainHealth $brainModels $ModelAlias
    $endedAt = [DateTime]::UtcNow
    $payload = [ordered]@{
        schema_version = 1
        profile = $ProfileName
        launcher = 'local-bonsai-integrated'
        status = $status
        started_at = $startedAt.ToString('o')
        ended_at = $endedAt.ToString('o')
        integrated_exit_code = $integratedExitCode
        model = $model
        model_alias = $ModelAlias
        brain_context_size = $BrainContextSize
        brain_max_output_tokens = $BrainMaxOutputTokens
        llm_url = $BrainUrl
        brain_owned_by = 'supervised-holder'
        brain_leaked_after_run = $leaked
        ports = [ordered]@{ jawl_console = $JawlConsolePort; control = $ControlPort; brain = $BrainPort; tts = $effectiveTtsPort }
        components = @('owned-jawl', $VisionModel, 'gigaam-v3', $TtsProvider, 'voicemem')
        evidence_scope = 'startup-health-model-identity-shutdown only; no user-turn or browser-ASR acceptance'
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
}
if ($integratedExitCode -ne $null -and $integratedExitCode -ne 0) { exit $integratedExitCode }
