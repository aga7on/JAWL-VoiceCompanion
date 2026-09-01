param(
    [string]$ServerPath = 'C:\Users\ARTEM\vlm-bench\llamacpp\llama-server.exe',
    [string]$ModelPath = 'C:\Users\ARTEM\vlm-bench\models\Qwen3-VL-2B-Q4_K_M.gguf',
    [string]$MmprojPath = 'C:\Users\ARTEM\vlm-bench\models\Qwen3-VL-2B-mmproj-F16.gguf',
    [int]$Port = 8983,
    [int]$Threads = 24,
    [int]$Context = 8192
)

$ErrorActionPreference = 'Stop'
foreach ($path in @($ServerPath, $ModelPath, $MmprojPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Vision file was not found: $path"
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
    throw "Vision port $Port is already used by $ownerName (PID $($listener.OwningProcess)). Choose another -Port."
}

$arguments = @(
    '--model', $ModelPath,
    '--mmproj', $MmprojPath,
    '--alias', 'Qwen3-VL-2B',
    '--host', '127.0.0.1',
    '--port', $Port,
    '--threads', $Threads,
    '--threads-batch', $Threads,
    '--ctx-size', $Context,
    '--parallel', 1,
    '--gpu-layers', 0,
    '--no-mmproj-offload',
    '--image-min-tokens', 1024
)

Write-Host "Starting CPU Vision endpoint: http://127.0.0.1:$Port/v1"
Write-Host "Model: $ModelPath"
& $ServerPath @arguments
exit $LASTEXITCODE
