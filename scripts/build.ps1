#requires -Version 5.1
<# SAP Lens public Windows bootstrapper. Main menus and build policy live in scripts/build.py.
   No execution-policy changes, raw installer downloads, or implicit system installs. #>
[CmdletBinding()]
param(
    [string]$Mode='', [string]$Platform='', [string]$Target='', [string]$Version='',
    [string]$Scope='targeted', [Alias('OutputDir')][string]$Output='', [string]$Area='',
    [switch]$Setup, [switch]$SetupOnly, [switch]$CheckOnly, [switch]$Repair, [switch]$Json, [switch]$SkipSetup, [switch]$InstallSystem,
    [switch]$NonInteractive, [switch]$DryRun, [switch]$ConfirmClean, [switch]$NoCache, [switch]$NativeAcceptance,
    [string]$WindowsHost='', [string]$WindowsRepository='', [string]$LinuxHost='', [string]$LinuxRepository='',
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
# The probe must not contain double quotes: Windows PowerShell 5.1 strips embedded double quotes from native-command arguments, which
# turns a literal such as "P" into a bare name and makes every interpreter fail with a NameError (the reported "Python is missing" bug).
$script:ScriptDirectory = $PSScriptRoot
$script:PythonProbe = 'import sys; print(sys.executable); print(sys.version.split()[0]); print(64 if sys.maxsize>2**32 else 32)'

function Test-PythonCandidate {
    param([string]$Source, [string]$Path, [string[]]$Prefix = @())
    $result = New-Object psobject -Property @{ Source = $Source; Path = $Path; Executable = ''; Version = ''; Bits = ''; Compatible = $false; Result = '' }
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # native stderr must not become a terminating error under -ErrorAction Stop
    try {
        $lines = @(& $Path @Prefix -c $script:PythonProbe 2>$null)
        $code = $LASTEXITCODE
    } catch {
        $result.Result = 'Rejected - the interpreter could not be started'
        return $result
    } finally { $ErrorActionPreference = $saved }
    if ($code -ne 0 -or $lines.Count -lt 3) { $result.Result = "Rejected - the interpreter failed its probe (exit code $code)"; return $result }
    $result.Executable = [string]$lines[0]; $result.Version = [string]$lines[1]; $result.Bits = [string]$lines[2]
    if ($result.Version -notmatch '^3\.12\.') { $result.Result = "Rejected - Python 3.12 is required (found $($result.Version))"; return $result }
    if ($result.Bits -ne '64') { $result.Result = 'Rejected - 64-bit Python is required'; return $result }
    if (-not (Test-Path -LiteralPath $result.Executable)) { $result.Result = 'Rejected - the reported interpreter path does not exist'; return $result }
    $result.Compatible = $true; $result.Result = 'Compatible'
    return $result
}

function Get-RepositoryRoot {
    # Explicit and validated: $PSScriptRoot is empty when a function runs outside a script file (dot-sourced scriptblock, -Command), so an
    # override or the script's own location is used and the result must contain scripts\build.py. Never the working directory.
    param([string]$ScriptDirectory = '')
    $directory = $ScriptDirectory
    if (-not $directory) { $directory = $env:SAP_LENS_SCRIPT_DIR }
    if (-not $directory -and $script:ScriptDirectory) { $directory = $script:ScriptDirectory }
    if (-not $directory -and $PSScriptRoot) { $directory = $PSScriptRoot }
    if (-not $directory) { return '' }
    $root = Split-Path -Parent $directory
    if ($root -and (Test-Path -LiteralPath (Join-Path $directory 'build.py'))) { return $root }
    return ''
}

function Get-PythonCandidates {
    param([string]$RepositoryRoot = '')
    # Deterministic order: project .venv, Python launcher, PATH, other registered installations. No hardcoded install locations.
    $seen = @{}
    $list = @()
    # This file lives in scripts/: the repository root is its parent and the engine is its sibling build.py; neither depends on the working directory.
    if (-not $RepositoryRoot) { $RepositoryRoot = Get-RepositoryRoot }
    $venv = if ($RepositoryRoot) { Join-Path $RepositoryRoot '.venv\Scripts\python.exe' } else { '' }
    if ($venv -and (Test-Path -LiteralPath $venv)) { $list += @{ Source = 'project .venv'; Path = $venv; Prefix = @() } }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $list += @{ Source = 'Python launcher (py -3.12)'; Path = $launcher.Source; Prefix = @('-3.12') } }
    foreach ($name in @('python3.12', 'python')) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.CommandType -ne 'Application') { continue }
            $list += @{ Source = "PATH ($name)"; Path = $command.Source; Prefix = @() }
        }
    }
    if ($launcher) {
        $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { foreach ($row in @(& $launcher.Source -0p 2>$null)) { if ("$row" -match '([A-Za-z]:\\.*python[w]?\.exe)\s*$') { $list += @{ Source = 'registered (py -0p)'; Path = $Matches[1]; Prefix = @() } } } } catch { } finally { $ErrorActionPreference = $saved }
    }
    if ($env:OS -eq 'Windows_NT') {
        foreach ($key in @('HKCU:\Software\Python\PythonCore\3.12\InstallPath', 'HKLM:\Software\Python\PythonCore\3.12\InstallPath', 'HKLM:\Software\WOW6432Node\Python\PythonCore\3.12\InstallPath')) {
            try {
                $entry = Get-ItemProperty -LiteralPath $key -ErrorAction Stop
                $exe = $entry.ExecutablePath
                if (-not $exe -and $entry.'(default)') { $exe = Join-Path $entry.'(default)' 'python.exe' }
                if ($exe) { $list += @{ Source = 'registered (registry)'; Path = $exe; Prefix = @() } }
            } catch { }
        }
    }
    $unique = @()
    foreach ($item in $list) {
        $id = ([string]$item.Path + '|' + ($item.Prefix -join ' ')).ToLowerInvariant()
        if ($seen.ContainsKey($id)) { continue }
        $seen[$id] = $true; $unique += $item
    }
    return $unique
}

function Find-BuildPython {
    $script:PythonDiagnostics = @()
    foreach ($candidate in (Get-PythonCandidates)) {
        if ($candidate.Path -match '\\WindowsApps\\') {
            $script:PythonDiagnostics += New-Object psobject -Property @{ Source = $candidate.Source; Path = $candidate.Path; Version = ''; Bits = ''; Compatible = $false; Result = 'Skipped - Microsoft Store app execution alias (not a real interpreter)' }
            continue
        }
        $probe = Test-PythonCandidate -Source $candidate.Source -Path $candidate.Path -Prefix $candidate.Prefix
        $script:PythonDiagnostics += $probe
        if ($probe.Compatible) {
            Write-Verbose ("Python discovery: using {0} ({1}, {2}-bit, {3})" -f $probe.Executable, $probe.Version, $probe.Bits, $candidate.Source)
            return [string]$probe.Executable
        }
    }
    return $null
}

$script:EngineCompleted = $false
$script:BootstrapDetail = 'Bootstrap failed before the build engine started.'
function Write-BootstrapMessage([string]$Message) {
    $script:BootstrapDetail = $Message
    if ($Json -or $DryRun) { [Console]::Error.WriteLine($Message) } else { Write-Host $Message }
}
function Write-BootstrapFailure([int]$Code) {
    if ($Json) { Write-Output (@{ ok=$false; exit_code=$Code; items=@(); error=$script:BootstrapDetail } | ConvertTo-Json -Depth 4) }
}

function Write-PythonDiscovery {
    Write-BootstrapMessage 'Python discovery:'
    if (-not $script:PythonDiagnostics -or $script:PythonDiagnostics.Count -eq 0) { Write-BootstrapMessage '  No Python interpreter was found (checked the project .venv, the Python launcher, PATH and registered installations).'; return }
    foreach ($row in $script:PythonDiagnostics) {
        $shown = if ($row.Version) { "$($row.Version), $($row.Bits)-bit" } else { 'not inspected' }
        Write-BootstrapMessage ("  {0}: {1}`n    {2} -> {3}" -f $row.Source, $row.Path, $shown, $row.Result)
    }
}
if ($env:OS -ne 'Windows_NT') { Write-BootstrapMessage 'Use python3.12 scripts/build.py on Linux. This bootstrapper supports Windows x64.'; Write-BootstrapFailure 2; exit 2 }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { Write-BootstrapMessage 'Use x64 PowerShell on Windows x64; ARM/32-bit build hosts are not supported.'; Write-BootstrapFailure 2; exit 2 }
$nonInteractiveRun=$NonInteractive -or $Json -or $DryRun -or $env:GITHUB_ACTIONS -eq 'true'
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
        Write-PythonDiscovery
        if ($Help) { Write-BootstrapMessage 'SAP Lens: .\scripts\build.ps1 -Mode quick|test|build|package|release|clean [-Platform windows|linux|docker] [-Target desktop|installer|service|server|all]. Install Python 3.12 x64 or opt in with -InstallSystem.'; exit 0 }
        if ($SkipSetup -or $DryRun) { Write-BootstrapMessage 'Python 3.12 x64 is missing. Install it through approved tools; skip-setup/dry-run will not install it.'; Write-BootstrapFailure 3; exit 3 }
        $consent=[bool]$InstallSystem
        if (-not $consent -and -not $nonInteractiveRun) { $consent=(Read-Host 'Python 3.12 x64 is required. Install for this user using winget? [y/N]') -match '^(?i:y|yes)$' }
        if (-not $consent) { Write-BootstrapMessage 'Python setup declined/not authorized. Install Python 3.12 x64 and reopen PowerShell, or explicitly use -InstallSystem.'; Write-BootstrapFailure 3; exit 3 }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Write-BootstrapMessage 'winget is unavailable. Use the approved Python 3.12 x64 installer from python.org, then reopen PowerShell. No software was installed.'; Write-BootstrapFailure 3; exit 3 }
        & winget install --id Python.Python.3.12 --exact --source winget --scope user --architecture x64 --accept-source-agreements --accept-package-agreements --disable-interactivity | ForEach-Object { if ($Json) { [Console]::Error.WriteLine([string]$_) } else { Write-Output $_ } }
        if ($LASTEXITCODE -ne 0) { $exitCode=$global:LASTEXITCODE; throw 'Python installation failed. Review winget/permission/network diagnostics; no elevated fallback is attempted.' }
        $python=Find-BuildPython
        if (-not $python) { Write-BootstrapMessage 'Installation returned success, but compatible Python was not found. Reopen PowerShell or repair Python 3.12 x64.'; Write-BootstrapFailure 3; exit 3 }
    }
    $arguments=@((Join-Path $PSScriptRoot 'build.py'))
    if ($Mode) { $arguments+=$Mode.ToLowerInvariant() }
    foreach ($pair in @(@('--platform',$Platform),@('--target',$Target),@('--version',$Version),@('--scope',$Scope),@('--output',$Output),@('--area',$Area),@('--windows-host',$WindowsHost),@('--windows-repository',$WindowsRepository),@('--linux-host',$LinuxHost),@('--linux-repository',$LinuxRepository))) {
        if ($pair[1]) { $arguments+=$pair }
    }
    foreach ($pair in @(@('--setup',$Setup),@('--setup-only',$SetupOnly),@('--check-only',$CheckOnly),@('--repair',$Repair),@('--json',$Json),@('--skip-setup',$SkipSetup),@('--install-system',$InstallSystem),@('--non-interactive',$nonInteractiveRun),@('--dry-run',$DryRun),@('--confirm-clean',$ConfirmClean),@('--no-cache',$NoCache),@('--native-acceptance',$NativeAcceptance),@('--verbose',[bool]$PSBoundParameters['Verbose']),@('--help',$Help))) {
        if ($pair[1]) { $arguments+=$pair[0] }
    }
    $nativePreference = $ErrorActionPreference
    try {
        # Native stderr carries legitimate warnings in JSON mode; the exit code, not stderr presence, is authoritative.
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = 2
        if ($Json) {
            $engineJson = @(& $python @arguments)
            $exitCode=$global:LASTEXITCODE
            if ($engineJson.Count) {
                $engineJson | Write-Output
                $script:EngineCompleted = $true
            } else {
                Write-BootstrapMessage 'Build engine returned no JSON report. Review stderr diagnostics.'
                if ($exitCode -eq 0) { $exitCode = 2 }
            }
        } else {
            & $python @arguments
            $exitCode=$global:LASTEXITCODE
            $script:EngineCompleted = $true
        }
    } finally { $ErrorActionPreference = $nativePreference }
} catch { if ($exitCode -eq 0) { $exitCode=2 }; Write-BootstrapMessage $_.Exception.Message } finally {
    [Console]::OutputEncoding=$originalEncoding
    $OutputEncoding=$originalOutputEncoding
    $env:PYTHONUTF8=$originalUtf8
}
if (-not $script:EngineCompleted) { Write-BootstrapFailure $exitCode }
exit $exitCode
