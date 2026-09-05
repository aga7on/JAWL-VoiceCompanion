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
$presentationPort = Get-FreeLoopbackPort
while ($presentationPort -eq $controlPort) { $presentationPort = Get-FreeLoopbackPort }
$baseUrl = "http://127.0.0.1:$controlPort"
$presentationUrl = "http://127.0.0.1:$presentationPort/avatar?debug=1"
$tempRoot = Join-Path $companionRoot 'runtime\browser-render-smoke'
$evidenceRoot = Join-Path $companionRoot ("runtime\browser-evidence\" + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$serverOut = Join-Path $tempRoot 'server.stdout.log'
$serverErr = Join-Path $tempRoot 'server.stderr.log'
$controlDomPath = Join-Path $tempRoot 'control.dom.html'
$avatarDomPath = Join-Path $tempRoot 'avatar.dom.html'
$controlProfile = Join-Path $tempRoot 'control-profile'
$avatarProfile = Join-Path $tempRoot 'avatar-profile'
$controlScreenshot = Join-Path $evidenceRoot 'control.png'
$avatarScreenshot = Join-Path $evidenceRoot 'avatar.png'
$server = $null

try {
    $server = Start-Process -FilePath $pythonExe -WorkingDirectory $companionRoot -PassThru `
        -ArgumentList @('-m', 'jawl_voicecompanion', '--host', '127.0.0.1', '--port', "$controlPort", '--presentation-host', '127.0.0.1', '--presentation-port', "$presentationPort") `
        -WindowStyle Hidden -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
    Wait-Health $baseUrl $server
    $controlDom = Invoke-BrowserDump $browser "$baseUrl/" $controlDomPath $controlProfile $controlScreenshot
    $avatarDom = Invoke-BrowserDump $browser $presentationUrl $avatarDomPath $avatarProfile $avatarScreenshot
    foreach ($image in @($controlScreenshot, $avatarScreenshot)) {
        if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw "Browser screenshot was not created: $image" }
    }
    foreach ($marker in @('JAWL VoiceCompanion', 'id="mic-gate"', 'id="obs-url"', 'id="health"')) {
        if ($controlDom -notmatch [regex]::Escape($marker)) { throw "Control DOM marker missing: $marker" }
    }
    foreach ($marker in @('JAWL Avatar', 'id="surface"', 'id="avatar"', 'id="subtitle"')) {
        if ($avatarDom -notmatch [regex]::Escape($marker)) { throw "Avatar DOM marker missing: $marker" }
    }
    $result = [ordered]@{
        schema_version = 1
        profile = 'browser_render_smoke'
        status = 'passed'
        browser = Split-Path -Leaf $browser
        control_url = $baseUrl
        presentation_url = $presentationUrl
        evidence_dir = $evidenceRoot
        screenshots = @($controlScreenshot, $avatarScreenshot)
        checks = @('control_dom', 'avatar_dom', 'gate_ui', 'obs_url', 'health_ui', 'transparent_avatar_surface')
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
