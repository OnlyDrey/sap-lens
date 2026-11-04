#requires -Version 5.1
<# SAP Lens public Windows bootstrapper. Main menus and build policy live in scripts/build.py.
   No execution-policy changes, raw installer downloads, or implicit system installs. #>
[CmdletBinding()]
param(
    [string]$Mode='', [string]$Platform='', [string]$Target='', [string]$Version='',
    [string]$Scope='targeted', [Alias('OutputDir')][string]$Output='', [string]$Area='',
    [switch]$Setup, [switch]$SetupOnly, [switch]$SkipSetup, [switch]$InstallSystem,
    [switch]$NonInteractive, [switch]$DryRun, [switch]$ConfirmClean, [switch]$NoCache,
    [string]$WindowsHost='', [string]$WindowsRepository='', [string]$LinuxHost='', [string]$LinuxRepository='',
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
function Find-BuildPython {
    $candidates=@()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates+=@{Command='py';Arguments=@('-3.12')} }
    foreach ($name in @('python3.12','python')) {
        $command=Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notmatch '\\WindowsApps\\') { $candidates+=@{Command=$command.Source;Arguments=@()} }
    }
    foreach ($path in @((Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'),(Join-Path $env:ProgramFiles 'Python312/python.exe'))) {
        if (Test-Path -LiteralPath $path) { $candidates+=@{Command=$path;Arguments=@()} }
    }
    foreach ($candidate in $candidates) {
        try {
            $prefix=$candidate.Arguments
            $commandPath=$candidate.Command
            $resolved=& $commandPath @prefix -c 'import sys,struct; print(sys.executable); sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize("P")==8 else 1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved)) { return [string]$resolved }
        } catch { continue }
    }
    return $null
}
if ($env:OS -ne 'Windows_NT') { Write-Host 'Use python3.12 scripts/build.py on Linux. This bootstrapper supports Windows x64.'; exit 2 }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { Write-Host 'Use x64 PowerShell on Windows x64; ARM/32-bit build hosts are not supported.'; exit 2 }
$nonInteractiveRun=$NonInteractive -or $env:GITHUB_ACTIONS -eq 'true'
try { $nonInteractiveRun=$nonInteractiveRun -or [Console]::IsInputRedirected } catch { $nonInteractiveRun=$true }
$originalEncoding=[Console]::OutputEncoding
$originalOutputEncoding=$OutputEncoding
$originalUtf8=$env:PYTHONUTF8
$exitCode=2
try {
    [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding=[Console]::OutputEncoding
    $env:PYTHONUTF8='1'
    $python=Find-BuildPython
    if (-not $python) {
        if ($Help) { Write-Host 'SAP Lens: .\build.ps1 -Mode quick|test|build|package|release|clean [-Platform windows|linux|docker] [-Target desktop|installer|service|server|all]. Install Python 3.12 x64 or opt in with -InstallSystem.'; exit 0 }
        if ($SkipSetup -or $DryRun) { Write-Host 'Python 3.12 x64 is missing. Install it through approved tools; skip-setup/dry-run will not install it.'; exit 3 }
        $consent=[bool]$InstallSystem
        if (-not $consent -and -not $nonInteractiveRun) { $consent=(Read-Host 'Python 3.12 x64 is required. Install for this user using winget? [y/N]') -match '^(?i:y|yes)$' }
        if (-not $consent) { Write-Host 'Python setup declined/not authorized. Install Python 3.12 x64 and reopen PowerShell, or explicitly use -InstallSystem.'; exit 3 }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Write-Host 'winget is unavailable. Use the approved Python 3.12 x64 installer from python.org, then reopen PowerShell. No software was installed.'; exit 3 }
        & winget install --id Python.Python.3.12 --exact --source winget --scope user --architecture x64 --accept-source-agreements --accept-package-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { $exitCode=$LASTEXITCODE; throw 'Python installation failed. Review winget/permission/network diagnostics; no elevated fallback is attempted.' }
        $python=Find-BuildPython
        if (-not $python) { Write-Host 'Installation returned success, but compatible Python was not found. Reopen PowerShell or repair Python 3.12 x64.'; exit 3 }
    }
    $arguments=@((Join-Path $PSScriptRoot 'scripts/build.py'))
    if ($Mode) { $arguments+=$Mode.ToLowerInvariant() }
    foreach ($pair in @(@('--platform',$Platform),@('--target',$Target),@('--version',$Version),@('--scope',$Scope),@('--output',$Output),@('--area',$Area),@('--windows-host',$WindowsHost),@('--windows-repository',$WindowsRepository),@('--linux-host',$LinuxHost),@('--linux-repository',$LinuxRepository))) {
        if ($pair[1]) { $arguments+=$pair }
    }
    foreach ($pair in @(@('--setup',$Setup),@('--setup-only',$SetupOnly),@('--skip-setup',$SkipSetup),@('--install-system',$InstallSystem),@('--non-interactive',$nonInteractiveRun),@('--dry-run',$DryRun),@('--confirm-clean',$ConfirmClean),@('--no-cache',$NoCache),@('--verbose',[bool]$PSBoundParameters['Verbose']),@('--help',$Help))) {
        if ($pair[1]) { $arguments+=$pair[0] }
    }
    & $python @arguments
    $exitCode=$LASTEXITCODE
} catch { Write-Host $_.Exception.Message -ForegroundColor Red } finally {
    [Console]::OutputEncoding=$originalEncoding
    $OutputEncoding=$originalOutputEncoding
    $env:PYTHONUTF8=$originalUtf8
}
exit $exitCode
