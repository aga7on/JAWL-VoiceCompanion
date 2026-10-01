param(
    [int]$RunSeconds = 60,
    [int]$JawlConsolePort = 8870,
    [int]$ControlPort = 2467,
    [int]$PresentationPort = 8866,
    [int]$TtsPort = 9989,
    [switch]$RunBrowserVoiceE2E,
    # The default brain is Bonsai-2 27B Hikari (abliterated, owner-selected):
    # it replaces both the 2B big-pickle (which cannot emit JAWL's strict tool
    # JSON) and the old Bonsai-27B-Q1_0. Wired through the runtime manifest's
    # bonsai_model entry.
    [string]$Model = 'G:\AI\models\Ternary-Bonsai-2-27B-Abliterated-Hikari\Ternary-Bonsai-2-27B-Abliterated-PQ2_0.gguf',
    [string]$ModelAlias = 'local-bonsai2'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
# One executable entry (ADR-041 stage 2): the Companion process itself owns
# the brain worker via --supervise-workers (RuntimeSupervisor + Job Object
# KILL_ON_JOB_CLOSE), so this script no longer spawns llama-server by hand.
# The brain is Bonsai-2 27B Hikari (abliterated, owner-selected): it replaces
# both the 2B big-pickle (which cannot emit JAWL's strict tool JSON) and the
# old Bonsai-27B-Q1_0. The PQ2_0 ternary quant only loads in the prism
# build-fa server (taardis rejects it: "invalid ggml type 142"); the model
# sits wholly on GPU 1 (GPU 0 stays with vision/screen-watch).
$server = 'G:\AI\llamacpp-prism\build-fa\bin\llama-server.exe'
$model = $Model
$report = Join-Path $repo 'runtime\local-bonsai-integrated-profile.json'
$startedAt = [DateTime]::UtcNow
$integratedExitCode = $null
$status = 'failed'
foreach ($path in @($server, $model)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Local Bonsai resource is missing: $path" } }
# Health probe budget for the supervised brain (the launcher waits for the
# profile to come up; the supervisor itself enforces worker health).
$brainHealth = 'http://127.0.0.1:8990/health'
# The supervised brain is raised by a dedicated holder process (RuntimeSupervisor
# + Job Object KILL_ON_JOB_CLOSE) BEFORE the profile starts, so the JAWL agent's
# first heartbeat meets a live endpoint (observed: with in-process supervision
# Step 1 failed at +2.5 s while the 6.7 GB model was still loading onto GPU 1).
function Wait-BrainHealthy([int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try { $health = Invoke-RestMethod $brainHealth -TimeoutSec 2; if ($health.status -eq 'ok') { return $true } } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}
try {
    # Raise the brain holder first; it prints READY once /health answers.
    $holderLog = Join-Path $repo 'runtime\supervised-brain-holder.log'
    $holder = Start-Process -FilePath python -ArgumentList @('-X','utf8',(Join-Path $repo 'scripts\hold_supervised_brain.py'),'--port','8990','--llm-exe',"`"$server`"",'--model',"`"$model`"",'--alias',$ModelAlias) -WorkingDirectory $repo -PassThru -WindowStyle Hidden -RedirectStandardOutput $holderLog -RedirectStandardError (Join-Path $repo 'runtime\supervised-brain-holder.err')
    if (-not (Wait-BrainHealthy 240)) {
        throw "Supervised brain did not become healthy (holder pid $($holder.Id))."
    }
    Write-Host "Supervised brain healthy on 8990 (holder pid $($holder.Id))."
    $env:LLM_API_URL = 'http://127.0.0.1:8990/v1'
    # Point JAWL's main_model at the local Hikari alias so the ReAct engine
    # addresses the model the worker actually serves.
    $env:JAWL_MODEL_OVERRIDE = $ModelAlias
    # Owner decision 2026-10-01: cap the model's output (the "thinking") at
    # 2048 tokens. Overlong ReAct rambling (observed 3370 tokens) broke the
    # tool-JSON format; the delivery prompt wants ~40 words of inner text.
    $env:LLM_MAX_OUTPUT_TOKENS = '2048'
    # Low temperature for strict tool-JSON adherence: at 1.0 the model's
    # format compliance on the 10k ReAct context is stochastic (a turn
    # succeeded, the next one emitted Invalid JSON). 0.3 trades creativity
    # the brain does not need for deterministic envelopes.
    $env:JAWL_TEMPERATURE_OVERRIDE = '0.3'
    $integratedArgs = @('-StartLocalAudio','-UseVoiceMem','-RunSeconds',$RunSeconds,'-JawlConsolePort',$JawlConsolePort,'-ControlPort',$ControlPort,'-PresentationPort',$PresentationPort,'-TtsPort',$TtsPort,
        # The brain worker loads 6.7 GB onto GPU 1; the first heartbeat cycle
        # can exceed the default 180 s budget.
        '-StartupTimeoutSeconds', 600,
        # The agent is legitimately "still thinking" when the console port is
        # already serving; treat that as ready instead of tearing the stack
        # down after a fixed wait.
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
    # Tear down the brain holder first: its supervisor stops the worker
    # cleanly; if the holder itself is already dead, the Job Object has
    # already reaped the worker (no orphans).
    if ($holder -and -not $holder.HasExited) { Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue }
    # The brain worker is owned by the holder's supervisor (Job Object
    # KILL_ON_JOB_CLOSE); after the profile tears down, verify nothing
    # leaked before reporting.
    Start-Sleep -Seconds 5
    $leaked = $false
    try { $null = Invoke-RestMethod $brainHealth -TimeoutSec 2; $leaked = $true } catch { }
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
        brain_owned_by = 'supervised-holder'
        brain_leaked_after_run = $leaked
        ports = [ordered]@{ jawl_console = $JawlConsolePort; control = $ControlPort; presentation = $PresentationPort; llm = 8990; tts = $TtsPort }
        components = @('owned-jawl', 'local-qwen3-vl-2b', 'gigaam-v3', 'TeraTTSv2', 'voicemem')
        evidence_scope = 'startup-health-shutdown only; no user-turn or browser-ASR acceptance'
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
}
if ($integratedExitCode -ne $null -and $integratedExitCode -ne 0) { exit $integratedExitCode }
