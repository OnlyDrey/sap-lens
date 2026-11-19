<#
.SYNOPSIS
  Builds, validates and deploys AuthLens (.NET server) on this Windows host as the sap-lens Windows service (test server). Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
  Usually started over SSH by scripts/deploy/deploy-windows.sh; it can also be run locally in an elevated PowerShell. Actions:

    PlanCanonicalTarget Read-only conversion proposal from explicit source/target files to canonical naming. Writes neither file.
    Status          Service model (windows-service, unmanaged-process or none), state, account, command line, linked release, readiness, journal.
    Build           Fetch the branch, lock the exact commit, build it in an isolated worktree with the release builder and the selected tests,
                    verify the release (manifest, SHA-256, commit, version) and copy it to a versioned folder under ReleasesRoot.
    Deploy          Build (unless -Release names an already published folder), then: confirm service and data state, refuse data written by a
                    newer build, create and verify an encrypted pre-deployment backup, stop the service, switch the 'current' link, start,
                    verify readiness, version and commit. Any failure rolls back to the previous release when that is proven safe.
                    -DryRun resolves the commit and prints the plan without building, backing up or touching the service. Needs -Yes.
    InstallService  Creates (or with -Reconfigure updates) the sap-lens service from the configuration. Needs -Yes.
                    An existing service of an earlier installation (SapLens2) is detected and used; a second service is never created.
    PreflightMigration Read-only inspection of explicit source/target configurations, release, data, TLS, keys, ACLs and recovery state.
                    Requires -InspectorExecutable from a newly verified Windows release; no executable or database fallback is selected.
    MigrateService  Journaled directory and service cutover to sap-lens; preserves the source release, network settings and account requirements.
                    Takes verified backups, stages private state, and retains SapLens2 stopped/disabled. Needs -TargetConfigFile,
                    -InspectorExecutable and -Yes. -DryRun performs only preflight. No automatic deletion of either installation.
    VerifyMigration Verifies the completed cutover and current release (including later Build & Replace deployments).
    RecoverMigration Recovers interrupted migration state when no writes would be discarded; otherwise requires manual recovery. Needs -Yes.
    RollbackMigration Explicitly requests migration rollback with the same data-preservation proof. Needs -Yes.
                    Deploy -AdoptService brings a hand-installed service under managed releases without renaming it.
    Rollback        Returns to the previous release (or -ToRelease), only when it can open the current data. Needs -Yes.
    Recover         Completes an interrupted deployment (Ctrl+C, a dropped SSH session): returns to the previous release. Needs -Yes.
    Health          Readiness and identity of the running server.
    AuditAcl        Read-only NTFS audit (by well-known SID) of private state, releases and configuration, and with -TargetConfigFile of the
                    parents of the migration targets. Lists each broad principal with its rights; exit 2 when anything is unsafe.
    ProtectAcl      Explicit remediation of what AuditAcl reports. Saves verified UTF-16 ACL inventories into a disjoint -AclBackupRoot first,
                    then sets protected DACLs (SYSTEM, Administrators, the service's virtual account), removes broad grants, resets
                    descendants to inherit and creates missing target parents protected. Never changes ProgramData, Program Files, the
                    Windows folder, user roots or drive roots, and never stops the service. -DryRun prints the audit. Needs -Yes and explicit -ApprovedAclRoot.
    RestoreAcl      Restores the ACLs saved by ProtectAcl (-AclBackup <folder>), with checksums, path bounds and DACL verification. Needs -Yes and -ApprovedAclRoot.

  Configuration: a JSON file that is not committed (-ConfigFile, $env:SAPLENS_DEPLOY_CONFIG, $env:SAPLENS2_DEPLOY_CONFIG,
  C:\sap-lens\deploy\deploy.local.json, C:\saplens\deploy.local.json or C:\saplens2\deploy.local.json, the first that is set or exists; template deploy.example.json). It holds paths,
  addresses and host names, never a secret. The last output line is 'SAPLENS-RESULT: <json>'.
  Exit codes: 0 success, 1 failed (nothing changed, or rolled back and ready again), 2 refused before any change, 4 manual action required.

.EXAMPLE
  .\Deploy-AuthLens.ps1 -Action Status
.EXAMPLE
  .\Deploy-AuthLens.ps1 -Action Deploy -Branch experiment/dotnet-backend -Tests focused -Yes
#>
[CmdletBinding()]
param(
    [ValidateSet('Status', 'PlanCanonicalTarget', 'Build', 'Deploy', 'InstallService', 'PreflightMigration', 'MigrateService', 'VerifyMigration', 'RecoverMigration', 'RollbackMigration', 'Rollback', 'Recover', 'Health', 'AuditAcl', 'ProtectAcl', 'RestoreAcl')]
    [string]$Action = 'Status',
    [string]$ConfigFile = '',
    [string]$TargetConfigFile = '',
    [string]$InspectorExecutable = '',
    [string]$Branch = '',
    [string]$Commit = '',
    [ValidateSet('focused', 'full', 'none')]
    [string]$Tests = 'focused',
    [string]$Release = '',
    [string]$ToRelease = '',
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
    Write-Host ('SAPLENS-RESULT: ' + (@{ exit = $Code; result = $Value } | ConvertTo-Json -Depth 8 -Compress))
    exit $Code
}

function Test-Elevated {
    # $IsWindows does not exist in Windows PowerShell 5.1 (and StrictMode refuses unknown variables): test the edition first.
    if ($PSVersionTable.PSEdition -eq 'Core' -and -not (Get-Variable IsWindows -ValueOnly -ErrorAction SilentlyContinue)) { return $true }
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

try {
    $changing = $Action -in @('Deploy', 'InstallService', 'MigrateService', 'RecoverMigration', 'RollbackMigration', 'Rollback', 'Recover', 'ProtectAcl', 'RestoreAcl') -and -not $DryRun
    if ($changing -and -not $Yes) { Stop-SL2 "$Action changes the service or its permissions; repeat with -Yes after reviewing -Action Status or -Action AuditAcl (or -DryRun)." }
    $config = Read-AuthLensSettings $ConfigFile
    if ($Action -eq 'PlanCanonicalTarget') {
        if (-not $ConfigFile -or -not $TargetConfigFile) { Stop-SL2 'PlanCanonicalTarget requires explicit source and target configuration files.' }
        Write-Result (Get-SL2CanonicalTargetPlan $config (Read-AuthLensSettings $TargetConfigFile)) 0
    }
    # NTFS audit (read-only): the source configuration's private state, releases and configuration, plus the parents of the target roots when a
    # target configuration is given. Exit code 0 when no broad principal can read private state or write anywhere it matters, 2 otherwise.
    if ($Action -eq 'AuditAcl' -or ($Action -eq 'ProtectAcl' -and $DryRun)) {
        $target = if ($TargetConfigFile) { Read-AuthLensSettings $TargetConfigFile } else { $null }
        $report = Get-SL2AclReport (Get-SL2AclPlan $config $target)
        Write-Result $report $(if ($report.safe) { 0 } else { 2 })
    }
    if ($Action -eq 'PreflightMigration' -or ($Action -eq 'MigrateService' -and $DryRun)) {
        if (-not $ConfigFile -or -not $TargetConfigFile) { Stop-SL2 'Migration requires explicit -ConfigFile and -TargetConfigFile.' }
        $preflight = Get-SL2MigrationPreflight $config (Read-AuthLensSettings $TargetConfigFile) $InspectorExecutable
        Write-Result $preflight $(if ($preflight.safe) { 0 } else { 2 })
    }
    if ($Action -eq 'VerifyMigration') { Write-Result (Test-SL2MigrationComplete $config) 0 }
    if ($Action -in @('RecoverMigration', 'RollbackMigration') -and $DryRun) { Stop-SL2 'Use Status or VerifyMigration for read-only inspection. Migration recovery has no DryRun mutation path.' }
    if ($changing -and -not (Test-Elevated)) { Stop-SL2 "$Action needs an elevated session (an administrator account over SSH, or Run as administrator)." }
    switch ($Action) {
        'Status' { Write-Result (Get-SL2Status $config) 0 }
        'Health' {
            $base = "https://$($config.ListenAddress):$($config.Port)"
            $ready = Invoke-SL2ConfiguredHttp $config '/health/ready'; $identity = Invoke-SL2ConfiguredHttp $config '/product-version.json'
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
                $check = Test-SL2PublishedRelease $Release
                if (-not $check.Verified) { Stop-SL2 "$Release does not verify as a server package (verify-release.ps1 -Scope Server); nothing was deployed." }
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
        'MigrateService' {
            if (-not $ConfigFile -or -not $TargetConfigFile) { Stop-SL2 'Migration requires explicit -ConfigFile and -TargetConfigFile.' }
            Write-Result (Invoke-SL2MigrateService $config (Read-AuthLensSettings $TargetConfigFile) $InspectorExecutable) 0
        }
        'RecoverMigration' { Write-Result (Invoke-SL2MigrationRecovery $config) 0 }
        'RollbackMigration' { Write-Result (Invoke-SL2MigrationRecovery $config -Rollback) 0 }
        'Rollback' { Write-Result (Invoke-SL2Rollback $config $ToRelease) 0 }
        'Recover' { Write-Result (Invoke-SL2Recover $config) 0 }
        'ProtectAcl' {
            if (-not $ConfigFile) { Stop-SL2 'ProtectAcl requires an explicit -ConfigFile (and -TargetConfigFile to prepare migration targets).' }
            $target = if ($TargetConfigFile) { Read-AuthLensSettings $TargetConfigFile } else { $null }
            $backupRoot = if ($AclBackupRoot) { $AclBackupRoot } else { Join-SL2 $config.WorkRoot 'acl-backups' }
            $result = Invoke-SL2ProtectAcl $config $target $backupRoot $ApprovedAclRoot
            Write-Result $result $(if ($result.after.safe) { 0 } else { 2 })
        }
        'RestoreAcl' {
            if (-not $AclBackup) { Stop-SL2 'RestoreAcl requires -AclBackup <WorkRoot\acl-backups\<UTC time>> written by ProtectAcl.' }
            Write-Result (Invoke-SL2RestoreAcl $AclBackup $ApprovedAclRoot) 0
        }
    }
}
catch {
    $code = if ($_.Exception.PSObject.Properties['ExitCode']) { [int]$_.Exception.ExitCode } else { 1 }
    Write-Host "deployment refused or failed: $($_.Exception.Message)"
    Write-Result ([pscustomobject]@{ error = $_.Exception.Message }) $code
}
finally { Exit-SL2Lock }
