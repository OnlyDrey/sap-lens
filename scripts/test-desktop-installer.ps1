# Native Windows acceptance: compile a test-only identity, never execute production Setup.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Installer,[Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE=1
if ($env:OS -ne 'Windows_NT') { throw 'Native installer acceptance requires Windows.' }
$root=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'testing/windows-app-control-evidence.ps1')
$python=Join-Path $root 'backend/build/python-env/Scripts/python.exe'
$helper=Join-Path $root 'scripts/build_system/installer_acceptance.py'
$productionKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{5DB5BC51-A860-44CA-93CA-09AE85812DF0}_is1'
if (Test-Path -LiteralPath $productionKey) {
    Write-Host 'Existing registered SAP Lens remains protected; production Setup will not be executed.'
}
# Installation is supported alongside a registered copy, not alongside a running writer.
# Never stop another instance or bypass the application's production mutex.
$mutex=$null
if ([Threading.Mutex]::TryOpenExisting('Local\SAPLensDesktop',[ref]$mutex)) {
    $mutex.Dispose()
    throw 'Close the running SAP Lens window and background/tray process before acceptance. The existing installation will not be modified.'
}
$names=@('SAP_LENS_CONFIG_DIR','SAP_LENS_BACKUP_DIR','SAP_LENS_BACKUP_KEY_FILE','SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE','SAP_LENS_INSTALLER_ACCEPTANCE_ROOT','RUNNER_TEMP','DATA_CSV_PATH','USER_CSV_PATH','EMPLOYEE_CSV_PATH','SOD_CSV_PATH')
$previous=@{}
foreach ($name in $names) { $previous[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
$script:InstallerEvidence=$null
$plan=$null; $testInstaller=$null; $primary=$null; $primaryStage=$null; $completed=$false; $proof=$null
$cleanupErrors=New-Object 'System.Collections.Generic.List[string]'
$stage='source installer verification'
function Invoke-Plan([string]$Operation) {
    $json=& $python $helper $Operation --plan $plan.plan_path
    if ($LASTEXITCODE -ne 0) { throw "Acceptance plan operation '$Operation' failed." }
    return ($json | ConvertFrom-Json)
}
function Get-InstallerBlockEvidence([string]$Path,[datetime]$StartedAt,[datetime]$FinishedAt) {
    # Code Integrity events 3077/3033 for this installer or for the payload Setup extracts to its temporary folder, inside a bounded window.
    $query=Get-CodeIntegrityEvents $StartedAt.AddSeconds(-2) $FinishedAt.AddSeconds(2)
    $selected=Select-CorrelatedCodeIntegrityEvents $query.Events $Path $null $StartedAt.AddSeconds(-2) $FinishedAt.AddSeconds(2) -InstallerTempPayload
    return @{ Records=@($selected.Records); Limitations=@($query.Limitations)+@($selected.Limitations) }
}
function Get-SetupLogTail([string]$LogPath) {
    if (-not $LogPath -or -not (Test-Path -LiteralPath $LogPath -PathType Leaf)) { return '(Setup log not found)' }
    try {
        $replacements=@{}
        foreach ($pair in @(@($env:LOCALAPPDATA,'%LOCALAPPDATA%'),@($env:USERPROFILE,'%USERPROFILE%'))) { if ($pair[0]) { $replacements[$pair[0]]=$pair[1] } }
        return ((ConvertTo-SafeLogTail (Get-Content -LiteralPath $LogPath -Tail 40 -ErrorAction Stop) $replacements) -join "`n")
    } catch { return "(Setup log unreadable: $($_.Exception.GetType().Name))" }
}
function Invoke-OwnedExecutable([string]$Path,[string[]]$Arguments,[string]$LogPath='') {
    $process=$null; $creation=$null; $startedAt=Get-Date
    try {
        try { $process=Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru -ErrorAction Stop } catch { $creation=$_.Exception }
        $finishedAt=Get-Date
        if ($creation -or $process.ExitCode -ne 0) {
            $exit=if ($creation) { 'not started' } else { [string]$process.ExitCode }
            $code=Get-ExceptionNativeErrorCode $creation
            $evidence=Get-InstallerBlockEvidence $Path $startedAt $finishedAt
            $message="Native process failed during '$stage' (exit $exit)."
            # Blocked only with a documented policy error code or a correlated Code Integrity event; a non-zero exit alone proves nothing about policy.
            if ((Get-PolicyBlockName $code) -or $evidence.Records.Count -gt 0) {
                $script:InstallerEvidence=@{ native_error_code=$code; correlated_events=(ConvertTo-EvidenceRecords $evidence.Records); limitations=@($evidence.Limitations) }
                $message+=' NATIVE ACCEPTANCE BLOCKED [environment_policy_blocked]: Windows App Control refused to run an unsigned installer component, so installer acceptance verified nothing. Do not disable or bypass the policy.'
                if ($evidence.Records.Count) { $message+=' Events: '+((ConvertTo-EvidenceRecords $evidence.Records | ForEach-Object { "event_id=$($_.event_id); policy_id=$($_.policy_id); correlation=$($_.correlation)" }) -join '; ')+'.' }
            }
            if ($evidence.Limitations.Count) { $message+=' Evidence limits: '+($evidence.Limitations -join ' ') }
            $message+=" Setup log (last lines): "+(Get-SetupLogTail $LogPath)
            throw $message
        }
    } finally { if ($process) { $process.Dispose() } }
}
function Install-TestPackage([string]$LogName) {
    $null=Invoke-Plan 'state'
    if ($plan.test_id -eq $plan.production_id -or $testInstaller -eq $Installer -or
        (Get-FileHash -LiteralPath $testInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne $proof.installer_sha256) {
        throw 'Refusing production or changed installer execution; existing registered SAP Lens must not be changed.'
    }
    Invoke-OwnedExecutable $testInstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',('/DIR="'+$plan.application+'"'),('/LOG="'+(Join-Path $plan.root $LogName)+'"')) (Join-Path $plan.root $LogName)
    $null=Invoke-Plan 'registered'
    $null=Invoke-Plan 'verify-production'
}
function Assert-InstallRefusedWithoutKey([string]$LogName) {
    # The pre-upgrade backup is always encrypted. Without a protected key Setup must refuse BEFORE changing anything, never fall back to an
    # unencrypted backup and never skip the backup. A refusal caused by App Control does not count as this proof.
    $null=Invoke-Plan 'state'
    if ($plan.test_id -eq $plan.production_id -or $testInstaller -eq $Installer -or
        (Get-FileHash -LiteralPath $testInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne $proof.installer_sha256) {
        throw 'Refusing production or changed installer execution; existing registered SAP Lens must not be changed.'
    }
    & $python (Join-Path $root 'backend/maintenance.py') check-backup-key --data $plan.data | Out-Null
    if ($LASTEXITCODE -eq 0) { throw 'Precondition failed: a backup key is already configured for the isolated data directory.' }
    $startedAt=Get-Date
    $process=Start-Process -FilePath $testInstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',('/DIR="'+$plan.application+'"'),('/LOG="'+(Join-Path $plan.root $LogName)+'"')) -Wait -PassThru -ErrorAction Stop
    $evidence=Get-InstallerBlockEvidence $testInstaller $startedAt (Get-Date)
    if ($evidence.Records.Count) {
        $script:InstallerEvidence=@{ native_error_code=$null; correlated_events=(ConvertTo-EvidenceRecords $evidence.Records); limitations=@($evidence.Limitations) }
        throw "NATIVE ACCEPTANCE BLOCKED [environment_policy_blocked]: App Control events correlate with the installer, so the missing-key refusal could not be verified. Setup log (last lines): "+(Get-SetupLogTail (Join-Path $plan.root $LogName))
    }
    if ($process.ExitCode -eq 0) { throw 'Setup succeeded without a protected backup key; the encrypted pre-upgrade backup is required.' }
    if (Test-Path -LiteralPath (Join-Path $plan.application 'SAP-Lens.exe')) { throw 'A refused installation left an application executable behind.' }
    if ([IO.File]::ReadAllText($settings) -ne $before) { throw 'A refused installation changed existing data.' }
    if (@(Get-ChildItem -LiteralPath $plan.backups -Filter '*.tar.gz' -ErrorAction SilentlyContinue).Count -ne 0) { throw 'A refused installation created a backup archive; the key requirement was bypassed.' }
    $null=Invoke-Plan 'unregistered'
    $null=Invoke-Plan 'verify-production'
}
function Uninstall-TestPackage {
    $null=Invoke-Plan 'registered'
    $uninstaller=Join-Path $plan.application 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf) -or
        ((Get-Item -LiteralPath $uninstaller -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Owned test uninstaller missing or linked; workspace retained.' }
    Invoke-OwnedExecutable $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
    $null=Invoke-Plan 'unregistered'
}
try {
    & $python (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') --installer $Installer
    if ($LASTEXITCODE -ne 0) { throw 'Source production installer resource verification failed.' }
    $stage='prepare isolated identity and production snapshot'
    $testParent=if ($previous['RUNNER_TEMP']) { $previous['RUNNER_TEMP'] } else { [IO.Path]::GetTempPath() }
    $json=& $python $helper prepare --installer $Installer --report $Report --parent $testParent
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare an isolated acceptance workspace.' }
    $plan=$json | ConvertFrom-Json
    $Report=$plan.report
    foreach ($name in @('DATA_CSV_PATH','USER_CSV_PATH','EMPLOYEE_CSV_PATH','SOD_CSV_PATH')) { [Environment]::SetEnvironmentVariable($name,'','Process') }
    $env:SAP_LENS_CONFIG_DIR=$plan.data; $env:SAP_LENS_BACKUP_DIR=$plan.backups
    $env:SAP_LENS_INSTALLER_ACCEPTANCE_ROOT=$plan.root; $env:RUNNER_TEMP=$plan.root
    foreach ($name in @('SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE')) { [Environment]::SetEnvironmentVariable($name,$null,'Process') }
    New-Item -ItemType Directory -Path $plan.data | Out-Null
    $settings=Join-Path $plan.data 'settings.json'
    [IO.File]::WriteAllText($settings,'{"schema_version":3,"data_csv_path":""}',[Text.UTF8Encoding]::new($false))
    $before=[IO.File]::ReadAllText($settings)
    $stage='compile test-only installer'
    & (Join-Path $root 'scripts/build-desktop-installer.ps1') -OutputDirectory $plan.root -AcceptancePlan $plan.plan_path
    if ($LASTEXITCODE -ne 0) { throw 'Test-only installer compilation failed.' }
    $testInstaller=Join-Path $plan.root ('SAP-Lens-Acceptance-'+$plan.test_id+'-Setup.exe')
    $proof=Get-Content -LiteralPath (Join-Path $plan.root 'compiled-acceptance.json') -Raw | ConvertFrom-Json
    if ($proof.test_id -ne $plan.test_id -or $proof.production_installer_sha256 -ne $plan.installer_sha256 -or
        $proof.payload_sha256 -ne $plan.payload_sha256 -or $proof.recipe_sha256 -ne $plan.recipe_sha256) { throw 'Isolated compiler proof differs from the acceptance plan.' }
    & $python (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') --installer $testInstaller --acceptance-id $plan.test_id
    if ($LASTEXITCODE -ne 0) { throw 'Test-only installer identity resource differs; execution refused.' }
    $null=Invoke-Plan 'verify-production'
    $stage='refusal without a protected backup key'
    $env:SAP_LENS_BACKUP_KEY_FILE=''
    Assert-InstallRefusedWithoutKey 'refused.log'
    $stage='provision isolated backup key'
    $keyDirectory=Join-Path $plan.root 'keys'
    New-Item -ItemType Directory -Path $keyDirectory | Out-Null
    $keyFile=Join-Path $keyDirectory 'backup.key'
    & $python (Join-Path $root 'backend/maintenance.py') init-backup-key --data $plan.data --output $keyFile | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The isolated backup key could not be created; installer acceptance cannot exercise the encrypted pre-upgrade backup.' }
    $env:SAP_LENS_BACKUP_KEY_FILE=$keyFile
    $stage='first isolated installation'
    Install-TestPackage 'setup.log'
    $stage='installed payload hash'
    $installed=Join-Path $plan.application 'SAP-Lens.exe'
    if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.payload_sha256) { throw 'Installed payload differs from the canonically verified EXE.' }
    $stage='isolated reinstallation and backups'
    Install-TestPackage 'reinstall.log'
    if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.payload_sha256 -or
        [IO.File]::ReadAllText($settings) -ne $before -or @(Get-ChildItem -LiteralPath $plan.backups -Filter '*.tar.gz').Count -lt 2) { throw 'Reinstallation changed payload/settings or failed to preserve private backups.' }
    $stage='installed executable lifecycle'
    & (Join-Path $root 'scripts/test-windows-exe.ps1') -ExecutablePath $installed
    if ($LASTEXITCODE -ne 0) { throw 'Installed EXE lifecycle smoke failed.' }
    $stage='isolated uninstall and data preservation'
    Uninstall-TestPackage
    if ((Test-Path -LiteralPath $installed) -or [IO.File]::ReadAllText($settings) -ne $before -or -not (Test-Path -LiteralPath $plan.backups)) { throw 'Uninstall changed private data or left the application installed.' }
    $null=Invoke-Plan 'verify-production'
    $completed=$true
} catch { $primary=$_.Exception; $primaryStage=$stage } finally {
    if ($plan) {
        try {
            $stageBeforeCleanup=$stage
            $stage='owned installation cleanup'
            $state=Invoke-Plan 'state'
            if ($state.test_registered) { Uninstall-TestPackage }
            else { $null=Invoke-Plan 'unregistered' }
            $null=Invoke-Plan 'verify-production'
            if ($completed -and -not $primary) { $null=Invoke-Plan 'cleanup' }
            $stage=$stageBeforeCleanup
        } catch { $cleanupErrors.Add($_.Exception.Message) }
    }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
}
if ($primary -or $cleanupErrors.Count -or -not $completed) {
    $global:LASTEXITCODE=1
    $failedStage=if ($primaryStage) { $primaryStage } else { $stage }
    # One machine-readable result, kept apart from the success receipt (which a failed or blocked run never writes).
    $verdict=if ($script:InstallerEvidence) { @{ status='blocked'; reason='environment_policy_blocked' } } else { @{ status='failed'; reason='installer_acceptance_failed' } }
    $installerResult=@{ kind='windows-installer-acceptance'; status=$verdict.status; reason=$verdict.reason; stage=$failedStage; cleanup_errors=$cleanupErrors.Count }
    if ($script:InstallerEvidence) { foreach ($key in $script:InstallerEvidence.Keys) { $installerResult[$key]=$script:InstallerEvidence[$key] } }
    Write-NativeResult (Join-Path $root 'backend/build/native-installer-result.json') $installerResult
    $message="Installer acceptance failed during '$failedStage'. "
    if ($primary) { $message+='Primary: '+$primary.Message+'. ' }
    if ($cleanupErrors.Count) { $message+='Cleanup: '+($cleanupErrors -join '; ')+'. ' }
    if ($plan) { $message+='Retained workspace: '+$plan.root+'; test AppId: '+$plan.test_id }
    throw $message
}
$identity=$plan.identity
$result=@{schema=1;identity=$identity;installer_sha256=$plan.installer_sha256;payload_sha256=$plan.payload_sha256;signing='disabled';
    acceptance_mode='isolated-app-id';test_app_id=$plan.test_id;production_app_id=$plan.production_id;executed_installer_sha256=$proof.installer_sha256;
    recipe_sha256=$plan.recipe_sha256;production_unchanged=$true;cleanup_complete=$true;
    native_installer_smoke='passed: isolated-AppId install/reinstall/installed-EXE-lifecycle/uninstall/data-preservation/production-invariance/cleanup'}
$stage='acceptance receipt'
$stream=$null; $writer=$null
try {
    [IO.Directory]::CreateDirectory((Split-Path $Report -Parent)) | Out-Null
    $stream=[IO.File]::Open($Report,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($false))
    $writer.Write(($result | ConvertTo-Json -Depth 8))
    $writer.Flush()
} catch {
    $global:LASTEXITCODE=1
    throw "Installer acceptance failed during '$stage': could not write the new receipt at $Report. The test installation was cleaned up."
} finally {
    if ($writer) { $writer.Dispose() } elseif ($stream) { $stream.Dispose() }
}
Write-Host 'Isolated native installer acceptance passed; production installation/data unchanged. Production upgrade, clean-PC and enterprise-policy acceptance remain separate.'
$global:LASTEXITCODE=0
