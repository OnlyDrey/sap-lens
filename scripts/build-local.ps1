# Supported local entry point. Packaging remains in build-windows.ps1.
[CmdletBinding()]
param(
    [ValidateSet('Build', 'Quick', 'Validate', 'Package')]
    [string]$Mode = 'Build',
    [string]$Version = '0.1.0'
)
$ErrorActionPreference = 'Stop'
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$stage = 'Prerequisites'
$root = Split-Path $PSScriptRoot -Parent
$originalLocation = Get-Location
$originalConsoleEncoding = [Console]::OutputEncoding
$originalOutputEncoding = $OutputEncoding
$environmentNames = @('PATH', 'PYTHONUTF8', 'PYTHONIOENCODING', 'SAP_LENS_LOCAL_VERSION', 'SAP_LENS_CONFIG_DIR', 'DATA_CSV_PATH', 'USER_CSV_PATH')
$savedEnvironment = @{}
foreach ($name in $environmentNames) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$lock = $null
$transcribing = $false
$results = @()
$completed = $false
$output = $null
function Invoke-Native([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
function Run-Stage([string]$Name, [scriptblock]$Action) {
    $script:stage = $Name
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $status = 'failed'
    Write-Host "`n=== $Name ==="
    try {
        # Do not redirect native stderr into PowerShell ErrorRecords: on Windows
        # PowerShell 5.1 that makes successful unittest/pip output terminate early.
        & $Action | Out-Default
        $status = 'passed'
    } finally {
        $script:results += [pscustomobject]@{ stage = $Name; status = $status; seconds = [math]::Round($timer.Elapsed.TotalSeconds, 2) }
    }
}
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Local Windows builds require Windows x64. Use the documented Linux validation commands on other operating systems.' }
    if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Use x64 Windows PowerShell on Windows x64, not an ARM or 32-bit shell.' }
    if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'Install Windows PowerShell 5.1 or PowerShell 7.' }
    if ($env:GITHUB_ACTIONS -eq 'true') { throw 'This entry point is local-only. GitHub Actions must use build-windows.ps1.' }
    Set-Location $root
    foreach ($command in @('git', 'node', 'npm')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Missing $command. Install Git for Windows and Node.js 24 LTS (including npm), then reopen PowerShell." }
    }
    $nodeVersion = & node -p 'process.versions.node'
    if ($LASTEXITCODE -ne 0 -or ([version]$nodeVersion).Major -ne 24) { throw 'Use Node.js 24 LTS, matching the Windows CI runner.' }
    $npmVersion = & npm --version
    if ($LASTEXITCODE -ne 0 -or ([version]$npmVersion).Major -notin @(10, 11)) { throw 'Use npm 10 or 11 supplied with the supported Node.js installation.' }
    # Configure I/O before querying Python: its installation path can be Unicode.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
    $hostPython = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $hostPython = & py -3.12 -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -ne 0) { $hostPython = $null }
    }
    if (-not $hostPython -and (Get-Command python -ErrorAction SilentlyContinue)) { $hostPython = (Get-Command python).Source }
    if (-not $hostPython) { throw 'Install 64-bit Python 3.12 with the Python launcher, then reopen PowerShell.' }
    & $hostPython -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required, matching CI. Install it with the Python launcher.' }
    $buildDirectory = Join-Path $root 'backend/build'
    New-Item -ItemType Directory -Force $buildDirectory | Out-Null
    try {
        $lock = [System.IO.File]::Open((Join-Path $buildDirectory 'local-build.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch { throw 'Another local build is running, or backend/build is not writable. Close the other build and retry.' }
    $run = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $runDirectory = Join-Path $root "dist/local/runs/$run"
    New-Item -ItemType Directory -Force $runDirectory | Out-Null
    Start-Transcript -Path (Join-Path $runDirectory 'build.log') | Out-Null
    $transcribing = $true
    $env:SAP_LENS_LOCAL_VERSION = $Version
    $env:SAP_LENS_CONFIG_DIR = Join-Path $buildDirectory "local-test-settings/$run"
    $env:DATA_CSV_PATH = ''
    $env:USER_CSV_PATH = ''
    $helper = Join-Path $PSScriptRoot 'local-build.py'
    $canonical = Join-Path $PSScriptRoot 'build-windows.ps1'
    $buildPython = Join-Path $buildDirectory 'python-env/Scripts/python.exe'
    $auditPython = Join-Path $buildDirectory 'audit-env/Scripts/python.exe'
    $env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:PATH
    if ($Mode -in @('Build', 'Package')) {
        Run-Stage 'Clean source check' { Invoke-Native $hostPython @($helper, 'clean') }
    }
    # Validate the requested version before dependency installation or packaging.
    Run-Stage 'Local identity' { Invoke-Native $hostPython @($helper, 'identity', '--version', $Version) }
    $info = Get-Content -Raw (Join-Path $buildDirectory 'build-version.json') | ConvertFrom-Json
    $output = Join-Path $root "dist/local/packages/$($info.version)/$run"
    if ($Mode -eq 'Package') {
        Run-Stage 'Validated input freshness' { Invoke-Native $hostPython @($helper, 'check', '--version', $Version) }
    } else {
        Run-Stage 'Invalidate previous validation' { Invoke-Native $hostPython @($helper, 'invalidate') }
        Run-Stage 'Environment' { & $canonical -Stage Environment -PythonExecutable $hostPython }
        Run-Stage 'Python' { & $canonical -Stage Python -PythonExecutable $hostPython }
        Run-Stage 'Frontend' {
            $frontendStage = if ($Mode -eq 'Quick') { 'FrontendInstall' } else { 'Frontend' }
            & $canonical -Stage $frontendStage -PythonExecutable $hostPython
            Invoke-Native 'npm' @('--prefix', 'frontend', 'run', 'check:types')
            Invoke-Native 'node' @('scripts/sync-lucide-catalog.mjs', '--check')
        }
    }
    Run-Stage 'Packaging tool versions' {
        Invoke-Native $buildPython @($helper, 'tools')
    }
    if ($Mode -ne 'Quick') {
        Run-Stage 'Audit' {
            Invoke-Native $hostPython @('-m', 'venv', (Join-Path $buildDirectory 'audit-env'))
            & $canonical -Stage Audit -PythonExecutable $hostPython -AuditPython $auditPython
            # Package also rechecks current vulnerability data without reinstalling inputs.
            if ($Mode -eq 'Package') { Invoke-Native 'npm' @('--prefix', 'frontend', 'audit', '--omit=dev') }
        }
    }
    if ($Mode -ne 'Package') {
        Run-Stage 'Backend' { & $canonical -Stage Backend -PythonExecutable $hostPython }
        if ($Mode -ne 'Quick') { Run-Stage 'Browser' { & $canonical -Stage Browser -PythonExecutable $hostPython } }
        Run-Stage 'Repository' {
            Invoke-Native $buildPython @('scripts/check-workflows.py')
            Invoke-Native $buildPython @('scripts/ci.py', 'lint')
            & (Join-Path $PSScriptRoot 'check-powershell.ps1')
            Invoke-Native 'git' @('diff', '--check')
        }
        if ($Mode -ne 'Quick') {
            Run-Stage 'Validation receipt' {
                Invoke-Native $buildPython @($helper, 'record', '--version', $Version, '--stages', 'Frontend', 'Python', 'Audit', 'Backend', 'Browser', 'Repository')
            }
        }
    }
    if ($Mode -in @('Build', 'Package')) {
        Run-Stage 'Validated input freshness' { Invoke-Native $buildPython @($helper, 'check', '--version', $Version) }
        Run-Stage 'Package' { & $canonical -Stage Package -PythonExecutable $hostPython }
        Run-Stage 'Verify' { & $canonical -Stage Verify -PythonExecutable $hostPython }
        Run-Stage 'Smoke' { & $canonical -Stage Smoke -PythonExecutable $hostPython }
        Run-Stage 'Distribution roundtrip' { Invoke-Native $buildPython @($helper, 'export', '--version', $Version, '--output', $output) }
    }
    $completed = $true
} catch {
    $message = "Local $Mode failed in stage '$stage': $($_.Exception.Message)"
    Write-Host $message -ForegroundColor Red

} finally {
    $watch.Stop()

    $status = if ($completed) { 'passed' } else { 'failed' }
    $summary = [pscustomobject]@{
        mode = $Mode; requested_version = $Version; status = $status; last_stage = $stage
        identity = $info; node = $nodeVersion; npm = $npmVersion; powershell = $PSVersionTable.PSVersion.ToString(); stages = $results; seconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
        artifact_directory = if ($completed -and $Mode -in @('Build', 'Package')) { $output } else { $null }
        log_directory = $runDirectory
    }
    if ($runDirectory) {
        $json = $summary | ConvertTo-Json -Depth 8
        [System.IO.File]::WriteAllText((Join-Path $runDirectory 'summary.json'), $json, (New-Object System.Text.UTF8Encoding($false)))
    }
    Write-Host "`nSAP Lens local $Mode : $status ($($summary.seconds) seconds)"
    if ($info) { Write-Host "Version: $($info.version) | Source: $($info.source_sha)" }
    $results | Format-Table -AutoSize | Out-Host
    if ($completed -and $Mode -in @('Build', 'Package')) { Write-Host "Verified artifacts: $output" }
    if ($runDirectory) { Write-Host "Logs and summary: $runDirectory" }
    if ($transcribing) { Stop-Transcript | Out-Null }
    if ($lock) { $lock.Dispose() }
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    [Console]::OutputEncoding = $originalConsoleEncoding
    $OutputEncoding = $originalOutputEncoding
    Set-Location $originalLocation
}
if (-not $completed) { exit 1 }
