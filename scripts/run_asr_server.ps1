param(
    [string]$ServerPath = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe',
    [string]$ModelPath = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf',
    [string]$MmprojPath = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf',
    [int]$Port = 8984,
    [int]$Threads = 12,
    [int]$Context = 4096
)

$ErrorActionPreference = 'Stop'
foreach ($path in @($ServerPath, $ModelPath, $MmprojPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required ASR file was not found: $path"
    }
}
if ($Port -lt 1 -or $Port -gt 65535) { throw "Port must be between 1 and 65535" }
if ($Threads -lt 1) { throw "Threads must be positive" }
if ($Context -lt 1024) { throw "Context must be at least 1024" }

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $ownerName = if ($owner) { $owner.ProcessName } else { 'unknown process' }
    throw "ASR port $Port is already used by $ownerName (PID $($listener.OwningProcess)). Choose another -Port."
}

$arguments = @(
    '--model', $ModelPath,
    '--mmproj', $MmprojPath,
    '--alias', 'Qwen3-ASR-0.6B',
    '--host', '127.0.0.1',
    '--port', $Port,
    '--threads', $Threads,
    '--threads-batch', $Threads,
    '--ctx-size', $Context,
    '--parallel', 1,
    '--gpu-layers', 0,
    '--no-mmproj-offload'
)

Write-Host "Starting CPU ASR endpoint: http://127.0.0.1:$Port/v1"
Write-Host "Model: $ModelPath"
& $ServerPath @arguments
exit $LASTEXITCODE
