$ErrorActionPreference = 'Stop'

$companionRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $companionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw 'Python 3.10+ was not found.'
    }
    $pythonExe = $pythonCommand.Source
}

$distRoot = Join-Path $companionRoot 'dist'
$wheelRoot = Join-Path $distRoot 'wheel'
New-Item -ItemType Directory -Force -Path $wheelRoot | Out-Null

# Set a stable archive epoch. Setuptools/wheel otherwise copies source and
# build timestamps into ZIP metadata, making identical source trees produce
# different hashes. Respect an operator-provided value when present.
$hadSourceDateEpoch = Test-Path Env:SOURCE_DATE_EPOCH
$previousSourceDateEpoch = $env:SOURCE_DATE_EPOCH
if (-not $hadSourceDateEpoch) {
    $env:SOURCE_DATE_EPOCH = '946684800' # 2000-01-01T00:00:00Z
}

Push-Location $companionRoot
try {
    & $pythonExe -m pip wheel . --no-deps --wheel-dir $wheelRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Wheel build failed with exit code $LASTEXITCODE."
    }

    $wheels = @(Get-ChildItem -LiteralPath $wheelRoot -Filter '*.whl' -File)
    if ($wheels.Count -eq 0) {
        throw 'Wheel build produced no artifact.'
    }
    $manifestPath = Join-Path $distRoot 'SHA256SUMS.txt'
    $lines = foreach ($wheel in $wheels) {
        $hash = (Get-FileHash -LiteralPath $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  wheel/$($wheel.Name)"
    }
    [System.IO.File]::WriteAllLines($manifestPath, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "PASS wheel artifacts: $wheelRoot"
    Write-Host "PASS hash manifest: $manifestPath"
} finally {
    Pop-Location
    if ($hadSourceDateEpoch) {
        $env:SOURCE_DATE_EPOCH = $previousSourceDateEpoch
    } else {
        Remove-Item Env:SOURCE_DATE_EPOCH -ErrorAction SilentlyContinue
    }
}
