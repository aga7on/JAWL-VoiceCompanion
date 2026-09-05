# Guarded live ASR profile over deterministic synthetic acoustic cases.
# Synthesizes one clean Russian utterance via TeraTTS (or reuses --source-wav),
# then runs make_synthetic_audio_cases.py to build slow/paused/quiet/noisy/
# phrase-end/consecutive variants and profiles them against a local llama-server
# Qwen3-ASR worker using the generated cases.json expectations (--expects).
param([string]$SourceWav = '')

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$teraPy = 'G:\AI\tts_env\Scripts\python.exe'
$asrServer = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe'
$asrModel = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf'
$asrMmproj = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf'
foreach ($path in @($teraPy, $asrServer, $asrModel, $asrMmproj)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required local model resource missing: $path" } }
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

$asrOut = Join-Path $runDir 'asr.log'
$asrErr = Join-Path $runDir 'asr.err'
$asrArgs=@('--model',$asrModel,'--mmproj',$asrMmproj,'--alias','Qwen3-ASR-0.6B','--host','127.0.0.1','--port','8984','--threads','12','--threads-batch','12','--ctx-size','4096','--parallel','1','--gpu-layers','0','--no-mmproj-offload')
$asr = Start-Process -FilePath $asrServer -WorkingDirectory (Split-Path -Parent $asrServer) -ArgumentList $asrArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $asrOut -RedirectStandardError $asrErr
try {
    $ready=$false
    for($i=0;$i -lt 180;$i++){try{$h=Invoke-RestMethod 'http://127.0.0.1:8984/health' -TimeoutSec 2;if($h.status -in @('ok','no slot available')){$ready=$true;break}}catch{};if($asr.HasExited){throw "ASR exited: $($asr.ExitCode)"};Start-Sleep 1}
    if(-not $ready){throw 'ASR did not become ready'}
    $wav=@(Get-ChildItem $casesDir -Filter '*.wav' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
    & python (Join-Path $repo 'scripts\run_asr_profile.py') --url http://127.0.0.1:8984/v1 --model Qwen3-ASR-0.6B --allow-live-model --expects (Join-Path $casesDir 'cases.json') --report (Join-Path $runDir 'synthetic-cases-profile.json') @($wav | ForEach-Object { @('--wav', $_) })
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
} finally { if(-not $asr.HasExited){Stop-Process -Id $asr.Id -Force -ErrorAction SilentlyContinue;$asr.WaitForExit(5000)|Out-Null} }
Get-Content (Join-Path $runDir 'synthetic-cases-profile.json')