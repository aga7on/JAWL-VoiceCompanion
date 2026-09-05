param(
    [string]$ModelDir = 'G:\AI\tts_models\Qwen__Qwen3-TTS-12Hz-0.6B-Base',
    [string]$RefAudio = 'G:\AI\tts_inference\mita_ref_24k.wav',
    [string]$RefText = 'G:\AI\tts_inference\mita_ref_text.txt',
    [string]$Voice = 'mita',
    [switch]$XVectorOnly,
    [int]$Threads = 24,
    [int]$Port = 9890,
    [string]$PythonExe = 'G:\AI\tts_env\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'
foreach ($path in @($ModelDir, $RefAudio)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Qwen3-TTS file was not found: $path" }
}
if (-not $XVectorOnly -and -not (Test-Path -LiteralPath $RefText -PathType Leaf)) { throw "Qwen3-TTS reference text was not found: $RefText" }
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535' }
if ($Threads -lt 1) { throw 'Threads must be positive' }
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Qwen3-TTS Python runtime was not found: $PythonExe" }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) { throw "Qwen3-TTS port $Port is already in use by PID $($listener.OwningProcess)." }

$arguments = @(
    (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\qwen3_tts_server.py'),
    '--model-dir', $ModelDir, '--ref-audio', $RefAudio, '--ref-text', $RefText,
    '--voice', $Voice, '--threads', $Threads, '--port', $Port
)
if ($XVectorOnly) { $arguments += '--x-vector-only' }
& $PythonExe @arguments
exit $LASTEXITCODE
