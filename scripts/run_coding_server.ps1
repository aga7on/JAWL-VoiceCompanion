# Bonsai-27B Q1 local coding/chat server (llama.cpp, GPU1).
# OpenAI-compatible endpoint for opencode / any OpenAI client.
param(
    [int]$Port = 8986,
    [int]$Ctx = 32768,
    [string]$Model = 'G:\AI\VLM-RealTime-Bench\models\bonsai-ternary\Bonsai-27B-Q1_0.gguf',
    [string]$Mmproj = 'G:\AI\VLM-RealTime-Bench\models\bonsai-ternary\Bonsai-27B-mmproj-Q8_0.gguf',
    [string]$ServerExe = 'G:\AI\llamacpp-taardis\build\bin\llama-server.exe'
)
$ErrorActionPreference = 'Stop'
foreach ($path in @($Model, $ServerExe)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing: $path" }
}
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) { throw "Port $Port is already in use (pid $($listener.OwningProcess))." }
$env:CUDA_VISIBLE_DEVICES = '1'
$argsList = @('--model', $Model, '--alias', 'bonsai', '--host', '127.0.0.1', '--port', [string]$Port,
              '--ctx-size', [string]$Ctx, '--threads', '8', '--no-mmproj-offload', '-ngl', '99', '--no-webui',
              '--reasoning', 'off')
if (Test-Path -LiteralPath $Mmproj -PathType Leaf) { $argsList += @('--mmproj', $Mmproj) }
& $ServerExe @argsList
exit $LASTEXITCODE
