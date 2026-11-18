# Part of SapLens.Deploy, dot-sourced into the same module. No operations run on import.
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
    # An environment override could make a copied pointer select a different key after cutover.
    if ($env:SAP_LENS_V2_BACKUP_KEY_FILE -or [Environment]::GetEnvironmentVariable('SAP_LENS_V2_BACKUP_KEY_FILE', 'Machine')) {
        Stop-SL2 'Remove and reconcile backup-key environment overrides before migration; use the data directory key pointer.'
    }
    $pointer = Join-SL2 $Source.DataDirectory 'backup-key-location.json'
    $key = (Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json).path
    if (-not [IO.Path]::IsPathRooted($key) -or -not (Test-Path -LiteralPath $key -PathType Leaf)) { Stop-SL2 'The host backup key pointer is missing or invalid.' }
    Test-SL2PathTree $key
    if (Test-SL2PathOverlap $Source.DataDirectory $key) { Stop-SL2 'The host backup key must be outside data.' }
    $key
}

function Get-SL2MigrationAcl([string]$Path, [switch]$Secret) {
    $acl = Get-Acl -LiteralPath $Path
    # Reject broad grants on private state. Return the DACL for operator review; never print file contents.
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -eq 'Allow' -and $sid -in @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')) {
            $mask = if ($Secret) { [Security.AccessControl.FileSystemRights]::ReadData } else { [Security.AccessControl.FileSystemRights]::Write }
            if ($rule.FileSystemRights -band $mask) { Stop-SL2 'Private source or target parent has broad NTFS access; review its ACL before migration.' }
        }
    }
    $acl.Sddl
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
    if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
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

function Copy-SL2MigrationTree([string]$Source, [string]$Target) {
    Test-SL2PathTree $Source; Test-SL2PathTree $Target
    if (Test-SL2PathOverlap $Source $Target) { Stop-SL2 'Copy source and target overlap.' }
    if (Test-Path -LiteralPath $Target) { Stop-SL2 'Migration never merges or overwrites existing staging.' }
    $before = @(Get-SL2TreeInventory $Source)
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    Set-Acl -LiteralPath $Target -AclObject (Get-Acl -LiteralPath $Source)
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
        online_backup = $null; offline_backup = $null; source_inventory = @(); target_inventory = @()
        target_creation_intent = $false; target_start_intent = $false; source_stop_intent = $false
        error = ''; recovery = ''
    }
}

function Get-SL2MigrationPreflight($Source, $Target, [string]$InspectorExecutable) {
    $checks = [Collections.Generic.List[object]]::new()
    $details = [ordered]@{}
    function Check([string]$Name, [scriptblock]$Body) {
        try { & $Body; $checks.Add([pscustomobject]@{ name = $Name; passed = $true; message = 'ok' }) }
        catch { $checks.Add([pscustomobject]@{ name = $Name; passed = $false; message = $_.Exception.Message }) }
    }
    Check 'service_conflicts' {
        $old = Get-SL2Service 'SapLens2'; $new = Get-SL2Service 'SapLens'
        $details.service = $old
        if ($new.Exists) { Stop-SL2 'SapLens already exists (including possible v1 installation). Nothing may be adopted or overwritten by migration.' }
        if (-not $old.Exists -or $old.State -ne 'Running') { Stop-SL2 'SapLens2 must exist and be running for initial migration.' }
        if ($Source.ServiceName -ne 'SapLens2' -or $Target.ServiceName -ne 'SapLens') { Stop-SL2 'Source must explicitly select SapLens2; target must explicitly select SapLens.' }
        if ($old.Account -notin @('LocalSystem', 'NT AUTHORITY\SYSTEM', 'NT SERVICE\SapLens2')) { Stop-SL2 'Custom service accounts require a separately reviewed credential and permission migration.' }
        $expected = if ($old.Account -eq 'NT SERVICE\SapLens2') { 'NT SERVICE\SapLens' } else { 'LocalSystem' }
        if ($Target.ServiceAccount -ne $expected) { Stop-SL2 "Target ServiceAccount must preserve the source identity: $expected." }
        $tokens = @(Split-SL2CommandLine $old.PathName)
        if (@(Compare-SL2ServiceArguments @($tokens | Select-Object -Skip 1) @(Get-SL2ServiceArguments $Source)).Count) { Stop-SL2 'Source configuration does not match the actual service arguments.' }
        $owners = @(Get-SL2Listener $Source.ListenAddress ([int]$Source.Port))
        if ($owners.Count -ne 1 -or $owners[0] -ne $old.ProcessId) { Stop-SL2 'The source service does not exclusively own the configured listener.' }
    }
    Check 'network_unchanged' {
        foreach ($p in 'ListenAddress', 'Port') { if ($Source.$p -ne $Target.$p) { Stop-SL2 "Migration cannot change $p." } }
        foreach ($p in 'AllowedHosts', 'TrustedProxies') {
            if (@(Compare-Object @($Source.$p) @($Target.$p)).Count) { Stop-SL2 "Migration cannot change $p." }
        }
    }
    Check 'source_release' {
        $tokens = @(Split-SL2CommandLine (Get-SL2Service 'SapLens2').PathName)
        $release = Split-Path (Split-Path $tokens[0])
        if (Test-SL2ServiceBinary (Get-SL2Service 'SapLens2').PathName $Source) { $release = Get-SL2Link (Get-SL2CurrentLink $Source) }
        Test-SL2PathTree $release
        $manifest = Get-Content -LiteralPath (Join-SL2 $release 'build-manifest.json') -Raw | ConvertFrom-Json
        if ($manifest.source_sha -notmatch '^[a-f0-9]{40}$' -or $manifest.version -ne '2.0.0-alpha.1' -or $manifest.source_dirty) { Stop-SL2 'A clean release manifest for version 2.0.0-alpha.1 is required.' }
        $verification = Invoke-SL2Process (Get-SL2Shell) @('-NoProfile', '-File', (Join-SL2 $PSScriptRoot '..\verify-release.ps1'), '-ReleasePath', $release) ''
        if ($verification.ExitCode -ne 0) { Stop-SL2 'Source release checksum verification failed.' }
        $details.release = $release; $details.manifest = $manifest
        # Ask the old binary only for its compiled migration list at a missing path. SQLite never opens source state.
        $probe = Join-SL2 $Source.WorkRoot ('.schema-probe-' + [guid]::NewGuid().ToString('N'))
        $schema = Invoke-SL2Maintenance $tokens[0] @('--schema-info', '--data-dir', $probe)
        $details.schema = $schema
    }
    Check 'private_state' {
        $details.key = Get-SL2MigrationKey $Source
        foreach ($path in $Source.DataDirectory, $Source.CertificatePath, $Source.CertificatePasswordFile, $details.key, $Source.BackupRoot) {
            if (-not (Test-Path -LiteralPath $path)) { Stop-SL2 'A required data, TLS, key or backup-history path is missing.' }
            Test-SL2PathTree $path
            $null = Get-SL2MigrationAcl $path -Secret:($path -ne $Source.DataDirectory -and $path -ne $Source.BackupRoot)
        }
        # Inspect every private descendant too, including external recovery keys beside the host key.
        foreach ($folder in $Source.DataDirectory, (Split-Path $details.key), (Split-Path $Source.CertificatePath), $Source.BackupRoot) {
            foreach ($file in @(Get-SL2TreeFiles $folder)) { $null = Get-SL2MigrationAcl $file.FullName -Secret }
        }
    }
    Check 'sqlite_consistency' {
        if (-not (Test-Path -LiteralPath $InspectorExecutable -PathType Leaf)) { Stop-SL2 'Supply -InspectorExecutable from a build containing --inspect-data (it is never installed as the service).' }
        $inspection = Invoke-SL2Maintenance $InspectorExecutable @('--inspect-data', '--data-dir', $Source.DataDirectory)
        $details.inspection = $inspection
        if (-not $inspection.ok) { Stop-SL2 'SQLite integrity inspection failed.' }
        if ($details.Contains('schema')) {
            $known = @($details.schema.known); $applied = @($inspection.schema.applied)
            if (-not $applied.Count -or @($applied | Where-Object { $known -notcontains $_ }).Count -or @($known | Where-Object { $applied -notcontains $_ }).Count) {
                Stop-SL2 'Source database must be compatible with its release and have no pending migrations.'
            }
        }
    }
    Check 'targets_and_capacity' {
        $sourceRoots = @($Source.DataDirectory, $Source.ReleasesRoot, $Source.WorkRoot, $Source.BackupRoot, (Split-Path $Source.CertificatePath), (Split-Path (Get-SL2MigrationKey $Source)))
        $targets = @($Target.DataDirectory, $Target.ReleasesRoot, $Target.WorkRoot, $Target.BackupRoot, (Split-Path $Target.CertificatePath), (Join-SL2 (Split-Path $Target.DataDirectory) 'backup'))
        for ($i = 0; $i -lt $targets.Count; $i++) {
            $path = $targets[$i]; Test-SL2PathTree $path
            if ($path -notmatch '^[A-Za-z]:\\' -or (Test-Path -LiteralPath $path)) { Stop-SL2 'Target roots must be new, absolute local directories. Retained partial staging requires recovery, never overwrite.' }
            foreach ($sourcePath in $sourceRoots) { if (Test-SL2PathOverlap $sourcePath $path) { Stop-SL2 'Source and target roots must be disjoint.' } }
            for ($j = 0; $j -lt $i; $j++) { if (Test-SL2PathOverlap $targets[$j] $path) { Stop-SL2 'Target roots must be disjoint.' } }
            $parent = Split-Path $path
            while (-not (Test-Path -LiteralPath $parent)) { $parent = Split-Path $parent }
            $null = Get-SL2MigrationAcl $parent
        }
        if ((Split-Path $Target.CertificatePasswordFile) -ne (Split-Path $Target.CertificatePath)) { Stop-SL2 'Target TLS certificate and password file must share the TLS directory.' }
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
        $details.backup_history_files = @(Get-SL2TreeFiles $Source.BackupRoot).Count
    }
    [pscustomobject]@{ safe = (@($checks | Where-Object { -not $_.passed }).Count -eq 0); checks = $checks.ToArray(); details = [pscustomobject]$details
        warnings = @('Live inspection is observational. The source will be stopped before the final copy and integrity verification.', 'Native service, NTFS effective access and reboot acceptance must run separately on isolated fixtures before production cutover.') }
}
