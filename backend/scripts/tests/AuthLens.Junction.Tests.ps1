# Native junctions are disposable TestDrive fixtures. SCM is never queried; ACL mutations and copying are mocked.
BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    Import-TestDeploymentModule
    $script:M = 'AuthLens.Deploy'
    $script:NativeProcess = (Get-Command Invoke-ALProcess).ScriptBlock
    function New-FixtureJunction([string]$Path, [string]$Target) {
        New-Item -ItemType Junction -Path $Path -Target $Target -ErrorAction Stop | Out-Null
        $script:Links.Add($Path)
    }
    function New-FixtureRelease([string]$Name) {
        $path = Join-Path $script:Releases $Name
        New-Item -ItemType Directory (Join-Path $path 'server') -Force | Out-Null
        Set-Content (Join-Path $path 'build-manifest.json') '{"synthetic":true}'
        Set-Content (Join-Path $path 'server/AuthLens.Api.exe') 'synthetic'
        $path
    }
}

Describe 'Bounded source releases/current junction' -Skip:([IO.Path]::DirectorySeparatorChar -ne '\') {
    BeforeEach {
        $script:Links = [Collections.Generic.List[string]]::new()
        $script:Root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:Install = Join-Path $script:Root 'source'
        $script:Releases = Join-Path $script:Install 'releases'
        $script:Backup = Join-Path $script:Root 'acl-backups'
        $script:Approved = @($script:Root)
        foreach ($name in 'data', 'backups', 'tls', 'work', 'releases') { New-Item -ItemType Directory (Join-Path $script:Install $name) -Force | Out-Null }
        Set-Content (Join-Path $script:Install 'deploy.local.json') '{}'
        $script:Release = New-FixtureRelease 'AuthLens-2.0.0-alpha.1-synthetic-win-x64'
        $script:Current = Join-Path $script:Releases 'current'
        New-FixtureJunction $script:Current $script:Release
        $script:Config = [pscustomobject]@{ ConfigFile = (Join-Path $script:Install 'deploy.local.json'); ServiceAccount = 'LocalSystem'
            DataDirectory = (Join-Path $script:Install 'data'); BackupRoot = (Join-Path $script:Install 'backups'); WorkRoot = (Join-Path $script:Install 'work')
            ReleasesRoot = $script:Releases; CertificatePath = (Join-Path $script:Install 'tls/server.pfx') }
        $script:Protected = [Collections.Generic.HashSet[string]]::new()
        $script:Calls = [Collections.Generic.List[string]]::new()
        Mock -ModuleName $M Get-ALService { throw 'No host services may be queried' }
        Mock -ModuleName $M Get-ALAclRules {
            param($Path)
            foreach ($sid in 'S-1-5-18', 'S-1-5-32-544') {
                [pscustomobject]@{ Sid=$sid; Rights=0x1F01FF; Allow=$true; Inherited=$false; InheritOnly=$false; ContainerInherit=$true; ObjectInherit=$true }
            }
            if ($Path -eq $script:Install -and -not $script:Protected.Contains($Path)) {
                [pscustomobject]@{ Sid='S-1-5-11'; Rights=0x301BF; Allow=$true; Inherited=$false; InheritOnly=$false; ContainerInherit=$true; ObjectInherit=$true }
            }
        }
        Mock -ModuleName $M New-ALDirectoryWithAcl { param($Path) New-Item -ItemType Directory $Path -ErrorAction Stop | Out-Null }
        Mock -ModuleName $M Invoke-ALProcess {
            param($File, $Arguments)
            $script:Calls.Add(($Arguments -join ' '))
            if ($Arguments -contains '/inheritance:r') { [void]$script:Protected.Add($Arguments[0]) }
            if ($Arguments -contains '/save') {
                $lines = @((Split-Path $Arguments[0] -Leaf), (Get-Acl -LiteralPath $Arguments[0]).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access))
                [IO.File]::WriteAllLines($Arguments[2], [string[]]$lines, [Text.Encoding]::Unicode)
            }
            @{ ExitCode = 0; Output = @() }
        }
    }
    AfterEach {
        # Delete only fixture junction objects, without recursive traversal, before Pester cleans TestDrive.
        foreach ($path in @($script:Links)) {
            $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $item.Delete() }
        }
    }
    It 'allows only the configured current junction and inventories physical release files once' {
        $link = Get-ALReleaseJunction $script:Releases $script:Approved
        $link.path | Should -Be $script:Current
        $link.target | Should -Be $script:Release
        $snapshot = @(Get-ALAclSnapshot $script:Install $script:Releases)
        @($snapshot | Where-Object { Test-ALPathWithin $_.path $script:Current }).Count | Should -Be 0
        @($snapshot | Where-Object path -eq (Join-Path $script:Release 'server/AuthLens.Api.exe')).Count | Should -Be 1
        { Get-ALAclSnapshot $script:Install } | Should -Throw '*Unexpected reparse point*'
    }
    It 'rejects an external target' {
        $outside = Join-Path $script:Root 'outside'
        New-Item -ItemType Directory $outside | Out-Null
        (Get-Item -LiteralPath $script:Current).Delete()
        New-FixtureJunction $script:Current $outside
        { Get-ALReleaseJunction $script:Releases } | Should -Throw '*inside the configured releases root*'
    }
    It 'rejects a missing target' {
        (Get-Item -LiteralPath $script:Current).Delete()
        $missing = Join-Path $script:Releases 'missing'
        New-Item -ItemType Directory $missing | Out-Null
        New-FixtureJunction $script:Current $missing
        [IO.Directory]::Delete($missing) # empty fixture directory only, leaving a dangling junction
        { Get-ALReleaseJunction $script:Releases } | Should -Throw '*missing*release directory*'
    }
    It 'rejects a junction loop' {
        (Get-Item -LiteralPath $script:Current).Delete()
        New-FixtureJunction $script:Current $script:Releases
        { Get-ALReleaseJunction $script:Releases } | Should -Throw '*direct physical release*'
    }
    It 'rejects a nested junction in the physical release' {
        New-FixtureJunction (Join-Path $script:Release 'nested') (Join-Path $script:Install 'data')
        { Get-ALReleaseJunction $script:Releases } | Should -Throw '*must not contain reparse points*'
    }
    It 'rejects a target that is itself a junction to another tree' {
        $alias = Join-Path $script:Releases 'alias'
        New-FixtureJunction $alias (Join-Path $script:Install 'data')
        (Get-Item -LiteralPath $script:Current).Delete()
        New-FixtureJunction $script:Current $alias
        { Get-ALReleaseJunction $script:Releases } | Should -Throw '*paths must not traverse reparse points*'
    }
    It 'rejects links outside the exact configured current path' {
        $wrong = Join-Path $script:Install 'current'
        New-FixtureJunction $wrong $script:Release
        { Get-ALAclSnapshot $script:Install $script:Releases } | Should -Throw '*Unexpected reparse point*'
        (Get-Item -LiteralPath $wrong).Delete()
        (Get-Item -LiteralPath $script:Current).Delete()
        New-FixtureJunction (Join-Path $script:Releases 'CURRENT') $script:Release
        { Get-ALAclSnapshot $script:Install $script:Releases } | Should -Throw '*Unexpected reparse point*'
    }
    It 'rejects an unexpected sibling link before saving or modifying ACLs' {
        New-FixtureJunction (Join-Path $script:Releases 'other') $script:Release
        { Invoke-ALProtectAcl $script:Config $script:Backup $script:Approved } | Should -Throw '*Unexpected reparse point*'
        $script:Calls.Count | Should -Be 0
        Test-Path $script:Backup | Should -BeFalse
    }
    It 'rejects symbolic links even at the expected path' {
        $fake = [pscustomobject]@{ Attributes=[IO.FileAttributes]::ReparsePoint; LinkType='SymbolicLink'; Target=@($script:Release) }
        Mock -ModuleName $M Get-Item { $fake } -ParameterFilter { $LiteralPath -eq $script:Current }
        { Get-ALReleaseJunction $script:Releases } | Should -Throw '*must be a directory junction*'
    }
    It 'cannot substitute a junction for approved physical roots' {
        { Get-ALReleaseJunction $script:Releases @((Join-Path $script:Install 'work')) } | Should -Throw '*outside*approved*'
        { Assert-ALAclApproved $script:Release @($script:Current) } | Should -Throw '*reparse points*'
        { Get-ALReleaseJunction $script:Releases @($script:Root.ToUpperInvariant()) } | Should -Throw '*exact spelling*'
    }
    It 'backs up and restores physical paths without recursive flags or current-path records' {
        $result = Invoke-ALProtectAcl $script:Config $script:Backup $script:Approved
        $result.after.safe | Should -BeTrue
        $script:Calls | Where-Object { $_ -match ' /T( |$)' -or $_.Contains($script:Current) -or $_ -match '\*' -and $_ -notmatch 'S-1-' } | Should -BeNullOrEmpty
        $record = Get-Content (Join-Path $result.backup 'acl-backup.json') -Raw | ConvertFrom-Json
        @($record.entries[0].snapshot | Where-Object { Test-ALPathWithin $_.path $script:Current }).Count | Should -Be 0
        $record.entries[0].junction.target | Should -Be $script:Release
        (Invoke-ALRestoreAcl $result.backup $script:Approved).verified | Should -BeTrue
        (Get-ALReleaseJunction $script:Releases).target | Should -Be $script:Release
    }
    It 'refuses restoration after the current binding changes' {
        $result = Invoke-ALProtectAcl $script:Config $script:Backup $script:Approved
        $other = New-FixtureRelease 'another-release'
        (Get-Item -LiteralPath $script:Current).Delete()
        New-FixtureJunction $script:Current $other
        $script:Calls.Clear()
        { Invoke-ALRestoreAcl $result.backup $script:Approved } | Should -Throw '*binding changed*'
        $script:Calls.Count | Should -Be 0
    }
    It 'rejects restore records that name paths through current' {
        $result = Invoke-ALProtectAcl $script:Config $script:Backup $script:Approved
        $file = Join-Path $result.backup 'acl-backup.json'
        $saved = Get-Content $file -Raw | ConvertFrom-Json
        $saved.entries[0].snapshot[0].path = Join-Path $script:Current 'server/AuthLens.Api.exe'
        $saved | ConvertTo-Json -Depth 10 | Set-Content $file
        $script:Calls.Clear()
        { Invoke-ALRestoreAcl $result.backup $script:Approved } | Should -Throw '*paths must not traverse reparse points*'
        $script:Calls.Count | Should -Be 0
    }
    It 'saves a real native ACL inventory without following current' {
        Mock -ModuleName $M Invoke-ALProcess {
            param($File, $Arguments, $LogFile)
            & $script:NativeProcess $File $Arguments $LogFile
        }
        $snapshot = @(Get-ALAclSnapshot $script:Install $script:Releases)
        $file = Join-Path $script:Root 'native.acl'
        Save-ALAclInventory $snapshot (Split-Path $script:Install) $file
        $entry = [pscustomobject]@{ file=$file; parent=(Split-Path $script:Install); path=$script:Install; snapshot=$snapshot }
        { Test-ALAclBackupFile $entry } | Should -Not -Throw
        [IO.File]::ReadAllText($file, [Text.Encoding]::Unicode) | Should -Not -Match 'releases\\current'
        (Get-ALReleaseJunction $script:Releases).target | Should -Be $script:Release
    }
    It 'round-trips native ACL restoration around an unchanged junction with an elevated token' {
        $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            Set-ItResult -Skipped -Because 'Native icacls /restore around the fixture junction requires an elevated Windows token.'
            return
        }
        Mock -ModuleName $M Invoke-ALProcess {
            param($File, $Arguments, $LogFile)
            & $script:NativeProcess $File $Arguments $LogFile
        }
        $snapshot = @(Get-ALAclSnapshot $script:Install $script:Releases)
        New-Item -ItemType Directory $script:Backup | Out-Null
        $file = Join-Path $script:Backup 'native.acl'
        Save-ALAclInventory $snapshot (Split-Path $script:Install) $file
        $entry = [pscustomobject]@{ file=$file; parent=(Split-Path $script:Install); path=$script:Install; snapshot=$snapshot
            sha256=(Get-FileHash $file).Hash; created=$false; releases_root=$script:Releases; junction=(Get-ALReleaseJunction $script:Releases) }
        @{ schema=2; entries=@($entry) } | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $script:Backup 'acl-backup.json')
        $leaf = Join-Path $script:Release 'server/AuthLens.Api.exe'
        $acl = [Security.AccessControl.FileSecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'Allow'))
        try {
            Set-Acl -LiteralPath $leaf -AclObject $acl
        } finally { $restored = Invoke-ALRestoreAcl $script:Backup $script:Approved }
        $restored.verified | Should -BeTrue
        (Get-ALReleaseJunction $script:Releases).target | Should -Be $script:Release
        Get-Content -LiteralPath $leaf | Should -Be 'synthetic'
    }
}
