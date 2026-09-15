param(
    [int]$ConsolePort = 8770,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'runtime\jawl-sources\jawl-20260906-daily-v2'
$venvPython = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) { throw "Owned runtime Python is missing: $venvPython" }
if (-not (Test-Path -LiteralPath $source)) { throw "Pinned JAWL source is missing: $source" }
& (Get-Command python -ErrorAction Stop).Source (Join-Path $repo 'scripts\verify_jawl_snapshot.py') --source $source | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Pinned JAWL source verification failed; refusing to start.' }

& $venvPython (Join-Path $repo 'scripts\prepare_daily_profile.py')
if ($LASTEXITCODE -ne 0) { throw 'Owned JAWL profile preparation failed; refusing to start.' }
$preflight = & $venvPython (Join-Path $repo 'scripts\preflight_jawl_runtime.py')
if ($LASTEXITCODE -ne 0) {
    Write-Error "JAWL daily profile is not ready. Run the preflight output above and warm the embedding cache before starting."
    exit $LASTEXITCODE
}

$env:PYTHONPATH = Join-Path $source ''
$env:JAWL_INSTANCE_ID = 'daily'
$env:JAWL_INSTANCE_HOME = Join-Path $repo 'runtime\instances\daily'
$env:JAWL_DATA_DIR = Join-Path $env:JAWL_INSTANCE_HOME 'data'
$env:JAWL_CONFIG_DIR = Join-Path $env:JAWL_INSTANCE_HOME 'config'
$env:JAWL_LOG_DIR = Join-Path $env:JAWL_INSTANCE_HOME 'logs'
$env:JAWL_CACHE_DIR = Join-Path $env:JAWL_INSTANCE_HOME 'cache'
$env:JAWL_PROMPT_DIR = Join-Path $env:JAWL_INSTANCE_HOME 'prompts'
$env:JAWL_SANDBOX_DIR = Join-Path $env:JAWL_INSTANCE_HOME 'sandbox'
$env:JAWL_ENV_FILE = Join-Path $env:JAWL_INSTANCE_HOME '.env'
$env:JAWL_INSTANCES_ROOT = Join-Path $repo 'runtime\instances'
$env:PYTHONDONTWRITEBYTECODE = '1'

# Provider URL is non-secret. The key must already exist in the environment as
# LLM_API_KEY_*. This script never stores, prints, or handles credentials.
if (-not $env:LLM_API_URL) { $env:LLM_API_URL = 'https://opencode.ai/zen/v1' }
$args = @('-m', 'src.web.server', '--host', '127.0.0.1', '--port', "$ConsolePort", '--keep-agent')
if ($NoBrowser) { $args += '--no-browser' }
Push-Location $env:JAWL_INSTANCE_HOME
try { & $venvPython @args } finally { Pop-Location }
