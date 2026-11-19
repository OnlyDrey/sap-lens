# Isolated synthetic files and mocked SCM/network/ACL operations only. Never queries a host service.
BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    Import-TestDeploymentModule
    $script:M = 'SapLens.Deploy'
    function New-MigrationFixture {
        $root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $old = Join-Path $root 'old'; $new = Join-Path $root 'new'
        foreach ($name in 'data', 'tls', 'backup', 'history', 'work', 'releases/release/server') { New-Item -ItemType Directory -Force (Join-Path $old $name) | Out-Null }
        foreach ($name in 'tls/server.pfx', 'tls/password', 'backup/host.key', 'data/sap-lens-v2.sqlite3', 'releases/release/server/SapLens.Api.exe') { Set-Content -LiteralPath (Join-Path $old $name) 'synthetic' }
        Set-Content -LiteralPath (Join-Path $old 'backup/host.key') ([Convert]::ToBase64String([byte[]](1..32)))
        @{ schema = 1; path = (Join-Path $old 'backup/host.key') } | ConvertTo-Json | Set-Content (Join-Path $old 'data/backup-key-location.json')
        @{ source_sha = ('a' * 40); version = '2.0.0-alpha.1'; source_dirty = $false } | ConvertTo-Json | Set-Content (Join-Path $old 'releases/release/build-manifest.json')
        $script:Source = [pscustomobject]@{ ServiceName = 'SapLens2'; ServiceAccount = 'LocalSystem'; ConfigFile = (Join-Path $root 'source.json'); RepositoryPath = $root
            WorkRoot = (Join-Path $old 'work'); ReleasesRoot = (Join-Path $old 'releases'); BackupRoot = (Join-Path $old 'history'); DataDirectory = (Join-Path $old 'data')
            CertificatePath = (Join-Path $old 'tls/server.pfx'); CertificatePasswordFile = (Join-Path $old 'tls/password'); ListenAddress = '192.0.2.10'; Port = 18795
            AllowedHosts = @('lens.example.com'); TrustedProxies = @('192.0.2.1'); StopTimeoutSeconds = 1; ReadyTimeoutSeconds = 1 }
        $script:Target = $script:Source.PSObject.Copy()
        foreach ($p in 'WorkRoot', 'ReleasesRoot', 'BackupRoot', 'DataDirectory', 'CertificatePath', 'CertificatePasswordFile') { $script:Target.$p = $script:Source.$p.Replace($old, $new) }
        $script:Target.ServiceName = 'sap-lens'; $script:Target.ConfigFile = Join-Path $root 'target.json'
        $script:Source | ConvertTo-Json | Set-Content $script:Source.ConfigFile
        $script:Target | ConvertTo-Json | Set-Content $script:Target.ConfigFile
        $script:Inspector = Join-Path $old 'releases/release/server/SapLens.Api.exe'
        $script:Services = @{ SapLens2 = [pscustomobject]@{ Exists = $true; State = 'Running'; Account = 'LocalSystem'; StartMode = 'Auto'; ProcessId = 42
            PathName = ('"' + $script:Inspector + '" ' + ((Get-SL2ServiceArguments $script:Source | ForEach-Object { '"' + $_ + '"' }) -join ' ')) } }
        $script:Mutations = [Collections.Generic.List[string]]::new()
        Mock -ModuleName $M Get-SL2Service { param($Name) if ($script:Services.ContainsKey($Name)) { $script:Services[$Name] } else { [pscustomobject]@{ Exists = $false; State = 'Missing'; ProcessId = 0 } } }
        Mock -ModuleName $M Get-SL2Listener { foreach ($svc in $script:Services.Values) { if ($svc.State -eq 'Running') { $svc.ProcessId } } }
        Mock -ModuleName $M Get-SL2Link { '' }
        $script:ApprovedRoots = @($root)
        Mock -ModuleName $M Get-SL2MigrationProvisioningRoots { $script:ApprovedRoots }
        $script:SafeAcl = @([pscustomobject]@{ Sid='S-1-5-18'; Rights=0x1F01FF; Allow=$true; InheritOnly=$false; Inherited=$false; ContainerInherit=$true; ObjectInherit=$true }, [pscustomobject]@{ Sid='S-1-5-32-544'; Rights=0x1F01FF; Allow=$true; InheritOnly=$false; Inherited=$false; ContainerInherit=$true; ObjectInherit=$true })
        Mock -ModuleName $M Get-SL2AclRules { $script:SafeAcl }
        Mock -ModuleName $M New-SL2DirectoryWithAcl { param($Path, $Security) New-Item -ItemType Directory -Path $Path -ErrorAction Stop | Out-Null }
        # Canonical production paths are tested separately; this state machine uses isolated TestDrive roots.
        Mock -ModuleName $M Assert-SL2CanonicalTargetLayout { }
        Mock -ModuleName $M Test-SL2MigrationEnvironment { }
        Mock -ModuleName $M Test-SL2MigrationTls { }
        Mock -ModuleName $M Get-SL2FreeSpace { 100GB }
        Mock -ModuleName $M Invoke-SL2Process { [pscustomobject]@{ ExitCode = 0; Output = @() } }
        Mock -ModuleName $M Invoke-SL2Http { param($Url, $HostHeader) @{ Status = 200; Body = (@{ source_sha = ('a' * 40); version = '2.0.0-alpha.1' } | ConvertTo-Json) } }
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments)
            switch ($Arguments[0]) {
                '--inspect-data' { [pscustomobject]@{ capabilities = @('rebase-upload-paths-v1'); source_paths = [pscustomobject]@{}; ok = $true; databases = @('synthetic'); schema = @{ compatible = $true; applied = @('m1') } } }
                '--rebase-upload-paths' { @{ rebased = 0; changed_fields = @() } }
                '--schema-info' { [pscustomobject]@{ database_exists = $false; compatible = $true; pending = @('m1'); applied = @(); known = @('m1') } }
            }
        }
        Mock -ModuleName $M Stop-SL2Service { throw 'Preflight may never stop a service' }
        Mock -ModuleName $M Start-SL2Service { throw 'Preflight may never start a service' }
        Mock -ModuleName $M Set-SL2ServiceEntry { throw 'Preflight may never create a service' }
        Mock -ModuleName $M Write-SL2Journal { throw 'Preflight may never write a journal' }
    }
}

Describe 'Migration preflight: source release integrity' {
    BeforeEach { New-MigrationFixture }
    It 'verifies the running release as a server package and records the result, including omitted Desktop and symbol files' {
        Mock -ModuleName $M Test-SL2PublishedRelease { [pscustomobject]@{ Verified = $true; Output = @('Release verified as a server package (undeclared: published before deployment-package.json existed): 3 of 5 artifacts present and matching, 2 omitted', '  omitted (not part of a server package): desktop/SapLens.exe') } }
        $preflight = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        ($preflight.checks | Where-Object name -eq 'source_release').passed | Should -BeTrue
        $preflight.details.release_verification | Should -Contain '  omitted (not part of a server package): desktop/SapLens.exe'
        Should -Invoke -ModuleName $M Test-SL2PublishedRelease -Times 1 -ParameterFilter { $Folder -eq (Split-Path (Split-Path $script:Inspector)) }
    }
    It 'blocks migration when the running release does not verify, naming the defect and changing nothing' {
        Mock -ModuleName $M Test-SL2PublishedRelease { [pscustomobject]@{ Verified = $false; Output = @('verify-release: missing: server/e_sqlite3.dll', 'verify-release: SHA256SUMS lists a missing file: server/e_sqlite3.dll') } }
        $preflight = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $preflight.safe | Should -BeFalse
        $check = $preflight.checks | Where-Object name -eq 'source_release'
        $check.passed | Should -BeFalse
        $check.message | Should -Match 'Source release verification failed \(verify-release.ps1 -Scope Server\): verify-release: missing: server/e_sqlite3.dll'
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
        Should -Invoke -ModuleName $M Set-SL2ServiceEntry -Times 0
    }
}

Describe 'Migration preflight: NTFS permissions' {
    BeforeEach { New-MigrationFixture }
    It 'blocks migration on broad access to private source state, names path, principal and right, and passes once the ACL is protected' {
        $data = [IO.Path]::GetFullPath($script:Source.DataDirectory)
        $script:Unsafe = $true
        Mock -ModuleName $M Get-SL2AclRules {
            param($Path)
            $script:SafeAcl
            if ($script:Unsafe -and [IO.Path]::GetFullPath($Path) -eq $data) { [pscustomobject]@{ Sid = 'S-1-5-11'; Rights = 0x301BF; Allow = $true; Inherited = $true; ContainerInherit = $true; ObjectInherit = $true; InheritOnly = $false } }
        }
        $preflight = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $check = $preflight.checks | Where-Object name -eq 'private_state'
        $check.passed | Should -BeFalse
        $check.message | Should -BeLike "*$data (source data): Authenticated Users has write access (0x000301BF, inherited, this folder and new children)*"
        $check.message | Should -BeLike '*-Action ProtectAcl*'
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
        $script:Unsafe = $false                                                    # after ProtectAcl
        ((Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).checks | Where-Object name -eq 'private_state').passed | Should -BeTrue
    }
    It 'names an existing target root instead of a generic refusal' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        New-Item -ItemType Directory -Force $script:Target.WorkRoot | Out-Null
        $check = (Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).checks | Where-Object name -eq 'targets_and_capacity'
        $check.message | Should -BeLike "Target root $($script:Target.WorkRoot) already exists*"
    }
}

Describe 'Migration backup, journal and staging contracts' {
    BeforeEach { New-MigrationFixture }
    It 'durably records intent on the source and mirrors it once the target work directory exists' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        $preflight = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $journal = New-SL2MigrationJournal $script:Source $script:Target $preflight $script:Inspector
        Set-SL2MigrationPhase $journal 'backup'
        (Read-SL2MigrationJournal $script:Source).phase | Should -Be 'backup'
        Test-Path $script:Target.WorkRoot | Should -BeFalse
        New-Item -ItemType Directory -Path $script:Target.WorkRoot -Force | Out-Null
        $journal.target_prepared = $true
        Set-SL2MigrationPhase $journal 'staging'
        (Read-SL2MigrationJournal $script:Target).id | Should -Be $journal.id
        (Read-SL2MigrationJournal $script:Target).phase | Should -Be 'staging'
        Test-Path (Join-Path $script:Source.WorkRoot 'migration-journal.json.previous') | Should -BeTrue
        { New-SL2MigrationJournal $script:Source $script:Target $preflight $script:Inspector } | Should -Throw '*journal exists*'
    }
    It 'refuses unverified backups before service control' {
        Mock -ModuleName $M Invoke-SL2Maintenance { param($ExePath, $Arguments) if ($Arguments[0] -eq '--backup-local') { @{ file = 'synthetic.slbak'; sha256 = 'a'; size = 1 } } else { @{ verified = $false; sha256 = 'a' } } }
        { New-SL2MigrationBackup $script:Source $script:Inspector } | Should -Throw '*verification failed*'
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
    }
    It 'never mirrors a journal into a target directory that it has not created' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        $preflight = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $journal = New-SL2MigrationJournal $script:Source $script:Target $preflight $script:Inspector
        New-Item -ItemType Directory $script:Target.WorkRoot | Out-Null
        $sentinel = Join-Path $script:Target.WorkRoot 'migration-journal.json'
        Set-Content $sentinel 'unrelated retained file'
        Set-SL2MigrationPhase $journal 'target_preparation'
        (Get-Content $sentinel -Raw).Trim() | Should -Be 'unrelated retained file'
        Test-Path "$sentinel.previous" | Should -BeFalse
        (Read-SL2MigrationJournal $script:Source).phase | Should -Be 'target_preparation'
    }
    It 'copies disjoint trees with their NTFS security and verifies content before allowing use' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        Mock -ModuleName $M Invoke-SL2Process {
            param($File, $Arguments)
            $from = $Arguments[0]; $to = $Arguments[1]
            foreach ($item in Get-ChildItem -LiteralPath $from -Force) { Copy-Item -LiteralPath $item.FullName -Destination $to -Recurse }
            [pscustomobject]@{ ExitCode = 1; Output = @() }
        }
        Copy-SL2MigrationTree $script:Source.DataDirectory $script:Target.DataDirectory $script:ApprovedRoots
        (Test-SL2InventoryEqual @(Get-SL2TreeInventory $script:Source.DataDirectory) @(Get-SL2TreeInventory $script:Target.DataDirectory)) | Should -BeTrue
        { Copy-SL2MigrationTree $script:Source.DataDirectory $script:Target.DataDirectory $script:ApprovedRoots } | Should -Throw '*never merges*'
    }
    It 'retains partial copies and refuses a robocopy failure or content mismatch' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        Mock -ModuleName $M Invoke-SL2Process { [pscustomobject]@{ ExitCode = 8; Output = @() } }
        { Copy-SL2MigrationTree $script:Source.DataDirectory $script:Target.DataDirectory $script:ApprovedRoots } | Should -Throw '*staging failed*'
        Test-Path $script:Target.DataDirectory | Should -BeTrue
        { Copy-SL2MigrationTree $script:Source.DataDirectory (Join-Path $script:Source.DataDirectory 'nested') $script:ApprovedRoots } | Should -Throw '*overlap*'
        Mock -ModuleName $M Invoke-SL2Process { [pscustomobject]@{ ExitCode = 0; Output = @() } }
        { Copy-SL2MigrationTree (Split-Path $script:Source.CertificatePath) (Split-Path $script:Target.CertificatePath) $script:ApprovedRoots } | Should -Throw '*differs*'
    }
    It 'rejects content and ACL drift independently' {
        $left = @([pscustomobject]@{ path = 'file'; hash = 'a'; acl = 'private' })
        (Test-SL2InventoryEqual $left @([pscustomobject]@{ path = 'file'; hash = 'b'; acl = 'private' })) | Should -BeFalse
        (Test-SL2InventoryEqual $left @([pscustomobject]@{ path = 'file'; hash = 'a'; acl = 'public' })) | Should -BeFalse
    }
}

# Windows only: drives C:\ target roots, NTFS ACLs (Get-Acl) and robocopy; runs in CI's windows-latest job.
Describe 'Journaled service cutover and interruption recovery' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
    BeforeEach {
        New-MigrationFixture
        $script:Failure = ''; $script:BackupCount = 0; $script:ActiveLink = ''
        Mock -ModuleName $M Get-SL2Link { param($Link) if ($Link -eq (Get-SL2CurrentLink $script:Target)) { $script:ActiveLink } else { '' } }
        Mock -ModuleName $M Invoke-SL2Process {
            param($File, $Arguments)
            if ($File -eq 'robocopy.exe') {
                if ($script:Failure -eq 'copy') { return @{ ExitCode = 8; Output = @() } }
                foreach ($item in Get-ChildItem -LiteralPath $Arguments[0] -Force) { Copy-Item -LiteralPath $item.FullName -Destination $Arguments[1] -Recurse }
            }
            if ($File -eq 'sc.exe') {
                $script:Mutations.Add(($Arguments -join ' '))
                if ($Arguments[0] -eq 'config') {
                    if ($script:Services.ContainsKey($Arguments[1])) { $script:Services[$Arguments[1]].StartMode = $(if ($Arguments[3] -eq 'disabled') { 'Disabled' } elseif ($Arguments[3] -eq 'auto') { 'Auto' } else { 'Manual' }) }
                }
            }
            @{ ExitCode = 0; Output = @() }
        }
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments)
            switch ($Arguments[0]) {
                '--rebase-upload-paths' { @{ rebased = 0; changed_fields = @() } }
                '--schema-info' { if ($Arguments[2] -like '*.schema-probe-*') { @{ database_exists = $false; compatible = $true; known = @('m1'); pending = @('m1'); applied = @() } } else { @{ database_exists = $true; compatible = $true; known = @('m1'); pending = @(); applied = @('m1') } } }
                '--inspect-data' { @{ capabilities = @('rebase-upload-paths-v1'); source_paths = [pscustomobject]@{}; ok = ($script:Failure -ne 'integrity' -or $Arguments[2] -eq $script:Source.DataDirectory); schema = @{ applied = @('m1') } } }
                '--backup-local' {
                    $script:BackupCount++
                    if ($script:Failure -eq 'target-race' -and $script:BackupCount -eq 1) {
                        New-Item -ItemType Directory $script:Target.WorkRoot -Force | Out-Null
                        Set-Content (Join-Path $script:Target.WorkRoot 'migration-journal.json') 'unrelated retained file'
                    }
                    if ($script:Failure -eq 'backup') { throw 'synthetic backup failure' }
                    $file = Join-Path $Arguments[1] ('backup-' + $script:BackupCount + '.slbak')
                    Set-Content -LiteralPath $file 'synthetic sealed archive'
                    @{ file = $file; sha256 = 'verified'; size = 1 }
                }
                '--backup-verify' { @{ verified = $true; sha256 = 'verified' } }
            }
        }
        Mock -ModuleName $M Stop-SL2Service { param($Name) $script:Mutations.Add("stop:$Name"); $script:Services[$Name].State = 'Stopped'; if ($script:Failure -eq 'stop' -and $Name -eq 'SapLens2') { throw 'interrupted after stopping' } }
        Mock -ModuleName $M Set-SL2ServiceEntry {
            param($Config, $Binary, $Exists, $StartMode)
            $script:Mutations.Add('create:sap-lens')
            $script:Services['sap-lens'] = [pscustomobject]@{ Exists = $true; State = 'Stopped'; Account = $Config.ServiceAccount; StartMode = 'Manual'; ProcessId = 43; PathName = $Binary }
            if ($script:Failure -eq 'create') { throw 'interrupted after creating' }
        }
        Mock -ModuleName $M Grant-SL2Access { }
        Mock -ModuleName $M Set-SL2Link { param($Link, $Target) $script:ActiveLink = $Target }
        Mock -ModuleName $M Start-SL2Service {
            param($Name)
            $script:Mutations.Add("start:$Name")
            if ($Name -eq 'sap-lens') {
                $script:Services.SapLens2.State | Should -Be 'Stopped'
                $script:Services.SapLens2.StartMode | Should -Be 'Disabled'
                if ($script:Failure -eq 'startup') { throw 'synthetic startup failure' }
                if ($script:Failure -eq 'written') { Add-Content -LiteralPath (Join-Path $script:Target.DataDirectory 'sap-lens-v2.sqlite3') 'new committed data' }
            }
            $script:Services[$Name].State = 'Running'
        }
        Mock -ModuleName $M Wait-SL2Ready { param($Config, $Commit, $Version) if ($Config.ServiceName -eq 'sap-lens' -and $script:Failure -in @('readiness', 'written')) { throw 'synthetic readiness failure' }; @{ process_id = 43; identity = @{ source_sha = $Commit; version = $Version } } }
    }
    It 'backs up online and offline, preserves identity, moves private state and retains the disabled legacy service' {
        $result = Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector
        $result.phase | Should -Be 'complete'
        $script:BackupCount | Should -Be 2
        $script:Services.SapLens2.State | Should -Be 'Stopped'
        $script:Services.SapLens2.StartMode | Should -Be 'Disabled'
        $script:Services['sap-lens'].State | Should -Be 'Running'
        $script:Services['sap-lens'].Account | Should -Be 'LocalSystem'
        $journal = Read-SL2MigrationJournal $script:Target
        (Get-Content (Join-Path $script:Target.DataDirectory 'backup-key-location.json') -Raw | ConvertFrom-Json).path | Should -Be $journal.key_after
        Test-Path $journal.key_before | Should -BeTrue
        Test-Path $journal.key_after | Should -BeTrue
        @($script:Mutations | Where-Object { $_ -match 'delete' }).Count | Should -Be 0
        $calls = $script:Mutations.Count
        (Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector).phase | Should -Be 'complete'
        $script:Mutations.Count | Should -Be $calls
    }
    It 'refuses a target directory appearing after preflight without modifying its files or stopping the source' {
        $script:Failure = 'target-race'
        { Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector } | Should -Throw '*safely returned*'
        (Get-Content (Join-Path $script:Target.WorkRoot 'migration-journal.json') -Raw).Trim() | Should -Be 'unrelated retained file'
        $script:Services.SapLens2.State | Should -Be 'Running'
        $script:Mutations | Should -Not -Contain 'stop:SapLens2'
        $script:Mutations | Should -Not -Contain 'create:sap-lens'
    }
    It 'returns to the untouched source after <Failure> failure' -ForEach @(
        @{ Failure = 'backup' }, @{ Failure = 'copy' }, @{ Failure = 'stop' }, @{ Failure = 'integrity' }, @{ Failure = 'create' }, @{ Failure = 'startup' }, @{ Failure = 'readiness' }
    ) {
        $script:Failure = $Failure
        { Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector } | Should -Throw '*safely returned*'
        (Read-SL2MigrationJournal $script:Source).phase | Should -Be 'rolled_back'
        $script:Services.SapLens2.State | Should -Be 'Running'
        Test-Path $script:Source.DataDirectory | Should -BeTrue
        if ($script:Services.ContainsKey('sap-lens')) { $script:Services['sap-lens'].StartMode | Should -Be 'Disabled'; $script:Services['sap-lens'].State | Should -Be 'Stopped' }
    }
    It 'stops for manual recovery when target writes make rollback unproven' {
        $script:Failure = 'written'
        { Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector } | Should -Throw '*manual recovery*'
        $journal = Read-SL2MigrationJournal $script:Source
        $journal.phase | Should -Be 'manual_recovery_required'
        $journal.recovery | Should -Match 'NEW directory'
        $script:Services.SapLens2.State | Should -Be 'Stopped'
        $script:Services['sap-lens'].State | Should -Be 'Stopped'
        Get-Content (Join-Path $script:Target.DataDirectory 'sap-lens-v2.sqlite3') | Should -Contain 'new committed data'
    }
    It 'recovers a persisted cutover intent after interruption and retains both service records' {
        $null = Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector
        $journal = Read-SL2MigrationJournal $script:Source
        $journal.phase = 'service_startup'; Write-SL2MigrationJournal $journal
        (Invoke-SL2MigrationRecovery $script:Source).phase | Should -Be 'rolled_back'
        (Invoke-SL2MigrationRecovery $script:Source).changed | Should -BeFalse
        $script:Services.SapLens2.State | Should -Be 'Running'
        $script:Services['sap-lens'].StartMode | Should -Be 'Disabled'
    }
    It 'refuses recovery after configuration drift or an unrelated canonical service appears' {
        $null = Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector
        Add-Content -LiteralPath $script:Target.ConfigFile ' '
        { Invoke-SL2MigrationRecovery $script:Source -Rollback } | Should -Throw '*configuration changed*'
        $script:Services['sap-lens'].State | Should -Be 'Running'
    }
    It 'supports Build and Replace and ordinary release rollback with the canonical persistent paths' {
        Mock -ModuleName $M Write-SL2Journal { param($Config, $Journal) $Journal.updated = [DateTime]::UtcNow.ToString('o'); $Journal | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Get-SL2JournalPath $Config) }
        $null = Invoke-SL2MigrateService $script:Source $script:Target $script:Inspector
        { Assert-SL2DeploymentAllowed $script:Source } | Should -Throw '*inactive migration*'
        { Assert-SL2DeploymentAllowed $script:Target } | Should -Not -Throw
        $canonical = Read-SapLensSettings (Join-Path $script:Target.WorkRoot 'deploy.local.json')
        $canonical.ServiceName | Should -Be 'sap-lens'
        $canonical.ServiceAccount | Should -Be 'LocalSystem'
        $release = Join-Path $script:Target.ReleasesRoot 'next'
        New-Item -ItemType Directory -Path (Join-Path $release 'server') -Force | Out-Null
        @{ source_sha = ('b' * 40); version = '2.0.0-alpha.1' } | ConvertTo-Json | Set-Content (Join-Path $release 'build-manifest.json')
        $null = New-SL2Run $canonical 'deploy'
        (Invoke-SL2Deploy $canonical $release ('b' * 40)).deployed | Should -BeTrue
        (Test-SL2MigrationComplete $canonical).commit | Should -Be ('b' * 40)
        $script:Services.SapLens2.State | Should -Be 'Stopped'
        (Invoke-SL2Rollback $canonical '').rolled_back | Should -BeTrue
        $script:ActiveLink | Should -Not -Be $release
        $script:Services.SapLens2.StartMode | Should -Be 'Disabled'
    }
    It 'blocks ordinary service changes while migration is unfinished' {
        $preflight = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $journal = New-SL2MigrationJournal $script:Source $script:Target $preflight $script:Inspector
        Set-SL2MigrationPhase $journal 'verified_backup'
        { Invoke-SL2Deploy $script:Source 'unused' 'unused' } | Should -Throw '*Migration is unfinished*'
        { Install-SL2Service $script:Source -Reconfigure } | Should -Throw '*Migration is unfinished*'
        { Invoke-SL2Recover $script:Source } | Should -Throw '*Migration is unfinished*'
    }
}

Describe 'Read-only identity and directory migration preflight' {
    BeforeEach { New-MigrationFixture }
    It 'checks only a matching unique acceptance service pair without querying canonical services' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        $prefix = 'SapLens.Acceptance-' + [guid]::NewGuid().ToString('N')
        $script:Source.ServiceName = "$prefix-old"; $script:Target.ServiceName = "$prefix-new"
        $script:Services[$script:Source.ServiceName] = $script:Services.SapLens2
        $script:Services.Remove('SapLens2')
        (Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).safe | Should -BeTrue
        Should -Invoke -ModuleName $M Get-SL2Service -Times 0 -ParameterFilter { $Name -in @('sap-lens', 'SapLens2') }
        $script:Target.ServiceName = 'sap-lens'
        { Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector } | Should -Throw '*matching unique*'
    }
    It 'blocks a healthy listener answering with the wrong source release identity' {
        Mock -ModuleName $M Invoke-SL2Http { @{ Status = 200; Body = '{"source_sha":"wrong","version":"2.0.0-alpha.1"}' } }
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        ($result.checks | Where-Object name -eq 'source_release').message | Should -Match 'identity does not match'
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
    }
    It 'refuses runtime source paths inside the installation being retired' {
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments)
            if ($Arguments[0] -eq '--schema-info') { return @{ known = @('m1') } }
            @{ capabilities = @('rebase-upload-paths-v1'); ok = $true; schema = @{ applied = @('m1') }; source_paths = [pscustomobject]@{ data_csv_path = (Join-Path $script:Source.WorkRoot 'roles.csv') } }
        }
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        ($result.checks | Where-Object name -eq 'sqlite_consistency').message | Should -Match 'depends on the old installation'
    }
    It 'plans managed-upload rebasing without changing any source files' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments)
            if ($Arguments[0] -eq '--schema-info') { return @{ known = @('m1') } }
            @{ capabilities = @('rebase-upload-paths-v1'); ok = $true; schema = @{ applied = @('m1') }; source_paths = [pscustomobject]@{ data_csv_path = (Join-Path $script:Source.DataDirectory 'sources/roles-0123456789abcdef.csv') } }
        }
        $before = @(Get-SL2TreeInventory $script:Source.DataDirectory)
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $result.safe | Should -BeTrue
        $result.details.source_paths_to_rebase | Should -Contain 'data_csv_path'
        (Test-SL2InventoryEqual $before @(Get-SL2TreeInventory $script:Source.DataDirectory)) | Should -BeTrue
        Should -Invoke -ModuleName $M Invoke-SL2Maintenance -Times 0 -ParameterFilter { $Arguments[0] -eq '--rebase-upload-paths' }
    }
    It 'refuses an inspector without upload-copy rebasing support before service control' {
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments)
            if ($Arguments[0] -eq '--schema-info') { return @{ known = @('m1') } }
            @{ capabilities = @(); ok = $true; schema = @{ applied = @('m1') }; source_paths = [pscustomobject]@{} }
        }
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        ($result.checks | Where-Object name -eq 'sqlite_consistency').message | Should -Match 'lacks verified upload rebasing'
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
    }
    It 'uses an existing allowed hostname for direct listener probes' {
        $null = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        Should -Invoke -ModuleName $M Invoke-SL2Http -Times 1 -ParameterFilter { $Url -eq 'https://192.0.2.10:18795/health/ready' -and $HostHeader -eq 'lens.example.com:18795' }
    }
    It 'blocks pending v1 <Name> without changing completed migration evidence' -ForEach @(@{Name='activation'}, @{Name='rollback'}) {
        New-Item -ItemType Directory (Join-Path $script:Source.DataDirectory 'migration') | Out-Null
        Set-Content (Join-Path $script:Source.DataDirectory "migration/pending-$Name.json") '{}'
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        ($result.checks | Where-Object name -eq 'recovery_state').message | Should -Match 'v1 migration activation or rollback is pending'
    }
    It 'checks all prerequisites without writing installation files or controlling services' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        $before = @(Get-ChildItem (Split-Path $script:Source.ConfigFile) -Recurse -Force | ForEach-Object FullName)
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $result.safe | Should -BeTrue
        $result.checks.Count | Should -Be 7
        @(Get-ChildItem (Split-Path $script:Source.ConfigFile) -Recurse -Force | ForEach-Object FullName) | Should -Be $before
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
        Should -Invoke -ModuleName $M Write-SL2Journal -Times 0
    }
    It 'blocks an existing <Existing> service without adopting it' -ForEach @(@{ Existing = 'sap-lens' }, @{ Existing = 'SapLens' }) {
        $script:Services[$Existing] = $script:Services.SapLens2.PSObject.Copy()
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $result.safe | Should -BeFalse
        ($result.checks | Where-Object name -eq 'service_conflicts').message | Should -Match 'already exists'
    }
    It 'blocks network changes, unsafe targets, and insufficient capacity independently' {
        $script:Target.Port = 443
        $script:Target.DataDirectory = $script:Source.DataDirectory
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        @($result.checks | Where-Object { -not $_.passed }).Count | Should -Be 2
        $script:Target.DataDirectory = Join-Path (Split-Path $script:Target.WorkRoot) 'data'
        Mock -ModuleName $M Get-SL2FreeSpace { 0 }
        (Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).safe | Should -BeFalse
    }
    It 'reports integrity and pending-migration failures as blocking conditions' {
        Mock -ModuleName $M Invoke-SL2Maintenance { param($ExePath, $Arguments) if ($Arguments[0] -eq '--inspect-data') { @{ ok = $false } } else { @{ database_exists = $true; compatible = $true; pending = @('future') } } }
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        @($result.checks | Where-Object { -not $_.passed }).name | Should -Contain 'sqlite_consistency'
    }
    It 'blocks a previous migration journal and does not overwrite retained staging' {
        Set-Content (Join-Path $script:Source.WorkRoot 'migration-journal.json') '{}'
        New-Item -ItemType Directory -Path $script:Target.DataDirectory -Force | Out-Null
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        @($result.checks | Where-Object { -not $_.passed }).name | Should -Contain 'recovery_state'
        @($result.checks | Where-Object { -not $_.passed }).name | Should -Contain 'targets_and_capacity'
    }
    It 'rejects source path aliases and source service argument drift' -Skip:([System.IO.Path]::DirectorySeparatorChar -eq '/') {
        $script:Services.SapLens2.PathName += ' --unexpected-option x'
        (Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).safe | Should -BeFalse
        (Test-SL2PathOverlap 'C:\old\data' 'C:\old\data\child') | Should -BeTrue
        (Test-SL2PathOverlap 'C:\old\data' 'C:\old\database') | Should -BeFalse
    }
}
