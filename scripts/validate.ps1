param(
    [ValidateSet('Fast','Feature','Full')][string]$Level = 'Fast',
    [string]$Area,
    [string]$Base = 'HEAD',
    [ValidateRange(1,3)][int]$Jobs = 1,
    [ValidateRange(1,3)][int]$BrowserJobs = 1,
    [string]$Grep,
    [switch]$Plan,
    [switch]$Reports,
    [switch]$NoBuild
)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'validate.py'),'--level',$Level.ToLower(),'--base',$Base,'--jobs',$Jobs,'--browser-jobs',$BrowserJobs)
if ($Area) { $arguments += @('--area',$Area) }
if ($Grep) { $arguments += @('--grep',$Grep) }
if ($Plan) { $arguments += '--plan' }
if ($Reports) { $arguments += '--reports' }
if ($NoBuild) { $arguments += '--no-build' }
$interpreter = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $interpreter @arguments
exit $LASTEXITCODE
