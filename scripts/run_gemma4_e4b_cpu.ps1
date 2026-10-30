param(
    [ValidateSet('q2','q4')]
    [string]$Quant = 'q2',
    [int]$Threads = 6,
    [int]$ThreadsBatch = 6,
    [int]$RunSeconds = 0,
    [int]$MaxTokens = 160,
    [string]$TargetTitle = 'YouTube',
    [switch]$Probe,
    [switch]$Live,
    [switch]$VerifySha,
    [string]$Out = ''
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configPath = Join-Path $repo 'config\gemma4-e4b-cpu.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$modelInfo = $config.models.$Quant
$root = $config.llama_cpp.root
$serverExe = Join-Path $root 'llama-server.exe'
if (-not (Test-Path -LiteralPath $serverExe)) { throw "llama-server is missing: $serverExe" }
foreach ($item in @(
    @{ Path = $modelInfo.file; Bytes = [int64]$modelInfo.bytes; Name = 'model' },
    @{ Path = $modelInfo.mmproj; Bytes = [int64]$modelInfo.mmproj_bytes; Name = 'mmproj' }
)) {
    if (-not (Test-Path -LiteralPath $item.Path)) { throw "$($item.Name) is missing: $($item.Path)" }
    $actual = (Get-Item -LiteralPath $item.Path).Length
    if ($actual -ne $item.Bytes) {
        throw "$($item.Name) is incomplete: $actual / $($item.Bytes) bytes. Finish the download first."
    }
    if ($VerifySha) {
        $expected = if ($item.Name -eq 'model') { $modelInfo.sha256 } else { $modelInfo.mmproj_sha256 }
        $actualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $item.Path).Hash.ToLower()
        if ($actualSha -ne $expected) { throw "$($item.Name) SHA256 mismatch: $actualSha" }
    }
}
$port = if ($Quant -eq 'q2') { [int]$config.server.port_q2 } else { [int]$config.server.port_q4 }
$logDir = Join-Path $repo 'runtime\gemma4-e4b-cpu\logs'
$outDir = Join-Path $repo 'runtime\gemma4-e4b-cpu\out'
New-Item -ItemType Directory -Force -Path $logDir,$outDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $logDir "server-$Quant-$Threads-$stamp.log"
$errLog = Join-Path $logDir "server-$Quant-$Threads-$stamp.err.log"
$serverArgs = @(
    '-m', $modelInfo.file,
    '--mmproj', $modelInfo.mmproj,
    '-c', [string]$config.server.context,
    '-ngl', '0',
    '--no-mmproj-offload',
    '-np', '1',
    '--threads', [string]$Threads,
    '--threads-batch', [string]$ThreadsBatch,
    '--host', $config.server.host,
    '--port', [string]$port,
    '--alias', 'gemma4-e4b',
    '--jinja',
    '--reasoning', 'off',
    '--metrics'
)
Write-Host "Starting Gemma 4 E4B CPU describer q=$Quant threads=$Threads/$ThreadsBatch port=$port"
$nvidiaBefore = (& nvidia-smi --query-gpu=index,memory.used --format=csv,noheader 2>$null) -join '; '
$process = Start-Process -FilePath $serverExe -ArgumentList $serverArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $errLog -PassThru
try {
    $deadline = (Get-Date).AddSeconds(240)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { throw "Gemma server exited; see $errLog" }
        try {
            $health = Invoke-RestMethod -Uri "http://$($config.server.host):$port/health" -TimeoutSec 3
            if ($health.status -in @('ok','ready')) { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "Gemma server health did not become ready; see $log" }
    $nvidiaAfter = (& nvidia-smi --query-gpu=index,memory.used --format=csv,noheader 2>$null) -join '; '
    Write-Host "Gemma ready. CPU-only flags: -ngl 0 --no-mmproj-offload. GPU before=$nvidiaBefore after=$nvidiaAfter"
    $metricsPath = Join-Path $outDir "server-metrics-$Quant-$Threads-$stamp.json"
    function Save-GemmaMetrics { try { $p = Get-Process -Id $process.Id -ErrorAction Stop; [pscustomobject]@{ quant=$Quant; threads=$Threads; threads_batch=$ThreadsBatch; working_set_mb=[math]::Round($p.WorkingSet64/1MB,1); private_mb=[math]::Round($p.PrivateMemorySize64/1MB,1); cpu_seconds=[math]::Round($p.TotalProcessorTime.TotalSeconds,1); gpu_before=$nvidiaBefore; gpu_after=$nvidiaAfter } | ConvertTo-Json | Set-Content -LiteralPath $metricsPath -Encoding UTF8 } catch { } }
    Save-GemmaMetrics
    $probeArgs = @(
        (Join-Path $repo 'scripts\gemma4_e4b_cpu_probe.py'),
        '--server-url', "http://$($config.server.host):$port",
        '--model', 'gemma4-e4b',
        '--quant', $Quant,
        '--timeout', '180',
        '--max-tokens', [string]$MaxTokens
    )
    if ($Probe) {
        $probeArgs += @('--case', 'all', '--runs', '1', '--out', (Join-Path $outDir "probe-$Quant-$Threads.json"))
    }
    if ($Live) {
        $probeArgs += @('--live', '--duration', [string]$(if ($RunSeconds -gt 0) { $RunSeconds } else { 900 }), '--target-title', $TargetTitle)
    }
    if ($Probe -or $Live -or $RunSeconds -gt 0) {
        & (Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe') @probeArgs
        if ($LASTEXITCODE -ne 0) { throw "Gemma probe failed with exit code $LASTEXITCODE" }
    }
    Save-GemmaMetrics
}
finally {
    if (Get-Command Save-GemmaMetrics -ErrorAction SilentlyContinue) { Save-GemmaMetrics }
    if ($process -and -not $process.HasExited) {
        try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch { }
        Start-Sleep -Seconds 2
        try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch { }
    }
}
