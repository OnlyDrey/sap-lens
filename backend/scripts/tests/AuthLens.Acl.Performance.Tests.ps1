# All real filesystem and DACL writes are confined to Pester's fresh TestDrive.
BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    Import-TestDeploymentModule
    function New-PerformanceFixture([int]$Files = 10) {
        $root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        [void][IO.Directory]::CreateDirectory($root)
        for ($i = 0; $i -lt $Files; $i++) {
            $directory = Join-Path $root ('d{0:D2}' -f ($i % 10))
            [void][IO.Directory]::CreateDirectory($directory)
            [IO.File]::WriteAllText((Join-Path $directory "$i.txt"), 'synthetic')
        }
        $root
    }
    function Set-ExplicitFixtureFile([string]$Path) {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'Allow'))
        Set-Acl -LiteralPath $Path -AclObject $acl
    }
}

Describe 'Bounded scalable Windows ACL operations' -Skip:([IO.Path]::DirectorySeparatorChar -ne '\') {
    It 'backs up and validates a thousand-file tree with zero native process launches' {
        $root = New-PerformanceFixture 1000
        $snapshot = @(Get-ALAclSnapshot $root)
        $snapshot.Count | Should -Be 1011
        $file = Join-Path $TestDrive 'large.acl'
        Mock -ModuleName AuthLens.Deploy Invoke-ALProcess { throw 'No per-object processes permitted' }
        Save-ALAclInventory $snapshot (Split-Path $root) $file
        $entry = [pscustomobject]@{ path=$root; parent=(Split-Path $root); file=$file; snapshot=$snapshot }
        Test-ALAclBackupFile $entry
        [IO.File]::ReadAllLines($file, [Text.Encoding]::Unicode).Count | Should -Be 2022
        Test-Path "$file.part" | Should -BeFalse
        Should -Invoke -ModuleName AuthLens.Deploy Invoke-ALProcess -Times 0 -Exactly
    }
    It 'retains partial output on a failed read and refuses to overwrite it on retry' {
        $root = New-PerformanceFixture
        $snapshot = @(Get-ALAclSnapshot $root)
        $file = Join-Path $TestDrive 'interrupted.acl'
        $script:Reads = 0
        Mock -ModuleName AuthLens.Deploy Get-Acl {
            param($LiteralPath)
            if (++$script:Reads -eq 5) { throw 'Injected ACL read failure' }
            Microsoft.PowerShell.Security\Get-Acl -LiteralPath $LiteralPath
        }
        { Save-ALAclInventory $snapshot (Split-Path $root) $file } | Should -Throw '*Injected ACL read failure*'
        Test-Path $file | Should -BeFalse
        Test-Path "$file.part" | Should -BeTrue
        $before = (Get-FileHash "$file.part").Hash
        { Save-ALAclInventory $snapshot (Split-Path $root) $file } | Should -Throw
        (Get-FileHash "$file.part").Hash | Should -Be $before
    }
    It 'refuses an existing completed recovery file without changing its bytes' {
        $root = New-PerformanceFixture 1
        $snapshot = @(Get-ALAclSnapshot $root)
        $file = Join-Path $TestDrive 'existing.acl'
        [IO.File]::WriteAllText($file, 'retained evidence')
        { Save-ALAclInventory $snapshot (Split-Path $root) $file } | Should -Throw '*already exists*'
        [IO.File]::ReadAllText($file) | Should -Be 'retained evidence'
    }
    It 'preserves the complete relative path when the saved parent is a drive root' {
        $root = New-PerformanceFixture 1
        $snapshot = @(Get-ALAclSnapshot $root)
        $drive = [IO.Path]::GetPathRoot($root)
        $file = Join-Path $TestDrive 'drive-parent.acl'
        Save-ALAclInventory $snapshot $drive $file
        [IO.File]::ReadAllLines($file, [Text.Encoding]::Unicode)[0] | Should -Be $root.Substring($drive.Length)
        Test-ALAclBackupFile ([pscustomobject]@{path=$root; parent=$drive; file=$file; snapshot=$snapshot})
        # Only the parent-path arithmetic uses the drive root; all files remain under TestDrive.
    }
    It 'refuses a DACL that changed after inventory before publishing the backup' {
        $root = New-PerformanceFixture 1
        $snapshot = @(Get-ALAclSnapshot $root)
        $leaf = @($snapshot | Where-Object path -like '*.txt')[0].path
        Set-ExplicitFixtureFile $leaf
        $file = Join-Path $TestDrive 'changed.acl'
        { Save-ALAclInventory $snapshot (Split-Path $root) $file } | Should -Throw '*differs from its inventory*'
        Test-Path $file | Should -BeFalse
        Test-Path "$file.part" | Should -BeTrue
    }
    It 'matches icacls file reset ACEs and inheritance under a protected parent and is idempotent' {
        $root = New-PerformanceFixture 2
        $parent = [Security.AccessControl.DirectorySecurity]::new()
        $parent.SetAccessRuleProtection($true, $false)
        $parent.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow'))
        $parent.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-11'), 'ReadAndExecute', 'ContainerInherit, ObjectInherit', 'None', 'Allow'))
        $directory = Join-Path $root 'd00'
        Set-Acl -LiteralPath $directory -AclObject $parent
        $a = Join-Path $directory '0.txt'; $b = Join-Path $directory 'comparison.txt'
        [IO.File]::WriteAllText($b, 'synthetic')
        Set-ExplicitFixtureFile $a; Set-ExplicitFixtureFile $b
        $parentBefore = (Get-Acl $directory).Sddl
        Reset-ALAclFile $a
        Invoke-ALIcacls @($b, '/reset', '/L', '/C', '/Q')
        $expected = (Get-Acl $b).GetSecurityDescriptorSddlForm('Access')
        $actual = (Get-Acl $a).GetSecurityDescriptorSddlForm('Access')
        $actual | Should -Be $expected
        (Get-Acl $a).AreAccessRulesProtected | Should -BeFalse
        Reset-ALAclFile $a
        (Get-Acl $a).GetSecurityDescriptorSddlForm('Access') | Should -Be $actual
        (Get-Acl $directory).Sddl | Should -Be $parentBefore
        { Reset-ALAclFile $directory } | Should -Throw
        (Get-Acl $directory).Sddl | Should -Be $parentBefore
    }
    It 'rejects a junction introduced between inventory and save without touching its target' {
        $root = New-PerformanceFixture 1
        $snapshot = @(Get-ALAclSnapshot $root)
        $child = Join-Path $root 'd00'
        $physical = Join-Path $root 'physical'
        [IO.Directory]::Move($child, $physical)
        $before = (Get-Acl $physical).Sddl
        $link = New-Item -ItemType Junction -Path $child -Target $physical
        try {
            { Save-ALAclInventory $snapshot (Split-Path $root) (Join-Path $TestDrive 'raced.acl') } | Should -Throw '*reparse points*'
            { Reset-ALAclFile (Join-Path $child '0.txt') } | Should -Throw '*reparse points*'
            (Get-Acl $physical).Sddl | Should -Be $before
        } finally { $link.Delete() } # only the synthetic link object, never recursive
    }
    It 'recognizes incomplete, complete, truncated and legacy operation evidence read-only' {
        $root = New-PerformanceFixture 0
        $journal = Join-Path $root 'acl-operation.jsonl'
        (Get-ALAclOperationStatus $root).phase | Should -Be 'legacy_unknown'
        (Get-ALAclOperationStatus $root).application_changes_may_have_started | Should -BeTrue
        [IO.File]::WriteAllText($journal, "{`"phase`":`"backup`",`"mutation_started`":false}`n")
        $status = Get-ALAclOperationStatus $root
        $status.incomplete | Should -BeTrue
        $status.application_changes_may_have_started | Should -BeFalse
        [IO.File]::AppendAllText($journal, "{`"phase`":`"remediation`",`"mutation_started`":true}`n{`"phase`":")
        $status = Get-ALAclOperationStatus $root
        $status.last_record_truncated | Should -BeTrue
        $status.application_changes_may_have_started | Should -BeTrue
        $status.phase | Should -Be 'remediation'
        [IO.File]::WriteAllText($journal, "{`"phase`":`"complete`",`"mutation_started`":true}`n")
        (Get-ALAclOperationStatus $root).incomplete | Should -BeFalse
    }
    It 'rejects a corrupt earlier checkpoint rather than trusting a later complete event' {
        $root = New-PerformanceFixture 0
        [IO.File]::WriteAllText((Join-Path $root 'acl-operation.jsonl'), "broken`n{`"phase`":`"complete`",`"mutation_started`":true}`n")
        { Get-ALAclOperationStatus $root } | Should -Throw '*corrupt*'
    }
    It 'retains Unicode paths through UTF-16 backup and UTF-8 manifest restore validation' {
        $root = New-PerformanceFixture 0
        $unicode = Join-Path $root ('release-' + [char]0x017B)
        [void][IO.Directory]::CreateDirectory($unicode)
        [IO.File]::WriteAllText((Join-Path $unicode ([string][char]0x6D4B + '.txt')), 'synthetic')
        $snapshot = @(Get-ALAclSnapshot $root)
        $backup = Join-Path $TestDrive 'unicode-recovery'
        [void][IO.Directory]::CreateDirectory($backup)
        $file = Join-Path $backup '01.acl'
        Save-ALAclInventory $snapshot (Split-Path $root) $file
        $entry = [pscustomobject]@{ path=$root; parent=(Split-Path $root); file=$file; snapshot=$snapshot
            sha256=(Get-FileHash $file).Hash; created=$false; releases_root=''; junction=$null }
        [IO.File]::WriteAllText((Join-Path $backup 'acl-backup.json'), (@{schema=2;entries=@($entry)} | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        Mock -ModuleName AuthLens.Deploy Get-ALAclRules {
            foreach ($sid in 'S-1-5-18', 'S-1-5-32-544') {
                [pscustomobject]@{ Sid=$sid; Rights=0x1F01FF; Allow=$true; Inherited=$false; InheritOnly=$false; ContainerInherit=$true; ObjectInherit=$true }
            }
        }
        Mock -ModuleName AuthLens.Deploy Invoke-ALProcess { @{ ExitCode=0; Output=@() } }
        (Invoke-ALRestoreAcl $backup @($TestDrive)).verified | Should -BeTrue
        Should -Invoke -ModuleName AuthLens.Deploy Invoke-ALProcess -Times 1 -Exactly
        # This exercises encoding/path validation; actual privileged restore remains a separate native acceptance test.
    }
}
