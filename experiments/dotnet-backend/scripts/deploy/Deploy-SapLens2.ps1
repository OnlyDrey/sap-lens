<#
.SYNOPSIS
  Builds, validates and deploys SAP Lens 2 on this Windows host as the SapLens2 Windows service (test server). Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
  Usually started over SSH by scripts/deploy/deploy-windows.sh; it can also be run locally in an elevated PowerShell. Actions:

    Status          Service model (windows-service, unmanaged-process or none), state, account, command line, linked release, readiness, journal.
    Build           Fetch the branch, lock the exact commit, build it in an isolated worktree with the release builder and the selected tests,
                    verify the release (manifest, SHA-256, commit, version) and copy it to a versioned folder under ReleasesRoot.
    Deploy          Build (unless -Release names an already published folder), then: confirm service and data state, refuse data written by a
                    newer build, create and verify an encrypted pre-deployment backup, stop the service, switch the 'current' link, start,
                    verify readiness, version and commit. Any failure rolls back to the previous release when that is proven safe.
                    -DryRun resolves the commit and prints the plan without building, backing up or touching the service. Needs -Yes.
    InstallService  Creates (or with -Reconfigure updates) the SapLens2 service from the configuration. Needs -Yes.
                    -AdoptService brings a hand-installed service (another executable path, same arguments) under managed releases once.
    Rollback        Returns to the previous release (or -ToRelease), only when it can open the current data. Needs -Yes.
    Recover         Completes an interrupted deployment (Ctrl+C, a dropped SSH session): returns to the previous release. Needs -Yes.
    Health          Readiness and identity of the running server.

  Configuration: a JSON file that is not committed (-ConfigFile, $env:SAPLENS2_DEPLOY_CONFIG or C:\saplens2\deploy.local.json; template
  deploy.example.json). It holds paths, addresses and host names, never a secret. The last output line is 'SAPLENS2-RESULT: <json>'.
  Exit codes: 0 success, 1 failed (nothing changed, or rolled back and ready again), 2 refused before any change, 4 manual action required.

.EXAMPLE
  .\Deploy-SapLens2.ps1 -Action Status
.EXAMPLE
  .\Deploy-SapLens2.ps1 -Action Deploy -Branch experiment/dotnet-backend -Tests focused -Yes
#>
[CmdletBinding()]
param(
    [ValidateSet('Status', 'Build', 'Deploy', 'InstallService', 'Rollback', 'Recover', 'Health')]
    [string]$Action = 'Status',
    [string]$ConfigFile = '',
    [string]$Branch = '',
    [string]$Commit = '',
    [ValidateSet('focused', 'full', 'none')]
    [string]$Tests = 'focused',
    [string]$Release = '',
    [string]$ToRelease = '',
    [switch]$DryRun,
    [switch]$FirstInstall,
    [switch]$Reconfigure,
    [switch]$AdoptService,
    [switch]$Yes
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SapLens2.Deploy.psm1') -Force

function Write-Result($Value, [int]$Code) {
    $Value | ConvertTo-Json -Depth 8 | Write-Host
    Write-Host ('SAPLENS2-RESULT: ' + (@{ exit = $Code; result = $Value } | ConvertTo-Json -Depth 8 -Compress))
    exit $Code
}

function Test-Elevated {
    # $IsWindows does not exist in Windows PowerShell 5.1 (and StrictMode refuses unknown variables): test the edition first.
    if ($PSVersionTable.PSEdition -eq 'Core' -and -not (Get-Variable IsWindows -ValueOnly -ErrorAction SilentlyContinue)) { return $true }
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

try {
    $config = Read-SapLens2Settings $ConfigFile
    $changing = $Action -in @('Deploy', 'InstallService', 'Rollback', 'Recover') -and -not $DryRun
    if ($changing -and -not $Yes) { Stop-SL2 "$Action changes the service; repeat with -Yes after reviewing -Action Status (or -DryRun)." }
    if ($changing -and -not (Test-Elevated)) { Stop-SL2 "$Action needs an elevated session (an administrator account over SSH, or Run as administrator)." }
    switch ($Action) {
        'Status' { Write-Result (Get-SL2Status $config) 0 }
        'Health' {
            $base = "https://$($config.ListenAddress):$($config.Port)"
            $ready = Invoke-SL2Http "$base/health/ready"; $identity = Invoke-SL2Http "$base/product-version.json"
            $value = [pscustomobject]@{ ready = ($ready.Status -eq 200); ready_status = $ready.Status; identity = $(if ($identity.Status -eq 200) { $identity.Body | ConvertFrom-Json } else { $null }) }
            Write-Result $value $(if ($value.ready) { 0 } else { 1 })
        }
    }
    Enter-SL2Lock $config
    $null = New-SL2Run $config $Action.ToLowerInvariant()
    switch ($Action) {
        'Build' {
            $sha = Resolve-SL2Commit $config $Branch $Commit
            $worktree = New-SL2Worktree $config $sha
            $built = Invoke-SL2Build $config $worktree $sha $Tests
            $manifest = Test-SL2Release $built $sha $worktree
            $published = Publish-SL2Release $config $built $manifest
            Write-Result ([pscustomobject]@{ commit = $sha; version = $manifest.version; tests = $Tests; release = $published; build_folder = $built }) 0
        }
        'Deploy' {
            if ($Tests -eq 'none' -and -not $Release) { Stop-SL2 'A deployment runs tests: use -Tests focused or full (or deploy a release built and tested earlier with -Release).' }
            if ($Release) {
                if (-not (Test-Path -LiteralPath (Join-Path $Release 'build-manifest.json'))) { Stop-SL2 "$Release is not a published release folder." }
                $published = $Release
                $sha = (Get-Content -LiteralPath (Join-Path $Release 'build-manifest.json') -Raw | ConvertFrom-Json).source_sha
            } else {
                $sha = Resolve-SL2Commit $config $Branch $Commit
                if ($DryRun) {
                    $existing = @(Get-ChildItem -LiteralPath $config.ReleasesRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*-$($sha.Substring(0, 7))-win-x64" })
                    if ($existing.Count -eq 0) { Write-Result ([pscustomobject]@{ dry_run = $true; commit = $sha; status = (Get-SL2Status $config); plan = 'build, test, verify, back up, stop, switch, start, verify' }) 0 }
                    $published = $existing[0].FullName
                } else {
                    $worktree = New-SL2Worktree $config $sha
                    $built = Invoke-SL2Build $config $worktree $sha $Tests
                    $manifest = Test-SL2Release $built $sha $worktree
                    $published = Publish-SL2Release $config $built $manifest
                }
            }
            Write-Result (Invoke-SL2Deploy $config $published $sha -DryRun:$DryRun -FirstInstall:$FirstInstall -AdoptService:$AdoptService) 0
        }
        'InstallService' { Install-SL2Service $config -Reconfigure:$Reconfigure; Write-Result (Get-SL2Status $config) 0 }
        'Rollback' { Write-Result (Invoke-SL2Rollback $config $ToRelease) 0 }
        'Recover' { Write-Result (Invoke-SL2Recover $config) 0 }
    }
}
catch {
    $code = if ($_.Exception.PSObject.Properties['ExitCode']) { [int]$_.Exception.ExitCode } else { 1 }
    Write-Host "deployment refused or failed: $($_.Exception.Message)"
    Write-Result ([pscustomobject]@{ error = $_.Exception.Message }) $code
}
finally { Exit-SL2Lock }
