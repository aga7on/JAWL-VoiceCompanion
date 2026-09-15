$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$teraPy = 'G:\AI\tts_env\Scripts\python.exe'
$asrServer = 'G:\AI\VLM-RealTime-Bench\runtime\llama-b10738-cpu\llama-server.exe'
$asrModel = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\Qwen3-ASR-0.6B-Q8_0.gguf'
$asrMmproj = 'G:\AI\VLM-RealTime-Bench\models\qwen3-asr\mmproj-Qwen3-ASR-0.6B-Q8_0.gguf'
foreach ($path in @($teraPy, $asrServer, $asrModel, $asrMmproj)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required local model resource missing: $path" } }
$fixtureDir = Join-Path $repo 'runtime\synthetic-questions'
New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null
$teraOut = Join-Path $repo 'runtime\synthetic-questions-tera.log'
$teraErr = Join-Path $repo 'runtime\synthetic-questions-tera.err'
$teraVoice = 'ru_f1'
$tera = Start-Process -FilePath $teraPy -WorkingDirectory $repo -ArgumentList @('scripts\teratts_server.py','--release-dir','G:\AI\tts_models\TeraSpace__TeraTTSv2','--voice',$teraVoice,'--model','distilled','--threads','24','--host','127.0.0.1','--port','9889') -PassThru -WindowStyle Hidden -RedirectStandardOutput $teraOut -RedirectStandardError $teraErr
# Windows PowerShell 5.1 may decode UTF-8 source as ANSI; build the authoritative
# Russian utterances from Unicode code points so the live test is language-correct.
$questions = @(
    (-join ([char[]](0x041A,0x0430,0x043A,0x043E,0x0439,0x0020,0x0441,0x0435,0x0433,0x043E,0x0434,0x043D,0x044F,0x0020,0x0441,0x0442,0x0430,0x0442,0x0443,0x0441,0x0020,0x043C,0x043E,0x0435,0x0433,0x043E,0x0020,0x043F,0x0440,0x043E,0x0435,0x043A,0x0442,0x0430,0x003F))),
    (-join ([char[]](0x0417,0x0430,0x043F,0x043E,0x043C,0x043D,0x0438,0x002C,0x0020,0x043F,0x043E,0x0436,0x0430,0x043B,0x0443,0x0439,0x0441,0x0442,0x0430,0x002C,0x0020,0x0447,0x0442,0x043E,0x0020,0x044F,0x0020,0x043F,0x0440,0x0435,0x0434,0x043F,0x043E,0x0447,0x0438,0x0442,0x0430,0x044E,0x0020,0x043A,0x043E,0x0440,0x043E,0x0442,0x043A,0x0438,0x0435,0x0020,0x043E,0x0442,0x0432,0x0435,0x0442,0x044B,0x002E))),
    (-join ([char[]](0x0421,0x043C,0x043E,0x0436,0x0435,0x0448,0x044C,0x0020,0x043F,0x0440,0x043E,0x0432,0x0435,0x0440,0x0438,0x0442,0x044C,0x0020,0x0442,0x0435,0x0441,0x0442,0x043E,0x0432,0x044B,0x0439,0x0020,0x0444,0x0430,0x0439,0x043B,0x0020,0x0438,0x0020,0x0441,0x043E,0x043E,0x0431,0x0449,0x0438,0x0442,0x044C,0x0020,0x0440,0x0435,0x0437,0x0443,0x043B,0x044C,0x0442,0x0430,0x0442,0x003F)))
)
<#
$questions = @(
    'Какой сегодня статус моего проекта?',
    'Запомни, пожалуйста, что я предпочитаю короткие ответы.',
    'Сможешь проверить тестовый файл и сообщить результат?'
)
#>
try {
    $ready = $false
    for ($i=0; $i -lt 90; $i++) { try { $h=Invoke-RestMethod 'http://127.0.0.1:9889/health' -TimeoutSec 2; if($h.status -eq 'ok'){$ready=$true;break} } catch{}; if($tera.HasExited){throw "Tera exited: $($tera.ExitCode)"}; Start-Sleep 1 }
    if(-not $ready){throw 'Tera did not become ready'}
    for($i=0;$i -lt $questions.Count;$i++){
        $payload = @{text=$questions[$i];voice=$teraVoice;speed=1.0} | ConvertTo-Json -Compress
        $target = Join-Path $fixtureDir ("question-{0:00}.wav" -f ($i+1))
        $payloadBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        Invoke-WebRequest -Uri 'http://127.0.0.1:9889/tts' -Method Post -ContentType 'application/json; charset=utf-8' -Body $payloadBytes -TimeoutSec 120 -OutFile $target
    }
} finally { if(-not $tera.HasExited){Stop-Process -Id $tera.Id -Force -ErrorAction SilentlyContinue;$tera.WaitForExit(5000)|Out-Null} }
$asrOut = Join-Path $repo 'runtime\synthetic-questions-asr.log'
$asrErr = Join-Path $repo 'runtime\synthetic-questions-asr.err'
$asrArgs=@('--model',$asrModel,'--mmproj',$asrMmproj,'--alias','Qwen3-ASR-0.6B','--host','127.0.0.1','--port','8984','--threads','12','--threads-batch','12','--ctx-size','4096','--parallel','1','--gpu-layers','0','--no-mmproj-offload')
$asr = Start-Process -FilePath $asrServer -WorkingDirectory (Split-Path -Parent $asrServer) -ArgumentList $asrArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $asrOut -RedirectStandardError $asrErr
try {
    $ready=$false
    for($i=0;$i -lt 180;$i++){try{$h=Invoke-RestMethod 'http://127.0.0.1:8984/health' -TimeoutSec 2;if($h.status -in @('ok','no slot available')){$ready=$true;break}}catch{};if($asr.HasExited){throw "ASR exited: $($asr.ExitCode)"};Start-Sleep 1}
    if(-not $ready){throw 'ASR did not become ready'}
    $wav=@(Get-ChildItem $fixtureDir -Filter 'question-*.wav' -File | Sort-Object Name | Select-Object -ExpandProperty FullName)
    & python (Join-Path $repo 'scripts\run_asr_profile.py') --url http://127.0.0.1:8984/v1 --model Qwen3-ASR-0.6B --allow-live-model --report (Join-Path $repo 'runtime\synthetic-questions-profile.json') @($wav | ForEach-Object { @('--wav', $_) })
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
} finally { if(-not $asr.HasExited){Stop-Process -Id $asr.Id -Force -ErrorAction SilentlyContinue;$asr.WaitForExit(5000)|Out-Null} }
Get-Content (Join-Path $repo 'runtime\synthetic-questions-profile.json')
