param(
    [int]$RunSeconds = 60,
    [int]$JawlConsolePort = 8870,
    [int]$ControlPort = 2467,
    [int]$PresentationPort = 8866,
    [int]$TtsPort = 9989,
    [int]$AsrPort = 9984,
    [switch]$RunBrowserVoiceE2E
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$server = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe'
$model = 'G:\AI\VLM-RealTime-Bench\models\Qwen3-VL-2B-Q4_K_M.gguf'
$report = Join-Path $repo 'runtime\local-bonsai-integrated-profile.json'
$startedAt = [DateTime]::UtcNow
$integratedExitCode = $null
$status = 'failed'
foreach ($path in @($server, $model)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Local Bonsai resource is missing: $path" } }
$out = Join-Path $repo 'runtime\local-bonsai-llm.log'
$err = Join-Path $repo 'runtime\local-bonsai-llm.err'
$llm = Start-Process -FilePath $server -WorkingDirectory (Split-Path -Parent $server) -ArgumentList @('--model',$model,'--alias','big-pickle','--host','127.0.0.1','--port','8990','--threads','12','--ctx-size','16384','--parallel','1','--gpu-layers','0') -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
try {
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        if ($llm.HasExited) { throw "Local Bonsai exited: $($llm.ExitCode)" }
        try { $health = Invoke-RestMethod 'http://127.0.0.1:8990/health' -TimeoutSec 2; if ($health.status -eq 'ok') { $ready = $true; break } } catch { }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Local Bonsai did not become healthy.' }
    $env:LLM_API_URL = 'http://127.0.0.1:8990/v1'
    $integratedArgs = @('-StartLocalAudio','-UseVoiceMem','-RunSeconds',$RunSeconds,'-JawlConsolePort',$JawlConsolePort,'-ControlPort',$ControlPort,'-PresentationPort',$PresentationPort,'-TtsPort',$TtsPort,'-AsrPort',$AsrPort)
    if ($RunBrowserVoiceE2E) {
        $voiceWavs = @((Join-Path $repo 'runtime\synthetic-questions\question-01.wav'), (Join-Path $repo 'runtime\synthetic-questions\question-02.wav'), (Join-Path $repo 'runtime\synthetic-questions\question-03.wav'))
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'scripts\run_integrated_profile.ps1') @integratedArgs -RunBrowserVoiceE2E -BrowserVoiceWav $voiceWavs
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
        components = @('owned-jawl', 'local-qwen3-vl-2b', 'qwen3-asr-0.6b', 'TeraTTSv2', 'voicemem')
        evidence_scope = 'startup-health-shutdown only; no user-turn or browser-ASR acceptance'
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
}
if ($integratedExitCode -ne $null -and $integratedExitCode -ne 0) { exit $integratedExitCode }
