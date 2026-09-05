param(
    [int]$StartupSeconds = 90,
    [int]$ShutdownSeconds = 20
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repo 'runtime\jawl-sources\jawl-20260905-daily-v1'
$py = Join-Path $repo 'runtime\jawl-daily-venv\Scripts\python.exe'
$profileHome = Join-Path $repo 'runtime\instances\daily'
$log = Join-Path $profileHome 'logs\startup-smoke.log'
$env:JAWL_INSTANCE_ID = 'daily'
$env:JAWL_INSTANCE_HOME = $profileHome
$env:JAWL_DATA_DIR = Join-Path $profileHome 'data'
$env:JAWL_CONFIG_DIR = Join-Path $profileHome 'config'
$env:JAWL_LOG_DIR = Join-Path $profileHome 'logs'
$env:JAWL_PROMPT_DIR = Join-Path $profileHome 'prompts'
$env:JAWL_SANDBOX_DIR = Join-Path $profileHome 'sandbox'
$env:JAWL_ENV_FILE = Join-Path $profileHome '.env'
$env:JAWL_INSTANCES_ROOT = Join-Path $repo 'runtime\instances'
$env:PYTHONPATH = $source
$env:PYTHONIOENCODING = 'utf-8'
$env:LLM_API_URL = 'http://127.0.0.1:9/v1'
$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $py
$psi.Arguments = 'src\main.py'
$psi.WorkingDirectory = $source
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
foreach ($name in 'JAWL_INSTANCE_ID','JAWL_INSTANCE_HOME','JAWL_DATA_DIR','JAWL_CONFIG_DIR','JAWL_LOG_DIR','JAWL_PROMPT_DIR','JAWL_SANDBOX_DIR','JAWL_ENV_FILE','JAWL_INSTANCES_ROOT','PYTHONPATH','PYTHONIOENCODING','LLM_API_URL') {
    $psi.Environment[$name] = (Get-Item "Env:$name").Value
}
$process = [Diagnostics.Process]::new()
$process.StartInfo = $psi
[void]$process.Start()
Start-Sleep -Seconds $StartupSeconds
New-Item -ItemType File -Force -Path (Join-Path $env:JAWL_DATA_DIR 'agent.stop') | Out-Null
if (-not $process.WaitForExit($ShutdownSeconds * 1000)) { $process.Kill(); $process.WaitForExit() }
$output = $process.StandardOutput.ReadToEnd() + "`n" + $process.StandardError.ReadToEnd()
[IO.File]::WriteAllText($log, $output, (New-Object Text.UTF8Encoding($false)))
"JAWL startup smoke exit=$($process.ExitCode)"
"log=$log"
Get-Content $log -Tail 20
