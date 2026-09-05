$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$server = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe'
$model = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf'
$mmproj = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf'
foreach ($path in @($server, $model, $mmproj)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "ASR resource missing: $path" } }
$log = Join-Path $repo 'runtime\asr-live.log'
$err = Join-Path $repo 'runtime\asr-live.err'
$args = @('--model', $model, '--mmproj', $mmproj, '--alias', 'Qwen3-ASR-0.6B', '--host', '127.0.0.1', '--port', '8984', '--threads', '12', '--threads-batch', '12', '--ctx-size', '4096', '--parallel', '1', '--gpu-layers', '0', '--no-mmproj-offload')
$proc = Start-Process -FilePath $server -WorkingDirectory (Split-Path -Parent $server) -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
try {
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        try { $h = Invoke-RestMethod 'http://127.0.0.1:8984/health' -TimeoutSec 2; if ($h.status -in @('ok','no slot available')) { $ready = $true; break } } catch { }
        if ($proc.HasExited) { throw "ASR server exited: $($proc.ExitCode)" }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'ASR server did not become ready' }
    $wav = @(
        'G:\AI\tts_samples\teratts-v2\welcome.wav',
        'G:\AI\tts_samples\teratts-v2\poem.wav',
        'G:\AI\tts_samples\qwen3-tts-0.6b\welcome.wav'
    )
    & python (Join-Path $repo 'scripts\run_asr_profile.py') --url http://127.0.0.1:8984/v1 --model Qwen3-ASR-0.6B --allow-live-model --report (Join-Path $repo 'runtime\asr-live-profile.json') @($wav | ForEach-Object { @('--wav', $_) })
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; $proc.WaitForExit(5000) | Out-Null }
}
Get-Content (Join-Path $repo 'runtime\asr-live-profile.json')
