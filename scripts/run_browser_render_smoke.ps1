$ErrorActionPreference = 'Stop'

<#
  Dependency-light browser rendering smoke.
  It deliberately uses an installed Edge/Chrome binary instead of adding a
  Playwright dependency to the core package. Exit code 2 means no supported
  browser was found; that is an environment skip, not a product pass.
#>

$companionRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $companionRoot 'src'
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Python 3.10+ was not found.' }
    $pythonExe = $pythonCommand.Source
}

function Get-FreeLoopbackPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

function Wait-Health {
    param([string]$Url, [System.Diagnostics.Process]$Process)
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) { throw "Companion exited during startup ($($Process.ExitCode))." }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$Url/api/health" -TimeoutSec 1
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 100
    }
    throw "Companion health did not become available: $Url"
}

function Invoke-BrowserDump {
    param(
        [string]$Browser,
        [string]$Url,
        [string]$OutputPath,
        [string]$ProfilePath,
        [string]$ScreenshotPath
    )
    $arguments = @(
        '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--window-size=1440,1000',
        '--disable-extensions', '--disable-background-networking', '--virtual-time-budget=2500',
        "--user-data-dir=$ProfilePath", "--screenshot=$ScreenshotPath", '--dump-dom', $Url
    )
    $browserProcess = Start-Process -FilePath $Browser -ArgumentList $arguments -Wait -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput $OutputPath -RedirectStandardError "$OutputPath.err"
    if ($browserProcess.ExitCode -ne 0) {
        $errorText = if (Test-Path -LiteralPath "$OutputPath.err") { Get-Content -Raw -LiteralPath "$OutputPath.err" } else { '' }
        throw "Browser render failed for $Url (exit $($browserProcess.ExitCode)): $($errorText.Substring(0, [Math]::Min(400, $errorText.Length)))"
    }
    $dom = Get-Content -Raw -LiteralPath $OutputPath
    if ([string]::IsNullOrWhiteSpace($dom)) { throw "Browser returned an empty DOM for $Url." }
    return $dom
}

$browser = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $browser) {
    Write-Output '{"status":"skipped","reason":"no supported Edge/Chrome executable"}'
    exit 2
}

$controlPort = Get-FreeLoopbackPort
$baseUrl = "http://127.0.0.1:$controlPort"
# ADR-052: one origin - the app serves the panel and the ?mode=obs surface.
$obsUrl = "$baseUrl/app?mode=obs"
$tempRoot = Join-Path $companionRoot 'runtime\browser-render-smoke'
$evidenceRoot = Join-Path $companionRoot ("runtime\browser-evidence\" + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$serverOut = Join-Path $tempRoot 'server.stdout.log'
$serverErr = Join-Path $tempRoot 'server.stderr.log'
$controlDomPath = Join-Path $tempRoot 'control.dom.html'
$obsDomPath = Join-Path $tempRoot 'obs.dom.html'
$controlProfile = Join-Path $tempRoot 'control-profile'
$obsProfile = Join-Path $tempRoot 'obs-profile'
$controlScreenshot = Join-Path $evidenceRoot 'control.png'
$obsScreenshot = Join-Path $evidenceRoot 'obs.png'
$server = $null

try {
    $server = Start-Process -FilePath $pythonExe -WorkingDirectory $companionRoot -PassThru `
        -ArgumentList @('-m', 'jawl_voicecompanion', '--host', '127.0.0.1', '--port', "$controlPort") `
        -WindowStyle Hidden -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
    Wait-Health $baseUrl $server
    $controlDom = Invoke-BrowserDump $browser "$baseUrl/app" $controlDomPath $controlProfile $controlScreenshot
    $obsDom = Invoke-BrowserDump $browser $obsUrl $obsDomPath $obsProfile $obsScreenshot
    foreach ($image in @($controlScreenshot, $obsScreenshot)) {
        if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw "Browser screenshot was not created: $image" }
    }
    foreach ($marker in @('JAWL Companion', 'id="chat-log"', 'id="avatar-canvas"', 'id="settings-list"')) {
        if ($controlDom -notmatch [regex]::Escape($marker)) { throw "Control DOM marker missing: $marker" }
    }
    # The obs renderer keeps only the stage: app.js sets obs-mode + title.
    foreach ($marker in @('id="avatar-canvas"', 'obs-mode', 'JAWL Avatar')) {
        if ($obsDom -notmatch [regex]::Escape($marker)) { throw "OBS DOM marker missing: $marker" }
    }
    if ($obsDom -notmatch '<body[^>]*\bobs-mode\b') {
        throw 'OBS mode class was not applied to the rendered document.'
    }
    if ($obsDom -notmatch '(?s)body\.obs-mode nav\.rail,.*?body\.obs-mode div\.side,.*?\{\s*display:\s*none\s*!important;\s*\}') {
        throw 'OBS mode must hide the application chrome and chat/settings panel.'
    }
    $result = [ordered]@{
        schema_version = 1
        profile = 'browser_render_smoke'
        status = 'passed'
        browser = Split-Path -Leaf $browser
        control_url = $baseUrl
        obs_url = $obsUrl
        evidence_dir = $evidenceRoot
        screenshots = @($controlScreenshot, $obsScreenshot)
        checks = @('control_dom', 'obs_dom', 'app_markers', 'obs_mode_class', 'obs_hides_panel')
    }
    $result | ConvertTo-Json -Compress
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
        $server.WaitForExit(3000) | Out-Null
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
