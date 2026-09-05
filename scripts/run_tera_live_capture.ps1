$ErrorActionPreference = 'Stop'
$serverPy = 'G:\AI\tts_env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $serverPy)) { throw 'Tera runtime missing' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$log = Join-Path $repo 'runtime\tts-tera-live.log'
$err = Join-Path $repo 'runtime\tts-tera-live.err'
$proc = Start-Process -FilePath $serverPy -WorkingDirectory $repo -ArgumentList @(
    'scripts\teratts_server.py', '--release-dir', 'G:\AI\tts_models\TeraSpace__TeraTTSv2',
    '--voice', 'ru_f1', '--model', 'distilled', '--threads', '24', '--host', '127.0.0.1', '--port', '9889'
) -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
try {
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        try { $health = Invoke-RestMethod 'http://127.0.0.1:9889/health' -TimeoutSec 2; if ($health.status -eq 'ok') { $ready = $true; break } } catch { }
        if ($proc.HasExited) { throw "Tera server exited: $($proc.ExitCode)" }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Tera server did not become ready' }
    & python (Join-Path $repo 'scripts\run_teratts_profile.py') --url http://127.0.0.1:9889 --requests 3 --allow-live-model --report (Join-Path $repo 'runtime\tera-live-profile.json')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; $proc.WaitForExit(5000) | Out-Null }
}
Get-Content (Join-Path $repo 'runtime\tera-live-profile.json')
