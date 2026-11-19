# NTFS policy for SAP Lens private state (SapLens.Acl.ps1): the pure rule evaluation by well-known SID, the audit plan, preflight refusals, and the
# explicit ProtectAcl/RestoreAcl remediation with synthetic folders. ACL reads and icacls are replaced; no real ACL or service is touched.
BeforeAll {
    Import-Module (Join-Path $PSScriptRoot '../deploy/SapLens.Deploy.psm1') -Force
    $script:M = 'SapLens.Deploy'
    # FileSystemRights as Windows reports them: Modify, ReadAndExecute, FullControl, and the ProgramData "Users may create" pattern (WD, AD, WEA, WA).
    $script:Modify = 0x301BF; $script:ReadExecute = 0x1200A9; $script:Full = 0x1F01FF; $script:CreateOnly = 278
    function Rule([string]$Sid, [int64]$Rights, [switch]$Inherited, [switch]$Children, [switch]$InheritOnly, [switch]$Deny) {
        [pscustomobject]@{ Sid = $Sid; Rights = $Rights; Allow = -not $Deny; Inherited = [bool]$Inherited; ContainerInherit = [bool]$Children; ObjectInherit = [bool]$Children; InheritOnly = [bool]$InheritOnly }
    }
    $script:Safe = @((Rule 'S-1-5-18' $script:Full -Children), (Rule 'S-1-5-32-544' $script:Full -Children))
    function New-AclFixture([string]$Account = 'LocalSystem') {
        $root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $old = Join-Path $root 'saplens2'; $new = Join-Path $root 'sap-lens'; $programData = Join-Path $root 'ProgramData'
        foreach ($name in 'data/logs', 'tls', 'backup', 'predeploy-backups', 'deploy', 'releases/r1/server') { New-Item -ItemType Directory -Force (Join-Path $old $name) | Out-Null }
        New-Item -ItemType Directory -Force $new, $programData | Out-Null
        foreach ($name in 'tls/server.pfx', 'tls/password', 'data/sap-lens-v2.sqlite3', 'data/logs/server.log') { Set-Content (Join-Path $old $name) 'synthetic' }
        Set-Content (Join-Path $old 'backup/host.key') ([Convert]::ToBase64String([byte[]](1..32)))
        @{ schema = 1; path = (Join-Path $old 'backup/host.key') } | ConvertTo-Json | Set-Content (Join-Path $old 'data/backup-key-location.json')
        Set-Content (Join-Path $old 'deploy.local.json') '{}'
        $script:Source = [pscustomobject]@{ ServiceName = 'SapLens2'; ServiceAccount = $Account; ConfigFile = (Join-Path $old 'deploy.local.json')
            WorkRoot = (Join-Path $old 'deploy'); ReleasesRoot = (Join-Path $old 'releases'); BackupRoot = (Join-Path $old 'predeploy-backups'); DataDirectory = (Join-Path $old 'data')
            CertificatePath = (Join-Path $old 'tls/server.pfx'); CertificatePasswordFile = (Join-Path $old 'tls/password') }
        $script:Target = [pscustomobject]@{ ServiceName = 'SapLens'; ServiceAccount = $Account; ConfigFile = (Join-Path $root 'private/target.local.json')
            WorkRoot = (Join-Path $new 'deploy'); ReleasesRoot = (Join-Path $new 'releases'); BackupRoot = (Join-Path $programData 'SapLens/predeploy-backups')
            DataDirectory = (Join-Path $programData 'SapLens/data'); CertificatePath = (Join-Path $programData 'SapLens/tls/server.pfx'); CertificatePasswordFile = (Join-Path $programData 'SapLens/tls/password') }
        New-Item -ItemType Directory -Force (Split-Path $script:Target.ConfigFile) | Out-Null; Set-Content $script:Target.ConfigFile '{}'
        $script:Paths = @{ Old = $old; New = $new; ProgramData = $programData }
        # The VM as reported: Authenticated Users Modify inherited across C:\saplens2 and C:\sap-lens, ProgramData letting users create folders.
        $script:Broad = @{}
        $script:Broad[$old] = @(Rule 'S-1-5-11' $script:Modify -Children)
        foreach ($path in Get-ChildItem $old -Recurse -Force | ForEach-Object FullName) { $script:Broad[$path] = @(Rule 'S-1-5-11' $script:Modify -Children -Inherited) }
        $script:Broad[$new] = @(Rule 'S-1-5-11' $script:Modify -Children)
        $script:Broad[$programData] = @((Rule 'S-1-5-32-545' $script:ReadExecute -Children -Inherited), (Rule 'S-1-5-32-545' $script:CreateOnly -Children -InheritOnly -Inherited))
        $script:Protected = [Collections.Generic.HashSet[string]]::new()
        $script:Icacls = [Collections.Generic.List[string]]::new()
        Mock -ModuleName $M Get-SL2AclRules {
            param($Path)
            $full = [IO.Path]::GetFullPath($Path).TrimEnd('/')
            if ($script:Protected.Contains($full)) { return $script:Safe }
            foreach ($protected in $script:Protected) { if ($full.StartsWith($protected + '/')) { return $script:Safe } }
            if ($script:Broad.ContainsKey($full)) { $script:Safe + $script:Broad[$full] } else { $script:Safe }
        }
        Mock -ModuleName $M Invoke-SL2Process {
            param($File, $Arguments)
            $script:Icacls.Add(($Arguments -join ' '))
            if ($Arguments -contains '/inheritance:r') { [void]$script:Protected.Add([IO.Path]::GetFullPath($Arguments[0]).TrimEnd('/')) }
            if ($Arguments -contains '/save') { Set-Content -LiteralPath $Arguments[2] 'saved ACL' }
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
        $finding = @(Get-SL2AclFindings @(& $Rule) $Class $true)
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
        @(Get-SL2AclFindings @(& $Rule) $Class $Container).Count | Should -Be 0
    }
}

Describe 'ACL audit plan and preflight refusals' {
    BeforeEach { New-AclFixture }
    It 'classifies source private state, releases, configuration and installation folder' {
        $plan = @(Get-SL2AclPlan $script:Source $null)
        ($plan | Where-Object Class -eq 'private' | ForEach-Object Role) | Should -Be @('source data', 'source pre-deployment backups', 'source TLS', 'source backup key', 'source deployment state')
        ($plan | Where-Object Class -eq 'binaries' | ForEach-Object Role) | Should -Be @('source releases', 'source configuration', 'source installation folder')
    }
    It 'judges a missing target parent by its nearest existing ancestor and keeps the strictest class for a shared parent' {
        $parents = @(Get-SL2AclPlan $null $script:Target | Where-Object Role -eq 'target parent')
        $programParent = $parents | Where-Object Path -eq (Join-Path $script:Paths.ProgramData 'SapLens')
        ($programParent.Class, $programParent.Existing) | Should -Be @('private', $script:Paths.ProgramData)
        ($parents | Where-Object Path -eq $script:Paths.New).Class | Should -Be 'private'                 # releases and deployment state share C:\sap-lens
    }
    It 'refuses the reported VM state, naming path, principal and right, and finds explicit broad grants on descendants' {
        $script:Broad[(Join-Path $script:Paths.Old 'tls/password')] = @(Rule 'S-1-5-32-545' 0x1200A9)
        $report = Get-SL2AclReport (Get-SL2AclPlan $script:Source $script:Target)
        $report.safe | Should -BeFalse
        { Assert-SL2AclPlan (Get-SL2AclPlan $script:Source $null) 'Private source state' } | Should -Throw '*Authenticated Users has write access (0x000301BF, inherited, this folder and new children)*'
        $tls = $report.entries | Where-Object role -eq 'source TLS'
        ($tls.findings | Where-Object path -like '*password').principal | Should -Be 'Users'
        # ProgramData itself: users read everything new folders inherit, and may create folders (inherit-only). Both block a private target.
        $programData = @(($report.entries | Where-Object path -eq (Join-Path $script:Paths.ProgramData 'SapLens')).findings | ForEach-Object { "$($_.access)/$($_.applies)" })
        $programData | Should -Be @('read/this folder and new children', 'write/new children only')
    }
    It 'accepts protected private state and binaries readable by everyone' {
        $script:Broad.Clear()
        $script:Broad[$script:Source.ReleasesRoot] = @(Rule 'S-1-5-11' 0x1200A9 -Children)
        New-Item -ItemType Directory (Join-Path $script:Paths.ProgramData 'SapLens') | Out-Null
        (Get-SL2AclReport (Get-SL2AclPlan $script:Source $script:Target)).safe | Should -BeTrue
    }
}

Describe 'Explicit ACL remediation (ProtectAcl and RestoreAcl)' {
    It 'saves every ACL before changing it, protects source and target, creates the missing target parent and passes the audit afterwards' {
        New-AclFixture 'NT SERVICE\SapLens2'
        $backupRoot = Join-Path $script:Source.WorkRoot 'acl-backups'
        $result = Invoke-SL2ProtectAcl $script:Source $script:Target $backupRoot
        $result.after.safe | Should -BeTrue
        $result.created | Should -Be @((Join-Path $script:Paths.ProgramData 'SapLens'))
        Test-Path (Join-Path $script:Paths.ProgramData 'SapLens') | Should -BeTrue
        $calls = @($script:Icacls)
        $calls[0] | Should -BeLike "$($result.backup) /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F"   # the backup is private first
        foreach ($path in $result.changed | Where-Object { $_ -notin $result.created }) {
            $save = [Array]::FindIndex([string[]]$calls, [Predicate[string]] { param($c) $c -like "$path /save *" })
            $change = [Array]::FindIndex([string[]]$calls, [Predicate[string]] { param($c) $c -like "$path /inheritance:r*" })
            ($save -ge 0 -and $change -gt $save) | Should -BeTrue -Because "$path must be saved before it changes"
        }
        $calls | Should -Contain "$($script:Source.DataDirectory) /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F NT SERVICE\SapLens2:(OI)(CI)M"
        $calls | Should -Contain "$(Join-Path $script:Source.DataDirectory '*') /reset /T /C /Q"
        $calls | Should -Contain "$($script:Source.ReleasesRoot) /grant:r *S-1-5-11:(OI)(CI)RX"
        $calls | Where-Object { $_ -like "$($script:Paths.ProgramData) *" } | Should -BeNullOrEmpty            # ProgramData itself is never changed
        $record = Get-Content (Join-Path $result.backup 'acl-backup.json') -Raw | ConvertFrom-Json
        ($record.entries | Where-Object created).path | Should -Be (Join-Path $script:Paths.ProgramData 'SapLens')
    }
    It 'gives LocalSystem services no extra grant: SYSTEM already has full control' {
        New-AclFixture 'LocalSystem'
        $null = Invoke-SL2ProtectAcl $script:Source $null (Join-Path $script:Source.WorkRoot 'acl-backups')
        $script:Icacls | Where-Object { $_ -like '*NT SERVICE*' -or $_ -like '*LocalSystem*' } | Should -BeNullOrEmpty
    }
    It 'changes nothing when the audit is already safe' {
        New-AclFixture; $script:Broad.Clear()
        $result = Invoke-SL2ProtectAcl $script:Source $null (Join-Path $script:Source.WorkRoot 'acl-backups')
        $result.changed.Count | Should -Be 0
        $script:Icacls.Count | Should -Be 0
    }
    It 'refuses to change a system location named as a target parent, before saving or changing anything' {
        New-AclFixture
        $previous = $env:ProgramData
        try {
            $env:ProgramData = $script:Paths.ProgramData
            $script:Target.DataDirectory = Join-Path $script:Paths.ProgramData 'data'
            { Invoke-SL2ProtectAcl $null $script:Target (Join-Path $script:Paths.New 'acl-backups') } | Should -Throw '*system location*'
            $script:Icacls.Count | Should -Be 0
        } finally { $env:ProgramData = $previous }
    }
    It 'restores the saved ACLs newest first and keeps the folders it created' {
        New-AclFixture
        $result = Invoke-SL2ProtectAcl $script:Source $script:Target (Join-Path $script:Source.WorkRoot 'acl-backups')
        $script:Icacls.Clear()
        $restored = Invoke-SL2RestoreAcl $result.backup
        $restored.kept_created | Should -Be @((Join-Path $script:Paths.ProgramData 'SapLens'))
        $script:Icacls.Count | Should -Be $restored.restored.Count
        $script:Icacls | ForEach-Object { $_ | Should -Match ' /restore .+\.acl /C /Q$' }
        $script:Icacls[0] | Should -BeLike "$(Split-Path $restored.restored[0]) /restore *"
        { Invoke-SL2RestoreAcl (Join-Path $TestDrive 'not-a-backup') } | Should -Throw '*not an ACL backup*'
    }
}
