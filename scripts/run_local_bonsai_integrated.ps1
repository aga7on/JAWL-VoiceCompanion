param(
    [int]$RunSeconds = 60,
    [int]$JawlConsolePort = 8870,
    [int]$ControlPort = 2467,
    [int]$PresentationPort = 8866,
    [int]$TtsPort = 9989,
    [switch]$RunBrowserVoiceE2E,
    # The default brain is the 27B GSQ model: the 2B big-pickle cannot emit
    # JAWL's strict tool JSON (every ReAct step failed with "Invalid JSON"
    # while the pipeline itself was fast). With response_format=json_object
    # the 27B passed 3/3 tool-JSON probes at 60-66 tok/s (see
    # runtime/brain-27b-tooljson-probe.json).
    [string]$Model = 'G:\AI\VLM-RealTime-Bench\models\gsq-rco\Qwen3.8-27B-GSQ-RCO-IQ2_S.gguf',
    [string]$ModelAlias = 'local-27b'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
# GPU-accelerated brain: the manifest's canonical llama-server
# (G:/AI/llamacpp-taardis, CUDA build - both RTX 5080s visible) replaces the
# CPU-only VLM-RealTime-Bench build, which cost ~33 s per ReAct step and made
# the interactive SLO unreachable. The model fits wholly on GPU 1 (GPU 0
# stays with vision/screen-watch).
$server = 'G:\AI\llamacpp-taardis\build\bin\llama-server.exe'
$model = $Model
$report = Join-Path $repo 'runtime\local-bonsai-integrated-profile.json'
$startedAt = [DateTime]::UtcNow
$integratedExitCode = $null
$status = 'failed'
foreach ($path in @($server, $model)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Local Bonsai resource is missing: $path" } }
$out = Join-Path $repo 'runtime\local-bonsai-llm.log'
$err = Join-Path $repo 'runtime\local-bonsai-llm.err'
$llm = Start-Process -FilePath $server -WorkingDirectory (Split-Path -Parent $server) -ArgumentList @('--model',$model,'--alias',$ModelAlias,'--host','127.0.0.1','--port','8990','--threads','12','--ctx-size','16384','--parallel','1','--gpu-layers','99','--device','CUDA1') -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
try {
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        if ($llm.HasExited) { throw "Local Bonsai exited: $($llm.ExitCode)" }
        try { $health = Invoke-RestMethod 'http://127.0.0.1:8990/health' -TimeoutSec 2; if ($health.status -eq 'ok') { $ready = $true; break } } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Local Bonsai did not become healthy.' }
    $env:LLM_API_URL = 'http://127.0.0.1:8990/v1'
    # Point JAWL's main_model at the local 27B alias so the ReAct engine
    # addresses the model the worker actually serves.
    $env:JAWL_MODEL_OVERRIDE = $ModelAlias
    $integratedArgs = @('-StartLocalAudio','-UseVoiceMem','-RunSeconds',$RunSeconds,'-JawlConsolePort',$JawlConsolePort,'-ControlPort',$ControlPort,'-PresentationPort',$PresentationPort,'-TtsPort',$TtsPort,
        # The local big-pickle LLM runs on CPU and needs ~33 s per ReAct step,
        # so the first heartbeat cycle can exceed the default 180 s budget.
        '-StartupTimeoutSeconds', 600,
        # With a CPU brain the agent is legitimately "still thinking" when the
        # console port is already serving; treat that as ready instead of
        # tearing the stack down after a fixed wait.
        '-AllowBusyStartup')
    if ($RunBrowserVoiceE2E) {
        # The integrated launcher fills its own canonical three-question WAV set
        # and semantic expectations when -BrowserVoiceWav is omitted; passing an
        # array through a powershell -File call collapses it into one string and
        # breaks parameter binding.
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts\run_integrated_profile.ps1') @integratedArgs -RunBrowserVoiceE2E
    } else {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts\run_integrated_profile.ps1') @integratedArgs
    }
    $integratedExitCode = $LASTEXITCODE
    if ($integratedExitCode -eq 0) { $status = 'passed' }
} finally {
    if (-not $llm.HasExited) { Stop-Process -Id $llm.Id -Force -ErrorAction SilentlyContinue; $llm.WaitForExit(5000) | Out-Null }
    $endedAt = [DateTime]::UtcNow
    $payload = [ordered]@{
        schema_version = 1
        profile = 'local-bonsai-integrated'
        status = $status
        started_at = $startedAt.ToString('o')
        ended_at = $endedAt.ToString('o')
        integrated_exit_code = $integratedExitCode
        model = $model
        llm_url = 'http://127.0.0.1:8990/v1'
        ports = [ordered]@{ jawl_console = $JawlConsolePort; control = $ControlPort; presentation = $PresentationPort; llm = 8990; asr = $AsrPort; tts = $TtsPort }
        components = @('owned-jawl', 'local-qwen3-vl-2b', 'gigaam-v3', 'TeraTTSv2', 'voicemem')
        evidence_scope = 'startup-health-shutdown only; no user-turn or browser-ASR acceptance'
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
}
if ($integratedExitCode -ne $null -and $integratedExitCode -ne 0) { exit $integratedExitCode }
