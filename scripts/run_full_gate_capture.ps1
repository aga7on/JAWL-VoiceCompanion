param(
    [string]$RunId = $null
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $RunId) { $RunId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') }
$logRelative = "runtime/full-gate-$RunId.log"
$jsonRelative = "runtime/full-gate-$RunId.json"
$log = Join-Path $repo $logRelative
$json = Join-Path $repo $jsonRelative

Push-Location $repo
try {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\run_full_gate.ps1' *> $log
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
} finally {
    Pop-Location
}

$metadata = [ordered]@{
    schema_version = 1
    run_id = $RunId
    exit_code = $exitCode
    log = $log
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
}
[IO.File]::WriteAllText($json, ($metadata | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))
Get-Content -LiteralPath $json
exit $exitCode
