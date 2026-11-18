<# Shared native orchestration: desktop packaging stays in build-windows.ps1. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('Desktop','Service')][string]$Target,[string]$OutputDirectory='',[switch]$NativeAcceptance)
$ErrorActionPreference = 'Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
# Packaging never installs or changes a Windows service. The privileged native SCM acceptance (scripts/test-server-service.ps1) runs only on request
# (-NativeAcceptance) or on the CI runner, and its prerequisite is checked before the expensive build starts.
$runAcceptance = $Target -eq 'Service' -and ($NativeAcceptance -or $env:GITHUB_ACTIONS -eq 'true')
if ($runAcceptance) {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        [Console]::Error.WriteLine('ACCEPTANCE PREREQUISITE: the native service (SCM) acceptance needs an elevated PowerShell. Nothing was built. Run without -NativeAcceptance to package without it, or start an elevated shell.')
        exit 3
    }
}
function Checked([scriptblock]$Command, [string]$Stage='Windows deployment command') {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $completed = $false
    Write-Host "[build-stage] START | $Stage"
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) { throw "Windows deployment stage '$Stage' failed (exit $LASTEXITCODE). See the enclosing build.log." }
        $completed = $true
    } finally {
        $timer.Stop()
        $status = if ($completed) { 'PASS' } else { 'FAILED' }
        Write-Host ("[build-stage] {0} | {1} | elapsed {2:N1}s" -f $status, $Stage, $timer.Elapsed.TotalSeconds)
    }
}
Checked { python scripts/deployment-package.py require-inputs } -Stage 'Verify validated deployment inputs'
if (-not $OutputDirectory) { $OutputDirectory=Join-Path $root 'dist/deployment' }
if ($env:GITHUB_ACTIONS -eq 'true') {
    & ./scripts/build-windows.ps1 -Stage Environment
    & ./scripts/build-windows.ps1 -Stage Python
    & ./scripts/build-windows.ps1 -Stage Audit
} # Local receipt already binds this Windows dependency environment and audit.
$python=Join-Path $root 'backend/build/python-env/Scripts/python.exe'
foreach ($pattern in @('test_desktop.py','test_windows_package.py','test_server.py')) {
    Checked { & $python -W error::DeprecationWarning -m unittest discover -s backend/tests -p $pattern -v } -Stage "Validate $pattern"
}
if ($Target -eq 'Desktop') {
    & ./scripts/build-windows.ps1 -Stage Package -ValidatedDeployment
    & ./scripts/build-windows.ps1 -Stage Verify
    & ./scripts/build-windows.ps1 -Stage Smoke
    # Keep the canonical portable EXE/verification, then wrap it with an installer.
    $info=Get-Content backend/build/build-version.json -Raw | ConvertFrom-Json
    $bundle=Join-Path $root ('backend/build/deployment-desktop-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $bundle | Out-Null
    Copy-Item LICENSE.md $bundle
    $readme=@"
SAP Lens Desktop

Run SAP-Lens-Windows-Desktop-x64-$($info.version)-Setup.exe to install for the current user under AppData. Administrator rights are not required. Microsoft Edge WebView2 Runtime is required.

For upgrades, close SAP Lens and run Setup again. Existing application data is preserved. Uninstall through Windows Installed Apps; data is retained by default.

The metadata directory contains integrity evidence, not launch choices. The portable EXE is an internal build input; this download contains only Setup.

Instructions: https://github.com/OnlyDrey/sap-lens/blob/work/docs/deployment/WINDOWS_DESKTOP.md
"@
    [IO.File]::WriteAllText((Join-Path $bundle 'README.md'),$readme,[Text.UTF8Encoding]::new($false))
    & ./scripts/build-desktop-installer.ps1 -OutputDirectory $bundle
    $installer=Join-Path $bundle ("SAP-Lens-Windows-Desktop-x64-$($info.version)-Setup.exe")
    $evidence=Join-Path $bundle 'metadata'
    New-Item -ItemType Directory $evidence | Out-Null
    & ./scripts/test-desktop-installer.ps1 -Installer $installer -Report (Join-Path $evidence 'installer-verification.json')
    # Compiler checksums remain internal; the bundle manifest binds shipped bytes.
    Remove-Item ($installer+'.sha256')
    Checked { & $python scripts/deployment-package.py finish --directory $bundle --platform Windows-Desktop-x64 --output $OutputDirectory }
    Checked { & $python scripts/packaging/verify-desktop-distribution.py --directory $bundle --payload-directory backend/dist }

} else {
    $wrapper=Join-Path $root 'backend/build/WinSW-x64.exe'
    Checked { & $python scripts/packaging/local-build.py winsw --output $wrapper }
    $bundle=Join-Path $root ('backend/build/deployment-service-'+[guid]::NewGuid().ToString('N'))
    & ./scripts/build-server-windows.ps1 -WinSW $wrapper -ValidatedDeployment -OutputDirectory $bundle
    if ($runAcceptance) { & ./scripts/test-server-service.ps1 -Bundle $bundle }
    else { Write-Output "Native SCM acceptance NOT RUN (packaging only). Run it elevated: powershell -NoProfile -File scripts\test-server-service.ps1 -Bundle `"$bundle`"" }
    Checked { & $python scripts/deployment-package.py finish --directory $bundle --platform Windows-Service-x64 --output $OutputDirectory }
}
