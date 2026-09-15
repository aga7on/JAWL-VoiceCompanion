param(
    [string]$PythonExe = 'G:\AI\VoxCPM\.venv\Scripts\python.exe',
    [string]$ModelDir = 'G:\AI\VoxCPM\models\models--openbmb--VoxCPM2\snapshots\32279effe8c19989596f05d353d1447f51d9e915',
    [string]$ReferenceWav = '',
    [int]$Port = 9891,
    [int]$Threads = 24,
    [int]$InferenceTimesteps = 10,
    [string]$Device = 'cuda:0',
    [string]$CudaVisibleDevices = '1'
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "VoxCPM Python executable was not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $ModelDir -PathType Container)) {
    throw "VoxCPM model directory was not found: $ModelDir"
}
if ($ReferenceWav -and -not (Test-Path -LiteralPath $ReferenceWav -PathType Leaf)) {
    throw "VoxCPM reference audio was not found: $ReferenceWav"
}
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535' }
if ($Threads -lt 1) { throw 'Threads must be positive' }
if ($InferenceTimesteps -lt 1 -or $InferenceTimesteps -gt 50) { throw 'InferenceTimesteps must be between 1 and 50' }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $ownerName = if ($owner) { $owner.ProcessName } else { 'unknown process' }
    throw "VoxCPM port $Port is already used by $ownerName (PID $($listener.OwningProcess)). Choose another -Port."
}

$env:CUDA_VISIBLE_DEVICES = $CudaVisibleDevices
$script = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\voxcpm_server.py'
$arguments = @(
    $script, '--model-dir', $ModelDir, '--device', $Device,
    '--port', $Port, '--threads', $Threads, '--inference-timesteps', $InferenceTimesteps
)
if ($ReferenceWav) { $arguments += @('--reference-wav', $ReferenceWav) }
& $PythonExe @arguments
exit $LASTEXITCODE
