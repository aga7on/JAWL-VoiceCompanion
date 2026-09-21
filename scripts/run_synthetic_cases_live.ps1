# Guarded live ASR capture over deterministic synthetic acoustic cases.
# Synthesizes one clean Russian utterance via TeraTTS (or reuses --source-wav),
# then runs make_synthetic_audio_cases.py to build slow/paused/quiet/noisy/
# phrase-end/consecutive variants and transcribes every generated case with the
# canonical GigaAM harness (crispasr file mode is the only ASR engine).
param([string]$SourceWav = '')

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$teraPy = 'G:\AI\tts_env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $teraPy -PathType Leaf)) { throw "Required local model resource missing: $teraPy" }
# The GigaAM harness checks its own crispasr executable and GGUF model paths and
# fails with a clear message if either is missing.
$runDir = Join-Path $repo 'runtime\synthetic-cases'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$tera = $null
try {
    if (-not $SourceWav) {
        # Windows PowerShell 5.1 may decode UTF-8 source as ANSI; synthesize the
        # authoritative Russian utterance from Unicode code points so the fixture
        # is language-correct. Sentence: "Какой сегодня статус моего проекта?"
        $sourceText = -join ([char[]](0x041A,0x0430,0x043A,0x043E,0x0439,0x0020,0x0441,0x0435,0x0433,0x043E,0x0434,0x043D,0x044F,0x0020,0x0441,0x0442,0x0430,0x0442,0x0443,0x0441,0x0020,0x043C,0x043E,0x0435,0x0433,0x043E,0x0020,0x043F,0x0440,0x043E,0x0435,0x043A,0x0442,0x0430,0x003F))
        $teraOut = Join-Path $runDir 'tera.log'
        $teraErr = Join-Path $runDir 'tera.err'
        $tera = Start-Process -FilePath $teraPy -WorkingDirectory $repo -ArgumentList @('scripts\teratts_server.py','--release-dir','G:\AI\tts_models\TeraSpace__TeraTTSv2','--voice','ru_f1','--model','distilled','--threads','24','--host','127.0.0.1','--port','9889') -PassThru -WindowStyle Hidden -RedirectStandardOutput $teraOut -RedirectStandardError $teraErr
        $ready = $false
        for ($i=0; $i -lt 90; $i++) { try { $h=Invoke-RestMethod 'http://127.0.0.1:9889/health' -TimeoutSec 2; if($h.status -eq 'ok'){$ready=$true;break} } catch{}; if($tera.HasExited){throw "Tera exited: $($tera.ExitCode)"}; Start-Sleep 1 }
        if(-not $ready){throw 'Tera did not become ready'}
        $sourceWavPath = Join-Path $runDir 'source.wav'
        $payload = @{text=$sourceText;voice='ru_f1';speed=1.0} | ConvertTo-Json -Compress
        Invoke-WebRequest -Uri 'http://127.0.0.1:9889/tts' -Method Post -ContentType 'application/json' -Body $payload -TimeoutSec 120 -OutFile $sourceWavPath
    } else {
        $sourceWavPath = (Resolve-Path $SourceWav).Path
        if(-not (Test-Path -LiteralPath $sourceWavPath -PathType Leaf)){throw "Source WAV missing: $sourceWavPath"}
    }
} finally { if($null -ne $tera -and -not $tera.HasExited){Stop-Process -Id $tera.Id -Force -ErrorAction SilentlyContinue;$tera.WaitForExit(5000)|Out-Null} }

$casesDir = Join-Path $runDir 'cases'
& python (Join-Path $repo 'scripts\make_synthetic_audio_cases.py') --wav $sourceWavPath --out $casesDir --seed 7
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}

$wav=@(Get-ChildItem $casesDir -Filter '*.wav' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
$asrLog = Join-Path $runDir 'asr.log'
$asrOutput = & python -X utf8 (Join-Path $repo 'scripts\gigaam_baseline_fixtures.py') @wav
$asrCode = $LASTEXITCODE
$asrOutput | Set-Content -LiteralPath $asrLog -Encoding UTF8
if($asrCode -ne 0){exit $asrCode}
Get-Content -LiteralPath $asrLog