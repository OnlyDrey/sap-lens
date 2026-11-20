# NTFS policy for AuthLens private state (AuthLens.Acl.ps1): the pure rule evaluation by well-known SID, the audit plan and refusals, and the
# explicit ProtectAcl/RestoreAcl remediation with synthetic folders. ACL reads and icacls are replaced; no real ACL or service is touched.
BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    # Off Windows the ACL cmdlet does not exist: a stand-in returns one fixed protected DACL so inventories, backups and restore
    # verification run against the same rule model (Get-ALAclRules is replaced below). On Windows the real cmdlet is used.
    if (-not (Get-Command Get-Acl -ErrorAction SilentlyContinue)) {
        function global:Get-Acl([string]$LiteralPath) {
            [pscustomobject]@{ Path = $LiteralPath } | Add-Member -PassThru ScriptMethod GetSecurityDescriptorSddlForm { param($Sections) 'D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' }
        }
    }
    Import-TestDeploymentModule
    $script:M = 'AuthLens.Deploy'
    # FileSystemRights as Windows reports them: Modify, ReadAndExecute, FullControl, and the ProgramData "Users may create" pattern (WD, AD, WEA, WA).
    $script:Modify = 0x301BF; $script:ReadExecute = 0x1200A9; $script:Full = 0x1F01FF; $script:CreateOnly = 278
    function Rule([string]$Sid, [int64]$Rights, [switch]$Inherited, [switch]$Children, [switch]$InheritOnly, [switch]$Deny) {
        [pscustomobject]@{ Sid = $Sid; Rights = $Rights; Allow = -not $Deny; Inherited = [bool]$Inherited; ContainerInherit = [bool]$Children; ObjectInherit = [bool]$Children; InheritOnly = [bool]$InheritOnly }
    }
    $script:Safe = @((Rule 'S-1-5-18' $script:Full -Children), (Rule 'S-1-5-32-544' $script:Full -Children))
    function New-AclFixture([string]$Account = 'LocalSystem') {
        $root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $install = Join-Path $root 'AuthLens'; $other = Join-Path $root 'other'
        foreach ($name in 'data/logs', 'tls', 'keys', 'backups/predeploy', 'deployment', 'releases/r1/server', 'config') { New-Item -ItemType Directory -Force (Join-Path $install $name) | Out-Null }
        New-Item -ItemType Directory -Force $other | Out-Null
        foreach ($name in 'tls/server.pfx', 'tls/cert-password', 'data/authlens.sqlite3', 'data/logs/server.log') { Set-Content (Join-Path $install $name) 'synthetic' }
        Set-Content (Join-Path $install 'keys/backup.key') ([Convert]::ToBase64String([byte[]](1..32)))
        @{ schema = 1; path = (Join-Path $install 'keys/backup.key') } | ConvertTo-Json | Set-Content (Join-Path $install 'data/backup-key-location.json')
        Set-Content (Join-Path $install 'config/deploy.json') '{}'
        $script:Config = [pscustomobject]@{ ServiceName = 'AuthLens'; ServiceAccount = $Account; ConfigFile = (Join-Path $install 'config/deploy.json')
            WorkRoot = (Join-Path $install 'deployment'); ReleasesRoot = (Join-Path $install 'releases'); BackupRoot = (Join-Path $install 'backups/predeploy')
            DataDirectory = (Join-Path $install 'data'); CertificatePath = (Join-Path $install 'tls/server.pfx'); CertificatePasswordFile = (Join-Path $install 'tls/cert-password') }
        $script:Paths = @{ Root = $root; Install = $install; Other = $other }
        $script:ApprovedRoots = @($root)
        $script:AclBackupRoot = Join-Path $root 'acl-recovery'
        $script:CreatedSecure = [Collections.Generic.List[string]]::new()
        # An installation as found on a reported VM: Authenticated Users Modify inherited across the whole tree.
        $script:Broad = @{}
        $script:Broad[$install] = @(Rule 'S-1-5-11' $script:Modify -Children)
        foreach ($path in Get-ChildItem $install -Recurse -Force | ForEach-Object FullName) { $script:Broad[$path] = @(Rule 'S-1-5-11' $script:Modify -Children -Inherited) }
        $script:Protected = [Collections.Generic.HashSet[string]]::new()
        $script:Icacls = [Collections.Generic.List[string]]::new()
        $script:ManifestChecked = 0
        Mock -ModuleName $M Reset-ALAclFile { param($Path) $script:Icacls.Add("native file reset $Path") }
        if ([IO.Path]::DirectorySeparatorChar -ne '\') {
            # Windows-only security-descriptor types: a protected stand-in, and exact SDDL comparison instead of the binary DACL comparison.
            Mock -ModuleName $M New-ALProtectedDirectorySecurity { [pscustomobject]@{ AreAccessRulesProtected = $true } }
            Mock -ModuleName $M Test-ALDaclEqual { param($Expected, $Actual) $Expected -ceq $Actual }
        }
        Mock -ModuleName $M Get-ALAclRules {
            param($Path)
            $full = [IO.Path]::GetFullPath($Path).TrimEnd('/')
            if ($script:Protected.Contains($full)) { return $script:Safe }
            foreach ($protected in $script:Protected) { if ($full.StartsWith($protected + '/')) { return $script:Safe } }
            if ($script:Broad.ContainsKey($full)) { $script:Safe + $script:Broad[$full] } else { $script:Safe }
        }
        Mock -ModuleName $M New-ALDirectoryWithAcl {
            param($Path, $Security)
            $Security.AreAccessRulesProtected | Should -BeTrue
            $script:CreatedSecure.Add($Path)
            New-Item -ItemType Directory -Path $Path -ErrorAction Stop | Out-Null
            [void]$script:Protected.Add([IO.Path]::GetFullPath($Path).TrimEnd('/'))
        }
        Mock -ModuleName $M Invoke-ALProcess {
            param($File, $Arguments)
            $script:Icacls.Add(($Arguments -join ' '))
            if ($Arguments -contains '/inheritance:r') {
                $manifest = @(Get-ChildItem $script:AclBackupRoot -Filter acl-backup.json -Recurse)
                $manifest.Count | Should -Be 1
                $saved = Get-Content $manifest[0].FullName -Raw | ConvertFrom-Json
                foreach ($entry in @($saved.entries | Where-Object { -not $_.created })) {
                    (Get-FileHash $entry.file).Hash | Should -Be $entry.sha256
                    Test-ALAclBackupFile $entry
                }
                $script:ManifestChecked++
                [void]$script:Protected.Add([IO.Path]::GetFullPath($Arguments[0]).TrimEnd('/'))
            }
            if ($Arguments -contains '/save') {
                $parent = Split-Path $Arguments[0]
                $lines = @((Split-Path $Arguments[0] -Leaf), (Get-Acl -LiteralPath $Arguments[0]).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access))
                [IO.File]::WriteAllLines($Arguments[2], [string[]]$lines, [Text.Encoding]::Unicode)
            }
            [pscustomobject]@{ ExitCode = 0; Output = @() }
        }
    }
}

Describe 'NTFS policy by well-known SID' {
    It 'reports <Name>' -ForEach @(
        @{ Name = 'inherited Authenticated Users Modify on private state as write'; Rule = { Rule 'S-1-5-11' 0x301BF -Children -Inherited }; Class = 'private'; Access = 'write'; Applies = 'this folder and new children' }
        @{ Name = 'Users read on private state as read'; Rule = { Rule 'S-1-5-32-545' 0x1200A9 -Children }; Class = 'private'; Access = 'read'; Applies = 'this folder and new children' }
        @{ Name = 'an inherit-only create right on a parent (the ProgramData pattern)'; Rule = { Rule 'S-1-5-32-545' 278 -Children -InheritOnly -Inherited }; Class = 'binaries'; Access = 'write'; Applies = 'new children only' }
        @{ Name = 'Domain Users by SID pattern'; Rule = { Rule 'S-1-5-21-1004336348-1177238915-682003330-513' 0x301BF }; Class = 'binaries'; Access = 'write'; Applies = 'this object' }
        @{ Name = 'GENERIC_READ on private state'; Rule = { Rule 'S-1-1-0' 2147483648 }; Class = 'private'; Access = 'read'; Applies = 'this object' }
    ) {
        $finding = @(Get-ALAclFindings @(& $Rule) $Class $true)
        $finding.Count | Should -Be 1
        ($finding[0].access, $finding[0].applies) | Should -Be @($Access, $Applies)
    }

    It 'accepts <Name>' -ForEach @(
        @{ Name = 'read and execute for Users on release binaries'; Rule = { Rule 'S-1-5-32-545' 0x1200A9 -Children }; Class = 'binaries'; Container = $true }
        @{ Name = 'SYSTEM, Administrators and the service account with full control'; Rule = { @((Rule 'S-1-5-18' 0x1F01FF -Children), (Rule 'S-1-5-32-544' 0x1F01FF), (Rule 'S-1-5-80-1234' 0x301BF -Children)) }; Class = 'private'; Container = $true }
        @{ Name = 'a broad deny rule'; Rule = { Rule 'S-1-1-0' 0x1F01FF -Deny }; Class = 'private'; Container = $true }
        @{ Name = 'an individual local user'; Rule = { Rule 'S-1-5-21-1-2-3-1001' 0x1F01FF }; Class = 'private'; Container = $true }
        @{ Name = 'an inherit-only rule on a file (it applies to nothing)'; Rule = { Rule 'S-1-5-11' 0x301BF -Children -InheritOnly }; Class = 'private'; Container = $false }
        @{ Name = 'read attributes and permissions only'; Rule = { Rule 'S-1-5-11' (0x80 + 0x20000) }; Class = 'private'; Container = $true }
    ) {
        @(Get-ALAclFindings @(& $Rule) $Class $Container).Count | Should -Be 0
    }
}

Describe 'ACL audit plan and refusals' {
    BeforeEach { New-AclFixture }
    It 'classifies data, backups, TLS, key, deployment state, releases and configuration' {
        $plan = @(Get-ALAclPlan $script:Config)
        ($plan | Where-Object Class -eq 'private' | ForEach-Object Role) | Should -Be @('data', 'pre-deployment backups', 'TLS', 'backup key', 'deployment state')
        ($plan | Where-Object Class -eq 'binaries' | ForEach-Object Role) | Should -Be @('releases', 'configuration', 'configuration folder')
        ($plan | Where-Object Role -eq 'data').Grant | Should -Be 'M'                                       # database, logs and application backups
        @($plan | Where-Object Role -in 'TLS', 'backup key' | ForEach-Object Grant) | Should -Be @('R', 'R')
        ($plan | Where-Object Role -eq 'releases').Grant | Should -Be 'RX'
        @($plan | Where-Object Role -in 'pre-deployment backups', 'deployment state', 'configuration', 'configuration folder' | Where-Object Grant).Count | Should -Be 0
        ($plan | Where-Object Role -eq 'backup key').Path | Should -Be (Join-Path $script:Paths.Install 'keys')
    }
    It 'refuses the reported VM state, naming path, principal and right, and finds explicit broad grants on descendants' {
        $script:Broad[(Join-Path $script:Paths.Install 'tls/cert-password')] = @(Rule 'S-1-5-32-545' 0x1200A9)
        $report = Get-ALAclReport (Get-ALAclPlan $script:Config)
        $report.safe | Should -BeFalse
        { Assert-ALAclPlan (Get-ALAclPlan $script:Config) 'Private state' } | Should -Throw '*Authenticated Users has write access (0x000301BF, inherited, this folder and new children)*'
        $tls = $report.entries | Where-Object role -eq 'TLS'
        ($tls.findings | Where-Object path -like '*cert-password').principal | Should -Be 'Users'
    }
    It 'accepts protected private state and binaries readable by everyone' {
        $script:Broad.Clear()
        $script:Broad[$script:Config.ReleasesRoot] = @(Rule 'S-1-5-11' 0x1200A9 -Children)
        (Get-ALAclReport (Get-ALAclPlan $script:Config)).safe | Should -BeTrue
    }
    It 'reports a missing path without findings and does not count it as unsafe' {
        $script:Broad.Clear()
        Remove-Item -Recurse -Force $script:Config.WorkRoot
        $report = Get-ALAclReport (Get-ALAclPlan $script:Config)
        ($report.entries | Where-Object role -eq 'deployment state').exists | Should -BeFalse
        $report.safe | Should -BeTrue
    }
}

Describe 'Explicit ACL remediation (ProtectAcl and RestoreAcl)' {
    It 'retains complete recovery inventories and records a partial remediation failure' {
        New-AclFixture
        Mock -ModuleName $M Reset-ALAclFile { throw 'Injected native file reset failure' }
        { Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots } | Should -Throw '*Injected native file reset failure*'
        $operation = @(Get-ChildItem $script:AclBackupRoot -Directory)[0].FullName
        $status = Get-ALAclOperationStatus $operation
        $status.phase | Should -Be 'failed'
        $status.incomplete | Should -BeTrue
        $status.application_changes_may_have_started | Should -BeTrue
        $status.manifest_present | Should -BeTrue
        $saved = Get-Content (Join-Path $operation 'acl-backup.json') -Raw | ConvertFrom-Json
        foreach ($entry in $saved.entries) { Test-ALAclBackupFile $entry }
        (Invoke-ALRestoreAcl $operation $script:ApprovedRoots).verified | Should -BeTrue
        Test-Path (Join-Path $operation 'acl-operation.jsonl') | Should -BeTrue
        @(Get-ChildItem $operation -Filter 'acl-restore-*.jsonl').Count | Should -Be 1
    }
    It 'refuses unapproved scope before creating backup files or changing ACLs' {
        New-AclFixture
        { Invoke-ALProtectAcl $script:Config (Join-Path $script:Paths.Other 'acl-backups') @($script:Paths.Other) } | Should -Throw '*outside*approved*'
        $script:CreatedSecure.Count | Should -Be 0
        $script:Icacls.Count | Should -Be 0
    }
    It 'is idempotent after verified protection and rejects a raced exclusive directory' {
        New-AclFixture
        $first = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $script:Icacls.Clear()
        $second = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $second.changed.Count | Should -Be 0
        $second.backup | Should -BeNullOrEmpty
        $script:Icacls.Count | Should -Be 0
        { New-ALSecureDirectory $first.backup $script:ApprovedRoots -Exclusive } | Should -Throw '*never merged*'
    }
    It 'refuses a changed ACL backup before the first restore command' {
        New-AclFixture
        $result = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $record = Get-Content (Join-Path $result.backup 'acl-backup.json') -Raw | ConvertFrom-Json
        Add-Content $record.entries[0].file 'tampered'
        $script:Icacls.Clear()
        { Invoke-ALRestoreAcl $result.backup $script:ApprovedRoots } | Should -Throw '*checksum differs*'
        $script:Icacls.Count | Should -Be 0
    }
    It 'fails closed if secure creation or final access verification fails' {
        New-AclFixture
        Mock -ModuleName $M New-ALDirectoryWithAcl { throw 'synthetic secure create failed' }
        { Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots } | Should -Throw '*secure create failed*'
        $script:Icacls.Count | Should -Be 0
        Mock -ModuleName $M Get-ALAclRules { @() }
        { Assert-ALAclRequiredAccess $script:Config.DataDirectory } | Should -Throw '*SYSTEM/Administrators*'
    }
    It 'rejects backup storage inside a tree whose ACLs it must save' {
        New-AclFixture
        { Invoke-ALProtectAcl $script:Config (Join-Path $script:Config.WorkRoot 'acl-backups') $script:ApprovedRoots } | Should -Throw '*disjoint*'
        $script:CreatedSecure.Count | Should -Be 0
        $script:Icacls.Count | Should -Be 0
    }
    It 'rejects an escaping native restore path even when its file checksum was recomputed' {
        New-AclFixture
        $result = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $recordFile = Join-Path $result.backup 'acl-backup.json'
        $record = Get-Content $recordFile -Raw | ConvertFrom-Json
        $entry = @($record.entries | Where-Object { -not $_.created })[0]
        $lines = [IO.File]::ReadAllLines($entry.file, [Text.Encoding]::Unicode)
        $lines[0] = '..\..\outside'
        [IO.File]::WriteAllLines($entry.file, $lines, [Text.Encoding]::Unicode)
        $entry.sha256 = (Get-FileHash $entry.file).Hash
        $record | ConvertTo-Json -Depth 8 | Set-Content $recordFile
        $script:Icacls.Clear()
        { Invoke-ALRestoreAcl $result.backup $script:ApprovedRoots } | Should -Throw '*restore paths escape*'
        $script:Icacls.Count | Should -Be 0
    }
    It 'removes explicit Domain Users and Domain Guests grants identified by SID pattern' {
        New-AclFixture
        $script:Broad[$script:Config.DataDirectory] = @((Rule 'S-1-5-21-1-2-3-513' $script:Modify), (Rule 'S-1-5-21-1-2-3-514' $script:ReadExecute))
        $null = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $remove = @($script:Icacls | Where-Object { $_ -like "$($script:Config.DataDirectory) /L /remove:g *" })
        $remove.Count | Should -Be 1
        $remove[0] | Should -Match '\*S-1-5-21-1-2-3-513'
        $remove[0] | Should -Match '\*S-1-5-21-1-2-3-514'
    }

    It 'saves every ACL before changing it, protects the installation with least privilege and passes the audit afterwards' {
        New-AclFixture 'NT SERVICE\AuthLens'
        $result = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $result.after.safe | Should -BeTrue
        $calls = @($script:Icacls)
        $script:CreatedSecure | Should -Contain $result.backup # protected at creation, before the first backup file
        $script:ManifestChecked | Should -Be $result.changed.Count
        $calls | Where-Object { $_ -match ' /save ' } | Should -BeNullOrEmpty
        $full = '*S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F'
        $calls | Should -Contain "$($script:Config.DataDirectory) /L /inheritance:r /grant:r $full NT SERVICE\AuthLens:(OI)(CI)M"
        $calls | Should -Contain "$(Split-Path $script:Config.CertificatePath) /L /inheritance:r /grant:r $full NT SERVICE\AuthLens:(OI)(CI)R"
        $calls | Should -Contain "$(Join-Path $script:Paths.Install 'keys') /L /inheritance:r /grant:r $full NT SERVICE\AuthLens:(OI)(CI)R"
        $calls | Should -Contain "$($script:Config.BackupRoot) /L /inheritance:r /grant:r $full"
        $calls | Should -Contain "$($script:Config.ReleasesRoot) /L /inheritance:r /grant:r $full NT SERVICE\AuthLens:(OI)(CI)RX"
        $calls | Should -Contain "native file reset $(Join-Path $script:Config.DataDirectory 'logs/server.log')"
        $calls | Should -Contain "$($script:Config.ReleasesRoot) /L /grant:r *S-1-5-11:(OI)(CI)RX"
        $calls | Where-Object { $_ -like "$($script:Config.ConfigFile) /L /grant:r *S-1-5-11*" } | Should -BeNullOrEmpty   # configuration is not readable by users
        $calls | Where-Object { $_ -like "$($script:Paths.Root) *" } | Should -BeNullOrEmpty                               # nothing above the installation
    }
    It 'gives LocalSystem services no extra grant: SYSTEM already has full control' {
        New-AclFixture 'LocalSystem'
        $null = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $script:Icacls | Where-Object { $_ -like '*NT SERVICE*' -or $_ -like '*LocalSystem*' } | Should -BeNullOrEmpty
    }
    It 'changes nothing when the audit is already safe' {
        New-AclFixture; $script:Broad.Clear()
        $result = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $result.changed.Count | Should -Be 0
        $script:Icacls.Count | Should -Be 0
    }
    It 'refuses to change a system location named in the configuration, before saving or changing anything' {
        New-AclFixture
        $previous = $env:ProgramData
        try {
            $env:ProgramData = Join-Path $script:Paths.Root 'ProgramData'
            New-Item -ItemType Directory $env:ProgramData | Out-Null
            $script:Config.WorkRoot = $env:ProgramData
            { Invoke-ALProtectAcl $script:Config (Join-Path $script:Paths.Other 'acl-backups') $script:ApprovedRoots } | Should -Throw '*system location*'
            $script:Icacls.Count | Should -Be 0
        } finally { $env:ProgramData = $previous }
    }
    It 'restores the saved ACLs newest first' {
        New-AclFixture
        $result = Invoke-ALProtectAcl $script:Config $script:AclBackupRoot $script:ApprovedRoots
        $script:Icacls.Clear()
        $restored = Invoke-ALRestoreAcl $result.backup $script:ApprovedRoots
        $restored.kept_created.Count | Should -Be 0
        $script:Icacls.Count | Should -Be $restored.restored.Count
        $script:Icacls | ForEach-Object { $_ | Should -Match ' /restore .+\.acl /L /C /Q$' }
        $script:Icacls[0] | Should -BeLike "$(Split-Path $restored.restored[0]) /restore *"
        { Invoke-ALRestoreAcl (Join-Path $TestDrive 'not-a-backup') @($TestDrive) } | Should -Throw '*not an ACL backup*'
    }
}

AfterAll { if (Test-Path Function:\global:Get-Acl) { Remove-Item Function:\global:Get-Acl } }
