<#
.SYNOPSIS
  Installs, updates and restores AuthLens (.NET server) on this Windows host as the AuthLens Windows service. Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
  Usually started over SSH by scripts/deploy/deploy-windows.sh; it can also be run locally in an elevated PowerShell. Three operations:

    Install         Deploy -FirstInstall: creates the installation root (default C:\ProgramData\AuthLens, protected DACL), builds and verifies a release
                    from the configured repository, installs the AuthLens service with its least-privilege grants and starts it on a new database.
    Update          Deploy: builds, tests and verifies the commit, takes an encrypted pre-deployment backup, stops the service, switches
                    releases\current, starts and verifies readiness, version and commit. Any failure rolls back to the previous release when that
                    is proven safe. The data directory stays in place; only required database migrations run (with their own backup).
    Restore         Restore -Backup <file.slbak> [-KeyFile <recovery key>]: restores an AuthLens or SAP Lens backup into this installation. The
                    key that sealed it is copied into <root>\keys and selected, the server validates the archive, the service restarts and the
                    restore is applied before the database opens; a failure is rolled back by the server. The source installation is untouched.

  Further actions:
    Status          Service model, state, account, command line, linked release, readiness, journal.
    Health          Readiness and identity of the running server.
    Build           Build, test and verify a commit and publish it under releases\ (no service change).
    InstallService  Creates (or with -Reconfigure updates) the AuthLens service from the configuration. Needs -Yes.
    Rollback        Returns to the previous release (or -ToRelease), only when it can open the current data. Needs -Yes.
    Recover         Completes an interrupted deployment (Ctrl+C, a dropped SSH session): returns to the previous release. Needs -Yes.
    AuditAcl        Read-only NTFS audit (by well-known SID) of private state, releases and configuration; exit 2 when anything is unsafe.
    ProtectAcl      Explicit remediation of what AuditAcl reports, after verified ACL inventories in -AclBackupRoot. Needs -Yes and -ApprovedAclRoot.
    RestoreAcl      Restores the ACLs saved by ProtectAcl (-AclBackup <folder>). Needs -Yes and -ApprovedAclRoot.

  Services of earlier products (SAP Lens: sap-lens, SapLens, SapLens2) are never detected, adopted, stopped or changed.

  Configuration: a JSON file that is not committed (-ConfigFile, $env:AUTHLENS_DEPLOY_CONFIG, or C:\ProgramData\AuthLens\config\deploy.json; template
  deploy.example.json). It holds paths, addresses and host names, never a secret. The last output line is 'AUTHLENS-RESULT: <json>'.
  Exit codes: 0 success, 1 failed (nothing changed, or rolled back and ready again), 2 refused before any change, 4 manual action required.

.EXAMPLE
  .\Deploy-AuthLens.ps1 -Action Status
.EXAMPLE
  .\Deploy-AuthLens.ps1 -Action Deploy -FirstInstall -Branch experiment/dotnet-backend -Tests focused -Yes
.EXAMPLE
  .\Deploy-AuthLens.ps1 -Action Restore -Backup D:\transfer\SAP-Lens-manual-<id>.slbak -KeyFile D:\transfer\recovery.key -Yes
#>
[CmdletBinding()]
param(
    [ValidateSet('Status', 'Health', 'Build', 'Deploy', 'InstallService', 'Restore', 'Rollback', 'Recover', 'AuditAcl', 'ProtectAcl', 'RestoreAcl')]
    [string]$Action = 'Status',
    [string]$ConfigFile = '',
    [string]$Branch = '',
    [string]$Commit = '',
    [ValidateSet('focused', 'full', 'none')]
    [string]$Tests = 'focused',
    [string]$Release = '',
    [string]$ToRelease = '',
    [string]$Backup = '',
    [string]$KeyFile = '',
    [string]$AclBackup = '',
    [string]$AclBackupRoot = '',
    [string[]]$ApprovedAclRoot = @(),
    [switch]$DryRun,
    [switch]$FirstInstall,
    [switch]$Reconfigure,
    [switch]$AdoptService,
    [switch]$Yes
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'AuthLens.Deploy.psm1') -Force

function Write-Result($Value, [int]$Code) {
    $Value | ConvertTo-Json -Depth 8 | Write-Host
    Write-Host ('AUTHLENS-RESULT: ' + (@{ exit = $Code; result = $Value } | ConvertTo-Json -Depth 8 -Compress))
    exit $Code
}

function Test-Elevated {
    # $IsWindows does not exist in Windows PowerShell 5.1 (and StrictMode refuses unknown variables): test the edition first.
    if ($PSVersionTable.PSEdition -eq 'Core' -and -not (Get-Variable IsWindows -ValueOnly -ErrorAction SilentlyContinue)) { return $true }
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

try {
    $changing = $Action -in @('Deploy', 'InstallService', 'Restore', 'Rollback', 'Recover', 'ProtectAcl', 'RestoreAcl') -and -not $DryRun
    if ($changing -and -not $Yes) { Stop-AL "$Action changes the service or its permissions; repeat with -Yes after reviewing -Action Status or -Action AuditAcl (or -DryRun)." }
    $config = Read-AuthLensSettings $ConfigFile
    # NTFS audit (read-only) of the installation's private state, releases and configuration. Exit code 0 when no broad principal can read private
    # state or write anywhere it matters, 2 otherwise.
    if ($Action -eq 'AuditAcl' -or ($Action -eq 'ProtectAcl' -and $DryRun)) {
        $report = Get-ALAclReport (Get-ALAclPlan $config)
        Write-Result $report $(if ($report.safe) { 0 } else { 2 })
    }
    if ($changing -and -not (Test-Elevated)) { Stop-AL "$Action needs an elevated session (an administrator account over SSH, or Run as administrator)." }
    switch ($Action) {
        'Status' { Write-Result (Get-ALStatus $config) 0 }
        'Health' {
            $base = "https://$($config.ListenAddress):$($config.Port)"
            $ready = Invoke-ALConfiguredHttp $config '/health/ready'; $identity = Invoke-ALConfiguredHttp $config '/product-version.json'
            $value = [pscustomobject]@{ ready = ($ready.Status -eq 200); ready_status = $ready.Status; identity = $(if ($identity.Status -eq 200) { $identity.Body | ConvertFrom-Json } else { $null }) }
            Write-Result $value $(if ($value.ready) { 0 } else { 1 })
        }
    }
    # Install, update and restore create or fill the installation; recovery and ACL actions must work on an installation as it is.
    if ($Action -in @('Build', 'Deploy', 'InstallService', 'Restore') -and -not $DryRun) { Initialize-ALInstallation $config }
    Enter-ALLock $config
    $null = New-ALRun $config $Action.ToLowerInvariant()
    switch ($Action) {
        'Build' {
            $sha = Resolve-ALCommit $config $Branch $Commit
            $worktree = New-ALWorktree $config $sha
            $built = Invoke-ALBuild $config $worktree $sha $Tests
            $manifest = Test-ALRelease $built $sha $worktree
            $published = Publish-ALRelease $config $built $manifest
            Write-Result ([pscustomobject]@{ commit = $sha; version = $manifest.version; tests = $Tests; release = $published; build_folder = $built }) 0
        }
        'Deploy' {
            if ($Tests -eq 'none' -and -not $Release) { Stop-AL 'A deployment runs tests: use -Tests focused or full (or deploy a release built and tested earlier with -Release).' }
            if ($Release) {
                if (-not (Test-Path -LiteralPath (Join-Path $Release 'build-manifest.json'))) { Stop-AL "$Release is not a published release folder." }
                $check = Test-ALPublishedRelease $Release
                if (-not $check.Verified) { Stop-AL "$Release does not verify as a server package (verify-release.ps1 -Scope Server); nothing was deployed." }
                $published = $Release
                $sha = (Get-Content -LiteralPath (Join-Path $Release 'build-manifest.json') -Raw | ConvertFrom-Json).source_sha
            } else {
                $sha = Resolve-ALCommit $config $Branch $Commit
                if ($DryRun) {
                    $existing = @(Get-ChildItem -LiteralPath $config.ReleasesRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*-$($sha.Substring(0, 7))-win-x64" })
                    if ($existing.Count -eq 0) { Write-Result ([pscustomobject]@{ dry_run = $true; commit = $sha; status = (Get-ALStatus $config); plan = 'build, test, verify, back up, stop, switch, start, verify' }) 0 }
                    $published = $existing[0].FullName
                } else {
                    $worktree = New-ALWorktree $config $sha
                    $built = Invoke-ALBuild $config $worktree $sha $Tests
                    $manifest = Test-ALRelease $built $sha $worktree
                    $published = Publish-ALRelease $config $built $manifest
                }
            }
            Write-Result (Invoke-ALDeploy $config $published $sha -DryRun:$DryRun -FirstInstall:$FirstInstall -AdoptService:$AdoptService) 0
        }
        'InstallService' { Install-ALService $config -Reconfigure:$Reconfigure; Write-Result (Get-ALStatus $config) 0 }
        'Restore' { Write-Result (Invoke-ALRestore $config $Backup $KeyFile) 0 }
        'Rollback' { Write-Result (Invoke-ALRollback $config $ToRelease) 0 }
        'Recover' { Write-Result (Invoke-ALRecover $config) 0 }
        'ProtectAcl' {
            if (-not $ConfigFile) { Stop-AL 'ProtectAcl requires an explicit -ConfigFile.' }
            $backupRoot = if ($AclBackupRoot) { $AclBackupRoot } else { Join-AL $config.WorkRoot 'acl-backups' }
            $result = Invoke-ALProtectAcl $config $backupRoot $ApprovedAclRoot
            Write-Result $result $(if ($result.after.safe) { 0 } else { 2 })
        }
        'RestoreAcl' {
            if (-not $AclBackup) { Stop-AL 'RestoreAcl requires -AclBackup <WorkRoot\acl-backups\<UTC time>> written by ProtectAcl.' }
            Write-Result (Invoke-ALRestoreAcl $AclBackup $ApprovedAclRoot) 0
        }
    }
}
catch {
    $code = if ($_.Exception.PSObject.Properties['ExitCode']) { [int]$_.Exception.ExitCode } else { 1 }
    Write-Host "deployment refused or failed: $($_.Exception.Message)"
    Write-Result ([pscustomobject]@{ error = $_.Exception.Message }) $code
}
finally { Exit-ALLock }
