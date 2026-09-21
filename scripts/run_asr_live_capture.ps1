# Live ASR capture over the fixed TTS sample WAVs.
# GigaAM (crispasr file mode) is the only ASR engine, so the capture runs the
# canonical harness scripts\gigaam_baseline_fixtures.py, which uses the
# project's own CrispASRFileTranscriber, and logs its per-file transcripts.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$log = Join-Path $repo 'runtime\asr-live.log'
$wav = @(
    'G:\AI\tts_samples\teratts-v2\welcome.wav',
    'G:\AI\tts_samples\teratts-v2\poem.wav',
    'G:\AI\tts_samples\qwen3-tts-0.6b\welcome.wav'
)
New-Item -ItemType Directory -Force -Path (Join-Path $repo 'runtime') | Out-Null
$asrOutput = & python -X utf8 (Join-Path $repo 'scripts\gigaam_baseline_fixtures.py') @wav
$asrCode = $LASTEXITCODE
$asrOutput | Set-Content -LiteralPath $log -Encoding UTF8
if ($asrCode -ne 0) { exit $asrCode }
Get-Content -LiteralPath $log
