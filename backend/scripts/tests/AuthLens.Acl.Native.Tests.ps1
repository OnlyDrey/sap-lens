# Windows-native DACL and icacls checks. All paths are fresh TestDrive fixtures, never installation paths.
BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    Import-TestDeploymentModule
    function Set-FixtureAcl([string]$Path, [switch]$Broad, [switch]$InheritOnly) {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in $acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier])) { [void]$acl.RemoveAccessRuleSpecific($rule) }
        $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        $none = [Security.AccessControl.PropagationFlags]::None
        $allow = [Security.AccessControl.AccessControlType]::Allow
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner, 'FullControl', $inherit, $none, $allow))
        if ($Broad) {
            $propagation = if ($InheritOnly) { [Security.AccessControl.PropagationFlags]::InheritOnly } else { $none }
            $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-11'), 'Modify', $inherit, $propagation, $allow))
        }
        Set-Acl -LiteralPath $Path -AclObject $acl
    }
}

Describe 'Windows-native NTFS audit and backup restoration' -Skip:([IO.Path]::DirectorySeparatorChar -ne '\') {
    It 'creates a protected DACL atomically and refuses to overwrite a raced path' {
        $parent = Join-Path $TestDrive 'atomic parent'
        New-Item -ItemType Directory $parent | Out-Null
        $parentAcl = [Security.AccessControl.DirectorySecurity]::new()
        $parentAcl.SetAccessRuleProtection($true, $false)
        $parentAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow'))
        $everyone = [Security.Principal.SecurityIdentifier]::new('S-1-1-0')
        $parentAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($everyone, 'ReadAndExecute', 'ContainerInherit, ObjectInherit', 'None', 'Allow'))
        $parentAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($everyone, 278, 'ContainerInherit, ObjectInherit', 'InheritOnly', 'Allow'))
        Set-Acl -LiteralPath $parent -AclObject $parentAcl
        $parentBefore = (Get-Acl -LiteralPath $parent).Sddl
        $security = [Security.AccessControl.DirectorySecurity]::new()
        $security.SetAccessRuleProtection($true, $false)
        $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow'))
        $path = Join-Path $parent 'private child'
        New-ALDirectoryWithAcl $path $security
        (Get-Acl -LiteralPath $path).AreAccessRulesProtected | Should -BeTrue
        (Get-ALAclAudit $path 'private' 'native fixture').findings.Count | Should -Be 0
        Set-Content (Join-Path $path 'synthetic.txt') 'retained'
        { New-ALDirectoryWithAcl $path $security } | Should -Throw '*error 183*'
        Get-Content (Join-Path $path 'synthetic.txt') | Should -Be 'retained'
        (Get-Acl -LiteralPath $parent).Sddl | Should -Be $parentBefore
    }
    It 'reads inherited broad grants by SID from a real NTFS DACL' {
        $root = Join-Path $TestDrive 'native audit'
        New-Item -ItemType Directory $root | Out-Null
        Set-FixtureAcl $root -Broad
        $child = New-Item -ItemType Directory (Join-Path $root 'child')
        $audit = Get-ALAclAudit $child.FullName 'private' 'fixture'
        $finding = @($audit.findings | Where-Object sid -eq 'S-1-5-11')
        $finding.Count | Should -Be 1
        $finding[0].inherited | Should -BeTrue
        $finding[0].access | Should -Be 'write'
        $finding[0].applies | Should -Be 'this folder and new children'
    }

    It 'reports inherit-only rights on a real parent before children receive them' {
        $root = Join-Path $TestDrive 'inherit only'
        New-Item -ItemType Directory $root | Out-Null
        Set-FixtureAcl $root -Broad -InheritOnly
        $finding = @((Get-ALAclAudit $root 'private' 'fixture').findings | Where-Object sid -eq 'S-1-5-11')
        $finding.Count | Should -Be 1
        $finding[0].applies | Should -Be 'new children only'
        $finding[0].inherited | Should -BeFalse
    }

    It 'saves a real root DACL with icacls without changing it' {
        $root = Join-Path $TestDrive 'save with spaces'
        New-Item -ItemType Directory $root | Out-Null
        Set-FixtureAcl $root -Broad
        $before = (Get-Acl -LiteralPath $root).Sddl
        $backup = Join-Path $TestDrive 'saved.acl'
        Invoke-ALIcacls @($root, '/save', $backup, '/T', '/Q')
        [IO.File]::ReadAllText($backup, [Text.Encoding]::Unicode) | Should -Match 'save with spaces'
        (Get-Acl -LiteralPath $root).Sddl | Should -Be $before
    }

    It 'restores root and descendant DACLs with actual icacls and the saved parent path' {
        $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            Set-ItResult -Skipped -Because 'icacls /restore requires an elevated Windows token; unprivileged reproduction returned exit 1300 (missing privilege).'
            return
        }
        $root = Join-Path $TestDrive 'restore with spaces'
        New-Item -ItemType Directory $root | Out-Null
        Set-FixtureAcl $root -Broad
        $child = New-Item -ItemType Directory (Join-Path $root 'child')
        Set-Content (Join-Path $child.FullName 'synthetic.txt') 'synthetic'
        $paths = @($root, $child.FullName, (Join-Path $child.FullName 'synthetic.txt'))
        $before = @($paths | ForEach-Object { (Get-Acl -LiteralPath $_).Sddl })
        $backup = Join-Path $TestDrive 'saved.acl'
        Invoke-ALIcacls @($root, '/save', $backup, '/T', '/Q')
        try {
            Set-FixtureAcl $root
            (Get-ALAclAudit $root 'private' 'fixture').findings.Count | Should -Be 0
        } finally { Invoke-ALIcacls @((Split-Path $root), '/restore', $backup, '/Q') }
        @($paths | ForEach-Object { (Get-Acl -LiteralPath $_).Sddl }) | Should -Be $before
    }
}
