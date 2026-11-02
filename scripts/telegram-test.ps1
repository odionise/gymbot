param(
    [ValidateSet('prepare', 'check', 'start', 'status', 'stop')]
    [string]$Mode = 'status',
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing project .venv; follow README setup first.' }
$taskArgs = @((Join-Path $PSScriptRoot 'telegram_test.py'), $Mode)
if ($Offline) { $taskArgs += '--offline' }
& $python @taskArgs
exit $LASTEXITCODE
