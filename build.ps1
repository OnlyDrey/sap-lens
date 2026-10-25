#requires -Version 5.1
# Cross-platform deployment builds; canonical packaging stays under scripts/.
[CmdletBinding()]
param(
    [ValidateSet('desktop','service','docker','linux-native','all')][string[]]$Platform=@('all'),
    [Parameter(Mandatory=$true)][string]$Version,
    [switch]$Clean,[switch]$NoCache,[switch]$ReuseValidation,
    [string]$OutputDir='',
    [string]$WindowsHost='',[string]$WindowsRepository='',
    [string]$LinuxHost='',[string]$LinuxRepository=''
)
$ErrorActionPreference = 'Stop'
$previousEncoding=[Console]::OutputEncoding
$previousOutputEncoding=$OutputEncoding
$previousUtf8=$env:PYTHONUTF8
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
$env:PYTHONUTF8='1'
Push-Location $PSScriptRoot
try {
    $arguments=@('scripts/build-deployments.py','--version',$Version)
    foreach ($target in $Platform) { $arguments+=@('--platform',$target) }
    if ($Clean) { $arguments+='--clean' }
    if ($NoCache) { $arguments+='--no-cache' }
    if ($ReuseValidation) { $arguments+='--reuse-validation' }
    foreach ($pair in @(@('--output-dir',$OutputDir),@('--windows-host',$WindowsHost),@('--windows-repository',$WindowsRepository),@('--linux-host',$LinuxHost),@('--linux-repository',$LinuxRepository))) {
        if ($pair[1]) { $arguments+=$pair }
    }
    if ($env:SAP_LENS_BUILD_PYTHON) { & $env:SAP_LENS_BUILD_PYTHON @arguments }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 @arguments }
    elseif (Get-Command python3.12 -ErrorAction SilentlyContinue) { & python3.12 @arguments }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python @arguments }
    else { throw 'Install Python 3.12 x64 with the Python launcher, then reopen PowerShell.' }
    exit $LASTEXITCODE
} finally {
    Pop-Location
    [Console]::OutputEncoding=$previousEncoding
    $OutputEncoding=$previousOutputEncoding
    $env:PYTHONUTF8=$previousUtf8
}
