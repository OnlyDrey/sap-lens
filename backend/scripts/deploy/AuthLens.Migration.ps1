# Part of AuthLens.Deploy, dot-sourced into the same module. No operations run on import.
# Migration always takes explicit source/target configurations; ordinary deployment never calls it.
function Test-SL2PathTree([string]$Path) {
    $item = [System.IO.Path]::GetFullPath($Path)
    while ($item) {
        if (Test-Path -LiteralPath $item) {
            if ((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-SL2 'Migration paths must not traverse reparse points.' }
        }
        $item = [IO.Path]::GetDirectoryName($item)
    }
}

function Get-SL2TreeFiles([string]$Root) {
    Test-SL2PathTree $Root
    foreach ($item in Get-ChildItem -LiteralPath $Root -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-SL2 'Migration sources must not contain reparse points.' }
        if ($item.PSIsContainer) { Get-SL2TreeFiles $item.FullName } else { $item }
    }
}

function Test-SL2PathOverlap([string]$Left, [string]$Right) {
    $a = [IO.Path]::GetFullPath($Left).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $b = [IO.Path]::GetFullPath($Right).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $a.StartsWith($b, [StringComparison]::OrdinalIgnoreCase) -or $b.StartsWith($a, [StringComparison]::OrdinalIgnoreCase)
}

function Get-SL2MigrationKey($Source) {
    # An environment override could make a copied pointer select a different key after cutover. SAP_LENS_V2_BACKUP_KEY_FILE is the name used
    # before the rename (migration-only detection: a host still carrying it is refused until it is reconciled).
    $overrides = foreach ($name in 'SAP_LENS_BACKUP_KEY_FILE', 'SAP_LENS_V2_BACKUP_KEY_FILE') {
        [Environment]::GetEnvironmentVariable($name); [Environment]::GetEnvironmentVariable($name, 'Machine')
    }
    if (@($overrides | Where-Object { $_ }).Count -gt 0) {
        Stop-SL2 'Remove and reconcile backup-key environment overrides before migration; use the data directory key pointer.'
    }
    $pointer = Join-SL2 $Source.DataDirectory 'backup-key-location.json'
    $location = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
    if ($location.schema -ne 1) { Stop-SL2 'Unsupported host backup-key pointer.' }
    $key = $location.path
    if (-not [IO.Path]::IsPathRooted($key) -or -not (Test-Path -LiteralPath $key -PathType Leaf)) { Stop-SL2 'The host backup key pointer is missing or invalid.' }
    Test-SL2PathTree $key
    if (Test-SL2PathOverlap $Source.DataDirectory $key) { Stop-SL2 'The host backup key must be outside data.' }
    try { if ([Convert]::FromBase64String([IO.File]::ReadAllText($key).Trim()).Length -ne 32) { throw 'invalid' } }
    catch { Stop-SL2 'The configured host recovery key is invalid.' }
    $key
}

function Test-SL2MigrationTls($Source) {
    $certificate = $null
    try {
        $password = [IO.File]::ReadAllText($Source.CertificatePasswordFile).TrimEnd([char[]]"`r`n")
        $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($Source.CertificatePath, $password, [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
        if (-not $certificate.HasPrivateKey -or $certificate.NotBefore -gt [DateTime]::Now -or $certificate.NotAfter -le [DateTime]::Now) { throw 'invalid' }
    } catch { Stop-SL2 'TLS certificate or password is invalid, expired or lacks its private key. No secrets were changed.' }
    finally { $password = $null; if ($certificate) { $certificate.Dispose() } }
}

function Test-SL2MigrationEnvironment([string]$ServiceName) {
    $machine = [Environment]::GetEnvironmentVariables('Machine')
    foreach ($name in $machine.Keys) { if ($name -like 'SAP_LENS_*') { Stop-SL2 'Machine-level SAP Lens environment overrides require manual reconciliation before migration.' } }
    $service = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName" -ErrorAction Stop
    if ($service.PSObject.Properties['Environment'] -and @($service.Environment).Count) { Stop-SL2 'Service-specific environment overrides require manual reconciliation before migration.' }
}

function Assert-SL2MigrationPair($Source, $Target) {
    if ($Source.ServiceName -eq 'SapLens2' -and $Target.ServiceName -ceq 'sap-lens') { return }
    if ($Source.ServiceName -cmatch '^AuthLens\.Acceptance-([a-f0-9]{32})-old$' -and
        $Target.ServiceName -ceq "AuthLens.Acceptance-$($Matches[1])-new") { return }
    Stop-SL2 'Select the explicit SapLens2/sap-lens pair, or matching unique AuthLens.Acceptance-<32 lowercase hex>-old/new test services.'
}

function Get-SL2FreeSpace([string]$Path) {
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))
    $drive = [IO.DriveInfo]::new($root)
    if ($drive.DriveFormat -ne 'NTFS') { Stop-SL2 'Migration requires local NTFS volumes.' }
    $drive.AvailableFreeSpace
}

function Write-SL2MigrationJournal($Journal) {
    $Journal.updated = [DateTime]::UtcNow.ToString('o')
    foreach ($root in @($Journal.source.WorkRoot, $Journal.target.WorkRoot)) {
        if ($root -eq $Journal.target.WorkRoot -and (-not $Journal.PSObject.Properties['target_prepared'] -or -not $Journal.target_prepared)) { continue }
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        Test-SL2PathTree $root
        $path = Join-SL2 $root 'migration-journal.json'
        $temporary = "$path.next"
        $bytes = [Text.Encoding]::UTF8.GetBytes(($Journal | ConvertTo-Json -Depth 16))
        $stream = [IO.File]::Open($temporary, 'Create', 'Write', 'None')
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temporary, $path, "$path.previous") }
        else { [IO.File]::Move($temporary, $path) }
    }
}

function Read-SL2MigrationJournal($Config) {
    $path = Join-SL2 $Config.WorkRoot 'migration-journal.json'
    if (-not (Test-Path -LiteralPath $path)) { return }
    $record = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    foreach ($root in @($record.source.WorkRoot, $record.target.WorkRoot)) {
        if ($root -eq $record.target.WorkRoot -and (-not $record.PSObject.Properties['target_prepared'] -or -not $record.target_prepared)) { continue }
        $mirror = Join-SL2 $root 'migration-journal.json'
        if ($mirror -eq $path -or -not (Test-Path -LiteralPath $mirror)) { continue }
        $other = Get-Content -LiteralPath $mirror -Raw | ConvertFrom-Json
        if ($other.id -ne $record.id) { Stop-SL2 'Migration journal identities disagree. Reconcile the retained records manually.' 4 }
        if (@($other.history).Count -gt @($record.history).Count) { $record = $other }
        elseif (@($other.history).Count -eq @($record.history).Count -and $other.phase -ne $record.phase) { Stop-SL2 'Migration journals disagree. Reconcile them manually.' 4 }
    }
    $record
}

function Set-SL2MigrationPhase($Journal, [string]$Phase) {
    $Journal.phase = $Phase
    $Journal.history = @($Journal.history) + @([pscustomobject]@{ phase = $Phase; at = [DateTime]::UtcNow.ToString('o') })
    Write-SL2MigrationJournal $Journal
    Write-SL2Log "migration phase: $Phase"
}

function Get-SL2TreeInventory([string]$Root) {
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $inventory = [Collections.Generic.List[object]]::new()
    $inventory.Add([pscustomobject]@{ path = '.'; hash = ''; acl = (Get-Acl -LiteralPath $base).Sddl })
    # Traversal rejects links before recursing, including directory links.
    $null = @(Get-SL2TreeFiles $Root)
    foreach ($item in Get-ChildItem -LiteralPath $Root -Recurse -Force | Sort-Object FullName) {
        $inventory.Add([pscustomobject]@{ path = $item.FullName.Substring($base.Length + 1); hash = $(if ($item.PSIsContainer) { '' } else { (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash }); acl = (Get-Acl -LiteralPath $item.FullName).Sddl })
    }
    $inventory.ToArray()
}

function Test-SL2InventoryEqual($Left, $Right, [switch]$ContentOnly) {
    $a = @($Left); $b = @($Right)
    if ($a.Count -ne $b.Count) { return $false }
    for ($i = 0; $i -lt $a.Count; $i++) {
        if ($a[$i].path -cne $b[$i].path -or $a[$i].hash -cne $b[$i].hash -or (-not $ContentOnly -and $a[$i].acl -cne $b[$i].acl)) { return $false }
    }
    $true
}

function Copy-SL2MigrationTree([string]$Source, [string]$Target, [string[]]$ApprovedRoots, [string]$Class = 'private') {
    Test-SL2PathTree $Source; Test-SL2PathTree $Target
    if (Test-SL2PathOverlap $Source $Target) { Stop-SL2 'Copy source and target overlap.' }
    if (Test-Path -LiteralPath $Target) { Stop-SL2 'Migration never merges or overwrites existing staging.' }
    $before = @(Get-SL2TreeInventory $Source)
    Assert-SL2AclApproved $Target $ApprovedRoots
    $audit = Get-SL2AclAudit $Source $Class 'staging source' -Recurse
    if ($audit.findings.Count) { Stop-SL2 'Staging source ACLs are insecure.' }
    New-SL2SecureDirectory $Target $ApprovedRoots -Exclusive
    Set-Acl -LiteralPath $Target -AclObject (Get-Acl -LiteralPath $Source)
    Assert-SL2AclRequiredAccess $Target
    if ((Get-SL2AclAudit $Target $Class 'staging target').findings.Count) { Stop-SL2 'Staged root ACL verification failed before copying files.' }
    $result = Invoke-SL2Process 'robocopy.exe' @($Source, $Target, '/E', '/COPYALL', '/DCOPY:DAT', '/B', '/XJ', '/R:0', '/W:0', '/NFL', '/NDL', '/NP', '/NJH', '/NJS') ''
    if ($result.ExitCode -ge 8) { Stop-SL2 'Migration file staging failed. Partial targets were retained for inspection.' 1 }
    if (-not (Test-SL2InventoryEqual $before @(Get-SL2TreeInventory $Source)) -or -not (Test-SL2InventoryEqual $before @(Get-SL2TreeInventory $Target))) {
        Stop-SL2 'Staging content or NTFS security differs from its source. Nothing may be cut over.' 1
    }
}

function New-SL2MigrationBackup($Source, [string]$Executable) {
    $backup = Invoke-SL2Maintenance $Executable @('--backup-local', $Source.BackupRoot, '--data-dir', $Source.DataDirectory)
    $verified = Invoke-SL2Maintenance $Executable @('--backup-verify', $backup.file, '--data-dir', $Source.DataDirectory)
    if (-not $verified.verified -or $verified.sha256 -ne $backup.sha256) { Stop-SL2 'Migration backup verification failed; cutover is forbidden.' 1 }
    $backup
}

function New-SL2MigrationJournal($Source, $Target, $Preflight, [string]$InspectorExecutable) {
    if (-not $Preflight.safe) { Stop-SL2 'Migration preflight has blocking conditions.' }
    if (Read-SL2MigrationJournal $Source) { Stop-SL2 'A migration journal exists. Verify or recover it explicitly.' }
    [pscustomobject]@{
        format = 1; id = [guid]::NewGuid().ToString('N'); phase = 'preflight'; updated = ''; history = @()
        source = $Source; target = $Target; service_before = $Preflight.details.service; release_before = $Preflight.details.release
        manifest = $Preflight.details.manifest; inspector = $InspectorExecutable
        source_config_hash = (Get-FileHash -LiteralPath $Source.ConfigFile -Algorithm SHA256).Hash
        target_config_hash = (Get-FileHash -LiteralPath $Target.ConfigFile -Algorithm SHA256).Hash
        key_before = $Preflight.details.key; key_after = Join-SL2 (Join-SL2 (Split-Path $Target.DataDirectory) 'backup') (Split-Path $Preflight.details.key -Leaf)
        staged_release = Join-SL2 $Target.ReleasesRoot (Split-Path $Preflight.details.release -Leaf)
        online_backup = $null; offline_backup = $null; upload_rebase = $null; source_inventory = @(); target_inventory = @()
        target_prepared = $false; target_creation_intent = $false; target_start_intent = $false; source_stop_intent = $false
        error = ''; recovery = ''
    }
}

function Set-SL2MigrationStartup([string]$Name, [string]$Mode) {
    $result = Invoke-SL2Process 'sc.exe' @('config', $Name, 'start=', $Mode) ''
    if ($result.ExitCode -ne 0) { Stop-SL2 "Could not set startup mode for $Name. Recovery requires attention." 4 }
}

function Assert-SL2DeploymentAllowed($Config) {
    $journal = Read-SL2MigrationJournal $Config
    if (-not $journal) { return }
    $expected = if ($journal.phase -eq 'complete') { $journal.target } elseif ($journal.phase -eq 'rolled_back') { $journal.source } else { Stop-SL2 'Migration is unfinished. Use RecoverMigration; ordinary deployment cannot change either service.' }
    foreach ($name in 'ServiceName', 'DataDirectory', 'ReleasesRoot', 'WorkRoot', 'BackupRoot', 'CertificatePath', 'CertificatePasswordFile', 'ListenAddress', 'Port') {
        if ($Config.$name -ne $expected.$name) { Stop-SL2 'This configuration points at the inactive migration installation. Select the active configuration; ordinary deployment never renames services.' }
    }
    foreach ($name in 'AllowedHosts', 'TrustedProxies') {
        if (@(Compare-Object @($Config.$name) @($expected.$name)).Count) { Stop-SL2 'Network configuration differs from the migration record. Review it explicitly before deployment.' }
    }
}

function Assert-SL2MigrationRecord($Journal) {
    if ($Journal.format -ne 1) { Stop-SL2 'Unsupported migration journal.' 4 }
    Assert-SL2MigrationPair $Journal.source $Journal.target
    foreach ($pair in @(@($Journal.source.ConfigFile, $Journal.source_config_hash), @($Journal.target.ConfigFile, $Journal.target_config_hash))) {
        if (-not (Test-Path -LiteralPath $pair[0]) -or (Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash -ne $pair[1]) { Stop-SL2 'A reviewed configuration changed since migration. Reconcile it with the journal before recovery.' 4 }
    }
    $old = Get-SL2Service $journal.source.ServiceName
    if (-not $old.Exists -or $old.PathName -cne $Journal.service_before.PathName -or $old.Account -ne $Journal.service_before.Account) { Stop-SL2 'The retained source service changed. Manual recovery is required.' 4 }
    $new = Get-SL2Service $journal.target.ServiceName
    if ($new.Exists -and (-not $Journal.target_creation_intent -or -not (Test-SL2ServiceBinary $new.PathName $Journal.target) -or $new.Account -ne $Journal.target.ServiceAccount)) {
        Stop-SL2 'The canonical service cannot be proven to belong to this migration. It was left untouched.' 4
    }
}

function Set-SL2MigrationManualRecovery($Journal, [string]$Reason) {
    $Journal.recovery = @"
Automatic recovery cannot prove that no writes would be lost. Both data trees and all staged files are retained. Do not delete or overwrite either.
Keep $($Journal.target.ServiceName) and $($Journal.source.ServiceName) stopped and disabled until the operator has reconciled their state.
Source configuration: $($Journal.source.ConfigFile)
Target configuration: $($Journal.target.ConfigFile)
Source data: $($Journal.source.DataDirectory)
Target data: $($Journal.target.DataDirectory)
Verified backups: $($Journal.source.BackupRoot) and $($Journal.target.BackupRoot)
Key locations are recorded in this journal. Keep the original and copied keys and TLS files protected.
Inspect both services with Get-CimInstance Win32_Service, then inspect this journal and the retained data inventories.
Back up both trees before deciding which contains authoritative writes. Restore or reconcile into a NEW directory, never over either tree.
After reconciling data and the chosen service command line, enable and start ONLY that service, then verify health and release identity.
Reason: $Reason
"@
    Set-SL2MigrationPhase $Journal 'manual_recovery_required'
    Stop-SL2 'Migration needs manual recovery. Read recovery in migration-journal.json; no data was replaced or deleted.' 4
}

function Invoke-SL2MigrationRecovery($Config, [switch]$Rollback) {
    $journal = Read-SL2MigrationJournal $Config
    if (-not $journal) { Stop-SL2 'No migration journal exists at the selected configuration.' }
    Assert-SL2MigrationRecord $journal
    if ($journal.phase -eq 'rolled_back') { return [pscustomobject]@{ phase = 'rolled_back'; changed = $false } }
    if ($journal.phase -eq 'complete' -and -not $Rollback) { return Test-SL2MigrationComplete $Config }
    if ($journal.phase -eq 'manual_recovery_required') { Stop-SL2 'Manual recovery is required; inspect the retained journal and data. Recovery never guesses after an unproven rollback.' 4 }
    $source = $journal.source; $target = $journal.target
    try {
        $new = Get-SL2Service $journal.target.ServiceName
        if ($new.Exists) {
            # Disable before stopping: an interruption cannot leave this service enabled beside the source.
            Set-SL2MigrationPhase $journal 'recovery_stopping_target'
            Set-SL2MigrationStartup $journal.target.ServiceName 'disabled'
            Stop-SL2Service $journal.target.ServiceName ([int]$target.StopTimeoutSeconds)
        }
        if ($journal.target_start_intent) {
            if (-not @($journal.target_inventory).Count -or -not (Test-SL2InventoryEqual @($journal.target_inventory) @(Get-SL2TreeInventory $target.DataDirectory) -ContentOnly)) {
                Set-SL2MigrationManualRecovery $journal 'The target may have accepted writes; returning to the original data would risk losing changes.'
            }
        }
        if ($journal.source_stop_intent -and @($journal.source_inventory).Count -and
            -not (Test-SL2InventoryEqual @($journal.source_inventory) @(Get-SL2TreeInventory $source.DataDirectory) -ContentOnly)) {
            Set-SL2MigrationManualRecovery $journal 'The original data changed after the stopped-source snapshot.'
        }
        if (@(Get-SL2Listener $source.ListenAddress ([int]$source.Port)).Count -gt 0 -and (Get-SL2Service $journal.source.ServiceName).State -ne 'Running') {
            Set-SL2MigrationManualRecovery $journal 'Another process still owns the listener.'
        }
        Set-SL2MigrationPhase $journal 'recovery_starting_source'
        $mode = if ($journal.service_before.StartMode -match '^Auto') { 'auto' } else { 'demand' }
        Set-SL2MigrationStartup $journal.source.ServiceName $mode
        if ((Get-SL2Service $journal.source.ServiceName).State -ne 'Running') { Start-SL2Service $journal.source.ServiceName }
        $null = Wait-SL2Ready $source $journal.manifest.source_sha $journal.manifest.version
        Set-SL2MigrationPhase $journal 'rolled_back'
        [pscustomobject]@{ phase = 'rolled_back'; source_service = $journal.source.ServiceName; target_retained = $new.Exists; data_deleted = $false }
    } catch {
        if ($journal.phase -eq 'manual_recovery_required') { throw }
        # A failed stop is not followed by starting the other service.
        try { Set-SL2MigrationStartup $journal.target.ServiceName 'disabled' } catch { }
        try { Set-SL2MigrationStartup $journal.source.ServiceName 'disabled' } catch { }
        Set-SL2MigrationManualRecovery $journal 'Service recovery or consistency verification failed. Inspect actual SCM state before any restart.'
    }
}

function Test-SL2MigrationComplete($Config) {
    $journal = Read-SL2MigrationJournal $Config
    if (-not $journal -or $journal.phase -ne 'complete') { Stop-SL2 'Migration is not complete. Inspect the journal or use RecoverMigration.' }
    Assert-SL2MigrationRecord $journal
    $old = Get-SL2Service $journal.source.ServiceName
    if ($old.State -ne 'Stopped' -or $old.StartMode -ne 'Disabled') { Stop-SL2 'The retained legacy service must be stopped and disabled.' 4 }
    $release = Get-SL2Link (Get-SL2CurrentLink $journal.target)
    if (-not $release) { $release = $journal.staged_release }
    $manifest = Get-Content -LiteralPath (Join-SL2 $release 'build-manifest.json') -Raw | ConvertFrom-Json
    $ready = Wait-SL2Ready $journal.target $manifest.source_sha $manifest.version
    [pscustomobject]@{ phase = 'complete'; service = $journal.target.ServiceName; legacy_service = $journal.source.ServiceName; legacy_service_deleted = $false
        data_directory = $journal.target.DataDirectory; release = $release; commit = $manifest.source_sha; migration_commit = $journal.manifest.source_sha
        version = $manifest.version; identity = $ready.identity }
}

function Invoke-SL2MigrateService($Source, $Target, [string]$InspectorExecutable) {
    if (-not $Target -or -not $InspectorExecutable) { Stop-SL2 'Service migration requires an explicit target configuration and InspectorExecutable. Run PreflightMigration first.' }
    $previous = Read-SL2MigrationJournal $Source
    if ($previous) {
        if ($previous.phase -eq 'complete') { return Test-SL2MigrationComplete $Source }
        Stop-SL2 'A migration already exists. Use RecoverMigration or VerifyMigration; partial staging is never overwritten.'
    }
    $preflight = Get-SL2MigrationPreflight $Source $Target $InspectorExecutable
    if (-not $preflight.safe) { Stop-SL2 ('Preflight blocked migration: ' + (($preflight.checks | Where-Object { -not $_.passed } | ForEach-Object name) -join ', ')) }
    $journal = New-SL2MigrationJournal $Source $Target $preflight $InspectorExecutable
    Write-SL2MigrationJournal $journal
    $exe = @(Split-SL2CommandLine $journal.service_before.PathName)[0]
    try {
        Set-SL2MigrationPhase $journal 'verified_backup'
        $journal.online_backup = New-SL2MigrationBackup $Source $exe
        Set-SL2MigrationPhase $journal 'target_preparation'
        $approvedRoots = @(Get-SL2MigrationProvisioningRoots $Target)
        New-SL2SecureDirectory $Target.WorkRoot $approvedRoots -Exclusive
        Set-Acl -LiteralPath $Target.WorkRoot -AclObject (Get-Acl -LiteralPath $Source.WorkRoot)
        $journal.target_prepared = $true
        Set-SL2MigrationPhase $journal 'file_staging'
        Copy-SL2MigrationTree $journal.release_before $journal.staged_release $approvedRoots 'binaries'
        Copy-SL2MigrationTree (Split-Path $Source.CertificatePath) (Split-Path $Target.CertificatePath) $approvedRoots
        Copy-SL2MigrationTree (Split-Path $journal.key_before) (Split-Path $journal.key_after) $approvedRoots
        # There is no safe live directory copy of SQLite. Journal the stop before invoking SCM, then copy only after it is quiescent.
        $journal.source_stop_intent = $true
        Set-SL2MigrationPhase $journal 'stopping_source'
        Set-SL2MigrationStartup $Source.ServiceName 'disabled'
        Stop-SL2Service $Source.ServiceName ([int]$Source.StopTimeoutSeconds)
        Set-SL2MigrationPhase $journal 'offline_backup'
        $journal.offline_backup = New-SL2MigrationBackup $Source $exe
        Copy-SL2MigrationTree $Source.BackupRoot $Target.BackupRoot $approvedRoots
        Copy-SL2MigrationTree $Source.DataDirectory $Target.DataDirectory $approvedRoots
        $journal.source_inventory = @(Get-SL2TreeInventory $Source.DataDirectory)
        $pointer = Join-SL2 $Target.DataDirectory 'backup-key-location.json'
        $location = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
        $location.path = $journal.key_after
        [IO.File]::WriteAllText($pointer, ($location | ConvertTo-Json))
        # Rebase only application-managed uploads in the verified OFFLINE copy. External source locations never change.
        Set-SL2MigrationPhase $journal 'rebasing_upload_paths'
        $databaseHash = (Get-FileHash -LiteralPath (Join-SL2 $Target.DataDirectory 'sap-lens-v2.sqlite3') -Algorithm SHA256).Hash
        $journal.upload_rebase = Invoke-SL2Maintenance $InspectorExecutable @('--rebase-upload-paths', $Source.DataDirectory, '--migration-copy', '--expected-db-sha', $databaseHash, '--data-dir', $Target.DataDirectory)
        if ($null -eq $journal.upload_rebase -or $journal.upload_rebase.rebased -lt 0) { Stop-SL2 'Copied upload path verification failed.' 1 }
        Set-SL2MigrationPhase $journal 'upload_paths_rebased'
        # Apart from the key pointer and journaled managed-upload locations, the copy retains its original content and ACLs.
        $inspection = Invoke-SL2Maintenance $InspectorExecutable @('--inspect-data', '--data-dir', $Target.DataDirectory)
        if (-not $inspection.ok) { Stop-SL2 'Staged SQLite integrity verification failed.' 1 }
        $archive = Join-SL2 $Target.BackupRoot (Split-Path $journal.offline_backup.file -Leaf)
        $verified = Invoke-SL2Maintenance $exe @('--backup-verify', $archive, '--data-dir', $Target.DataDirectory)
        if (-not $verified.verified -or $verified.sha256 -ne $journal.offline_backup.sha256) { Stop-SL2 'The copied key cannot verify the staged backup.' 1 }
        $journal.target_inventory = @(Get-SL2TreeInventory $Target.DataDirectory)
        Set-SL2MigrationPhase $journal 'data_verified'
        if (@(Get-SL2Listener $Target.ListenAddress ([int]$Target.Port)).Count) { Stop-SL2 'The listener is not free after stopping the source.' 4 }
        Set-SL2Link (Get-SL2CurrentLink $Target) $journal.staged_release
        $journal.target_creation_intent = $true
        Set-SL2MigrationPhase $journal 'service_cutover'
        if ((Get-SL2Service $Target.ServiceName).Exists) { Stop-SL2 'Canonical service appeared during migration. It was not modified.' 4 }
        Set-SL2ServiceEntry $Target (Get-SL2BinaryPath $Target) $false 'demand'
        Grant-SL2Access $Target
        # Added service-account grants are expected; record the final pre-start content inventory.
        $journal.target_inventory = @(Get-SL2TreeInventory $Target.DataDirectory)
        $journal.target_start_intent = $true
        Set-SL2MigrationPhase $journal 'service_startup'
        Start-SL2Service $Target.ServiceName
        Set-SL2MigrationPhase $journal 'identity_verification'
        $null = Wait-SL2Ready $Target $journal.manifest.source_sha $journal.manifest.version
        Set-SL2MigrationStartup $Target.ServiceName 'auto'
        Set-SL2MigrationPhase $journal 'publishing_configuration'
        $canonical = Join-SL2 $Target.WorkRoot 'deploy.local.json'
        $json = $Target | Select-Object * -ExcludeProperty ConfigFile, ServiceNameConfigured | ConvertTo-Json -Depth 8
        $stream = [IO.File]::Open($canonical, 'CreateNew', 'Write', 'None')
        try { $bytes = [Text.Encoding]::UTF8.GetBytes($json); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Set-SL2MigrationPhase $journal 'complete'
        Test-SL2MigrationComplete $Source
    } catch {
        # Do not persist raw native exception text: a failed certificate loader may disclose sensitive input.
        $journal.error = "Migration failed in phase $($journal.phase). Inspect the retained state and focused deployment log."
        Write-SL2MigrationJournal $journal
        $null = Invoke-SL2MigrationRecovery $Source -Rollback
        Stop-SL2 "Migration failed and safely returned to $($Source.ServiceName). Both installations and any owned target service were retained." 1
    }
}

# The running service selects the store; neither recursive filename searches nor configuration fallbacks may adopt another database.
function Get-SL2MigrationSourceData($Source, $Service) {
    if (-not $Service.Exists -or $Service.State -ne 'Running') { Stop-SL2 'The source service must be running before resolving its data directory.' }
    $tokens = @(Split-SL2CommandLine $Service.PathName)
    try { $arguments = ConvertTo-SL2ArgumentMap @($tokens | Select-Object -Skip 1) }
    catch { Stop-SL2 'The source service arguments are invalid or repeated; reconcile them without exposing argument values.' }
    if (-not $arguments.ContainsKey('--data-dir') -or [string]::IsNullOrWhiteSpace($arguments['--data-dir'])) {
        Stop-SL2 'The running source service requires one nonempty --data-dir argument; environment/default fallback is forbidden for migration.'
    }
    $data = $arguments['--data-dir']
    if (-not [IO.Path]::IsPathRooted($data) -or $data.StartsWith('\\') -or $data.StartsWith('//') -or $data.Contains('://')) { Stop-SL2 'The source service --data-dir must be an absolute local directory.' }
    if ([IO.Path]::GetFullPath($data).TrimEnd('\', '/') -eq [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($data)).TrimEnd('\', '/')) { Stop-SL2 'The source service --data-dir must not be a drive root.' }
    if ([string]::IsNullOrWhiteSpace($Source.DataDirectory)) { Stop-SL2 'The source configuration DataDirectory is empty; reconcile it with the running service.' }
    $data = [IO.Path]::GetFullPath($data).TrimEnd('\', '/')
    if (-not [string]::Equals($data, [IO.Path]::GetFullPath($Source.DataDirectory).TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) {
        Stop-SL2 'The source configuration DataDirectory differs from the running service --data-dir; no database was selected.'
    }
    Test-SL2PathTree $data
    # Matches DatabaseOptions.DatabasePath / ApplicationBackups.DatabaseEntry, not the optional security store or migration history.
    $database = Join-SL2 $data 'sap-lens-v2.sqlite3'
    [pscustomobject]@{ resolution = 'running_service --data-dir'; data_directory = $data; database_path = $database
        database_exists = (Test-Path -LiteralPath $database -PathType Leaf)
        wal_present = (Test-Path -LiteralPath "$database-wal" -PathType Leaf); shm_present = (Test-Path -LiteralPath "$database-shm" -PathType Leaf) }
}

function Get-SL2MigrationPreflight($Source, $Target, [string]$InspectorExecutable) {
    $checks = [Collections.Generic.List[object]]::new()
    $details = [ordered]@{}
    function Check([string]$Name, [scriptblock]$Body) {
        try { & $Body; $checks.Add([pscustomobject]@{ name = $Name; passed = $true; message = 'ok' }) }
        catch { $checks.Add([pscustomobject]@{ name = $Name; passed = $false; message = $_.Exception.Message }) }
    }
    Assert-SL2MigrationPair $Source $Target
    Check 'service_conflicts' {
        if ($Source.ServiceName -eq 'SapLens2' -and (Get-SL2Service 'AuthLens').Exists) { Stop-SL2 'The previous AuthLens service already exists; reconcile it explicitly before canonical migration.' }
        $old = Get-SL2Service $Source.ServiceName; $new = Get-SL2Service $Target.ServiceName
        if ($new.Exists) { Stop-SL2 'sap-lens already exists. Nothing may be adopted or overwritten by migration.' }
        if (-not $old.Exists -or $old.State -ne 'Running') { Stop-SL2 'SapLens2 must exist and be running for initial migration.' }
        if ($old.Account -notin @('LocalSystem', 'NT AUTHORITY\SYSTEM', "NT SERVICE\$($Source.ServiceName)")) { Stop-SL2 'Custom service accounts require a separately reviewed credential and permission migration.' }
        $expected = if ($old.Account -eq "NT SERVICE\$($Source.ServiceName)") { "NT SERVICE\$($Target.ServiceName)" } else { 'LocalSystem' }
        if ($Target.ServiceAccount -ne $expected) { Stop-SL2 "Target ServiceAccount must preserve the source identity: $expected." }
        $tokens = @(Split-SL2CommandLine $old.PathName)
        $details.source_data = Get-SL2MigrationSourceData $Source $old
        if (@(Compare-SL2ServiceArguments @($tokens | Select-Object -Skip 1) @(Get-SL2ServiceArguments $Source)).Count) { Stop-SL2 'Source configuration does not match the actual service arguments.' }
        $owners = @(Get-SL2Listener $Source.ListenAddress ([int]$Source.Port))
        if ($owners.Count -ne 1 -or $owners[0] -ne $old.ProcessId) { Stop-SL2 'The source service does not exclusively own the configured listener.' }
        $details.service = $old # only retain a command line after every argument passed the supported-option/configuration checks
    }
    Check 'network_unchanged' {
        foreach ($p in 'ListenAddress', 'Port') { if ($Source.$p -ne $Target.$p) { Stop-SL2 "Migration cannot change $p." } }
        foreach ($p in 'AllowedHosts', 'TrustedProxies') {
            if (@(Compare-Object @($Source.$p) @($Target.$p)).Count) { Stop-SL2 "Migration cannot change $p." }
        }
    }
    Check 'source_release' {
        if (-not $details.Contains('service')) { Stop-SL2 'Resolve source service conflicts before querying the source release.' }
        $details.release_junction = Get-SL2ReleaseJunction $Source.ReleasesRoot
        $tokens = @(Split-SL2CommandLine (Get-SL2Service $Source.ServiceName).PathName)
        $release = Split-Path (Split-Path $tokens[0])
        if (Test-SL2ServiceBinary (Get-SL2Service $Source.ServiceName).PathName $Source) { $release = Get-SL2Link (Get-SL2CurrentLink $Source) }
        Test-SL2PathTree $release
        $manifest = Get-Content -LiteralPath (Join-SL2 $release 'build-manifest.json') -Raw | ConvertFrom-Json
        if ($manifest.source_sha -notmatch '^[a-f0-9]{40}$' -or $manifest.version -ne '2.0.0-alpha.1' -or $manifest.source_dirty) { Stop-SL2 'A clean release manifest for version 2.0.0-alpha.1 is required.' }
        # The running release is a server deployment package: verify every artifact it holds against its manifest and SHA256SUMS. Only the Desktop and
        # symbol files may be absent, and each absence is recorded; a package published before deployment-package.json existed is reported as undeclared.
        $verification = Test-SL2PublishedRelease $release
        $details.release_verification = $verification.Output
        if (-not $verification.Verified) { Stop-SL2 "Source release verification failed (verify-release.ps1 -Scope Server): $(($verification.Output | Where-Object { $_ -like 'verify-release:*' } | Select-Object -First 3) -join ' ')" }
        $details.release = $release; $details.manifest = $manifest
        $ready = Invoke-SL2ConfiguredHttp $Source '/health/ready'
        $identityResponse = Invoke-SL2ConfiguredHttp $Source '/product-version.json'
        if ($ready.Status -ne 200 -or $identityResponse.Status -ne 200) { Stop-SL2 'The source is not ready or its release identity is unavailable.' }
        $identity = $identityResponse.Body | ConvertFrom-Json
        if ($identity.source_sha -ne $manifest.source_sha -or $identity.version -ne $manifest.version) { Stop-SL2 'Running source identity does not match the verified release manifest.' }
        $details.running_identity = $identity
        # Ask the old binary only for its compiled migration list at a missing path. SQLite never opens source state.
        $probe = Join-SL2 $Source.WorkRoot ('.schema-probe-' + [guid]::NewGuid().ToString('N'))
        $schema = Invoke-SL2Maintenance $tokens[0] @('--schema-info', '--data-dir', $probe)
        $details.release_schema = [pscustomobject]@{ purpose = 'compiled_migrations_only'; database_opened = $false; known = @($schema.known) }
    }
    Check 'private_state' {
        Test-SL2MigrationEnvironment $Source.ServiceName
        $details.key = Get-SL2MigrationKey $Source
        foreach ($path in $Source.DataDirectory, $Source.CertificatePath, $Source.CertificatePasswordFile, $details.key, $Source.BackupRoot, $Source.WorkRoot) {
            if (-not (Test-Path -LiteralPath $path)) { Stop-SL2 'A required data, TLS, key or backup-history path is missing.' }
            Test-SL2PathTree $path
        }
        # Private state (data, backups, TLS, keys and every descendant, deployment state) admits no broad read or write; releases, the configuration
        # and its folder no broad write. Principals are compared by well-known SID (AuthLens.Acl.ps1); each finding names path, principal and right.
        $null = @(Get-SL2TreeFiles $Source.DataDirectory)   # rejects reparse points before the recursive ACL audit
        $details.acl_source = Assert-SL2AclPlan (Get-SL2AclPlan $Source $null $details.key) 'Private source state'
        if ((Split-Path $Source.CertificatePath) -ne (Split-Path $Source.CertificatePasswordFile)) { Stop-SL2 'Source TLS files must share a directory before migration.' }
        Test-SL2MigrationTls $Source
    }
    Check 'sqlite_consistency' {
        if (-not $details.Contains('service') -or -not $details.Contains('source_data')) { Stop-SL2 'Resolve source service arguments/conflicts before inspecting SQLite; no fallback database is selected.' }
        $active = $details.source_data
        $details.schema = [pscustomobject]@{ database_exists = $active.database_exists; inspection_status = 'not_run' }
        if (-not $active.database_exists) { Stop-SL2 "The active SAP Lens database is missing: $($active.database_path). Historical and security databases are not substitutes." }
        if ([string]::IsNullOrWhiteSpace($InspectorExecutable)) { Stop-SL2 'Supply an explicit -InspectorExecutable from a verified Windows release containing the current --inspect-data; no inspector was selected.' }
        if (-not [IO.Path]::IsPathRooted($InspectorExecutable) -or -not (Test-Path -LiteralPath $InspectorExecutable -PathType Leaf)) { Stop-SL2 'The explicit -InspectorExecutable must be an existing absolute server executable path.' }
        Test-SL2PathTree $InspectorExecutable
        $inspectorVerification = Test-SL2PublishedRelease (Split-Path (Split-Path $InspectorExecutable))
        if (-not $inspectorVerification.Verified) { Stop-SL2 'The inspector release does not verify with verify-release.ps1 -Scope Server; no SQLite inspection ran.' }
        $details.inspector_executable = [IO.Path]::GetFullPath($InspectorExecutable)
        $inspection = Invoke-SL2Maintenance $InspectorExecutable @('--inspect-data', '--data-dir', $active.data_directory)
        $details.inspection = $inspection
        if (-not $inspection.ok) { Stop-SL2 'SQLite integrity inspection failed.' }
        $hasPaths = if ($inspection -is [Collections.IDictionary]) { $inspection.Contains('source_paths') } else { [bool]$inspection.PSObject.Properties['source_paths'] }
        if (-not $hasPaths) { Stop-SL2 'Inspector lacks source-path checks. Use the current inspector build.' }
        if (@($inspection.capabilities) -notcontains 'rebase-upload-paths-v1') { Stop-SL2 'Inspector lacks verified upload rebasing. Use the current inspector build.' }
        if (@($inspection.capabilities) -notcontains 'canonical-sqlite-stores-v1') { Stop-SL2 'Inspector lacks canonical SQLite store discovery and stable-copy verification. Use a newly verified inspector release.' }
        if (-not $inspection.schema.database_exists -or -not [string]::Equals($inspection.database_path, $active.database_path, [StringComparison]::OrdinalIgnoreCase)) { Stop-SL2 'Inspector did not verify the selected active database path; no fallback database may be adopted.' }
        $details.schema = $inspection.schema
        $details.source_paths_to_rebase = @()
        $sourceKinds = @{ data_csv_path = 'roles'; user_csv_path = 'users'; employee_csv_path = 'employees'; sod_csv_path = 'sod' }
        foreach ($path in $inspection.source_paths.PSObject.Properties) {
            if (-not $path.Value) { continue }
            if (-not [IO.Path]::IsPathRooted($path.Value)) { Stop-SL2 'A configured source path is relative. Reconcile it explicitly before migration.' }
            if (Test-SL2PathOverlap $Source.DataDirectory $path.Value) {
                $prefix = [IO.Path]::GetFullPath($Source.DataDirectory).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
                $relative = [IO.Path]::GetFullPath($path.Value).Substring($prefix.Length).Replace('\', '/')
                if ($relative -cnotmatch ('\Asources/' + $sourceKinds[$path.Name] + '-[a-f0-9]{16}\.csv\z')) { Stop-SL2 'A source inside data is not an application-managed upload. Review its location explicitly before migration.' }
                $details.source_paths_to_rebase += $path.Name
                continue
            }
            foreach ($root in $Source.DataDirectory, $Source.ReleasesRoot, $Source.WorkRoot, $Source.BackupRoot, (Split-Path $Source.CertificatePath), (Split-Path $details.key)) {
                if ($root -and (Test-SL2PathOverlap $root $path.Value)) { Stop-SL2 'A configured CSV source depends on the old installation. Re-import from a durable external source before migration; paths are never rewritten blindly.' }
            }
        }
        if ($details.Contains('release_schema')) {
            $known = @($details.release_schema.known); $applied = @($inspection.schema.applied)
            if (-not $applied.Count -or @($applied | Where-Object { $known -notcontains $_ }).Count -or @($known | Where-Object { $applied -notcontains $_ }).Count) {
                Stop-SL2 'Source database must be compatible with its release and have no pending migrations.'
            }
        }
    }
    Check 'targets_and_capacity' {
        Assert-SL2CanonicalTargetLayout $Target
        $sourceRoots = @($Source.DataDirectory, $Source.ReleasesRoot, $Source.WorkRoot, $Source.BackupRoot, (Split-Path $Source.CertificatePath), (Split-Path (Get-SL2MigrationKey $Source)))
        $targets = @($Target.DataDirectory, $Target.ReleasesRoot, $Target.WorkRoot, $Target.BackupRoot, (Split-Path $Target.CertificatePath), (Join-SL2 (Split-Path $Target.DataDirectory) 'backup'))
        for ($i = 0; $i -lt $targets.Count; $i++) {
            $path = $targets[$i]; Test-SL2PathTree $path
            if ($path -notmatch '^[A-Za-z]:\\') { Stop-SL2 "Target root $path must be an absolute local path." }
            if (Test-Path -LiteralPath $path) { Stop-SL2 "Target root $path already exists. Target roots must be new; retained partial staging requires recovery, never overwrite." }
            foreach ($sourcePath in $sourceRoots) { if (Test-SL2PathOverlap $sourcePath $path) { Stop-SL2 'Source and target roots must be disjoint.' } }
            for ($j = 0; $j -lt $i; $j++) { if (Test-SL2PathOverlap $targets[$j] $path) { Stop-SL2 'Target roots must be disjoint.' } }
        }
        # Each new target root inherits from its parent: the parent of a private target must be private, the parent of the release root free of broad
        # write. A missing parent is judged by its nearest existing ancestor (for example C:\ProgramData, which lets users create folders): prepare
        # it explicitly with -Action ProtectAcl first.
        $details.acl_target = Assert-SL2AclPlan @(Get-SL2AclPlan $null $Target | Where-Object Role -eq 'target parent') 'A target parent'
        if ((Split-Path $Target.CertificatePasswordFile) -ne (Split-Path $Target.CertificatePath)) { Stop-SL2 'Target TLS certificate and password file must share the TLS directory.' }
        foreach ($name in 'CertificatePath', 'CertificatePasswordFile') { if ((Split-Path $Target.$name -Leaf) -cne (Split-Path $Source.$name -Leaf)) { Stop-SL2 'Migration preserves TLS filenames; only their directory changes.' } }
        $bytes = 0L
        foreach ($path in @($Source.DataDirectory, $details.release, $Source.BackupRoot, (Split-Path $Source.CertificatePath), (Split-Path $details.key)) | Select-Object -Unique) { if ($path -and (Test-Path -LiteralPath $path)) { foreach ($file in @(Get-SL2TreeFiles $path)) { $bytes += $file.Length } } }
        $details.required_bytes_per_volume = 3 * $bytes + 1GB
        foreach ($path in $targets) { if ((Get-SL2FreeSpace $path) -lt $details.required_bytes_per_volume) { Stop-SL2 'Insufficient free space for staging, verified backup and recovery reserve.' } }
        $details.targets = $targets
    }
    Check 'recovery_state' {
        $journal = Read-SL2Journal $Source
        $details.journal = $journal
        if ($journal -and $journal.phase -notin $script:FinalPhases) { Stop-SL2 'An unfinished deployment requires recovery before migration.' }
        if (Test-Path -LiteralPath (Join-SL2 $Source.WorkRoot 'migration-journal.json')) { Stop-SL2 'A migration journal already exists. Use VerifyMigration or RecoverMigration; never repeat a cutover blindly.' }
        if (Test-Path -LiteralPath (Join-SL2 $Source.DataDirectory 'restore/pending.json')) { Stop-SL2 'An application restore is pending. Resolve it before directory migration.' }
        foreach ($pending in 'migration/pending-activation.json', 'migration/pending-rollback.json') {
            if (Test-Path -LiteralPath (Join-SL2 $Source.DataDirectory $pending)) { Stop-SL2 'A v1 migration activation or rollback is pending. Resolve it before directory migration.' }
        }
        $operation = Join-SL2 $Source.DataDirectory 'backups/operation.json'
        if (Test-Path -LiteralPath $operation) {
            $state = Get-Content -LiteralPath $operation -Raw | ConvertFrom-Json
            if ($state.status -notin @('idle', 'ready', 'completed', 'cancelled', 'failed')) { Stop-SL2 'An application backup or restore is in progress.' }
        }
        $details.backup_history_files = @(Get-SL2TreeFiles $Source.BackupRoot).Count
    }
    [pscustomobject]@{ safe = (@($checks | Where-Object { -not $_.passed }).Count -eq 0); checks = $checks.ToArray(); details = [pscustomobject]$details
        warnings = @('Live inspection is observational. The source will be stopped before the final copy and integrity verification.', 'Native service, NTFS effective access and reboot acceptance must run separately on isolated fixtures before production cutover.') }
}
