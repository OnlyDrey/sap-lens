# Part of SapLens.Deploy, dot-sourced into the same module. No operations run on import.
# NTFS policy for SAP Lens private state, release binaries and the parents of migration targets. Principals are compared by well-known SID, never
# by (localized) account name. Audit is read-only; Invoke-SL2ProtectAcl changes ACLs only after an explicit, approved call (Deploy-SapLens.ps1
# -Action ProtectAcl -Yes), saves every affected ACL first (icacls /save, restorable with -Action RestoreAcl) and never touches system roots.

# Broad principals: any interactive or authenticated user of the machine or domain. Domain Users and Domain Guests (RID 513/514) match by pattern.
$script:BroadSids = [ordered]@{
    'S-1-1-0' = 'Everyone'; 'S-1-5-11' = 'Authenticated Users'; 'S-1-5-32-545' = 'Users'; 'S-1-5-4' = 'Interactive'; 'S-1-5-2' = 'Network'
    'S-1-5-7' = 'Anonymous Logon'; 'S-1-5-32-546' = 'Guests'
}
# FileSystemRights bits (as unsigned 32-bit values). Read: ReadData/ListDirectory, GENERIC_READ, GENERIC_ALL. Write: WriteData/CreateFiles,
# AppendData/CreateDirectories, WriteExtendedAttributes, DeleteSubdirectoriesAndFiles, WriteAttributes, Delete, ChangePermissions,
# TakeOwnership, GENERIC_WRITE, GENERIC_ALL. Execute, ReadAttributes and ReadPermissions alone are neither.
$script:AclRead = [int64]1 -bor [int64]2147483648 -bor [int64]268435456
$script:AclWrite = [int64](2 + 4 + 16 + 64 + 256 + 65536 + 262144 + 524288) -bor [int64]1073741824 -bor [int64]268435456
$script:AclSystem = 'S-1-5-18'; $script:AclAdministrators = 'S-1-5-32-544'

function Test-SL2BroadSid([string]$Sid) { $script:BroadSids.Contains($Sid) -or $Sid -match '^S-1-5-21-\d+-\d+-\d+-51[34]$' }

function Get-SL2BroadName([string]$Sid) {
    if ($script:BroadSids.Contains($Sid)) { return $script:BroadSids[$Sid] }
    if ($Sid -like '*-513') { 'Domain Users' } else { 'Domain Guests' }
}

# The explicit and inherited allow/deny rules of a path as plain objects (Windows only; tests replace it). Rights are unsigned 32-bit values so the
# generic bits compare correctly in Windows PowerShell 5.1 and PowerShell 7.
function Get-SL2AclRules([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        [pscustomobject]@{
            Sid = $rule.IdentityReference.Value
            Rights = [int64][BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$rule.FileSystemRights), 0)
            Allow = ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow); Inherited = $rule.IsInherited
            ContainerInherit = [bool]($rule.InheritanceFlags -band [Security.AccessControl.InheritanceFlags]::ContainerInherit)
            ObjectInherit = [bool]($rule.InheritanceFlags -band [Security.AccessControl.InheritanceFlags]::ObjectInherit)
            InheritOnly = [bool]($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)
        }
    }
}

# Pure policy. Class 'private' (data, backups, keys, TLS, deployment state and the parents of new private targets): no broad read or write.
# Class 'binaries' (release folders, configuration files and the parents of new release roots): broad read and execute are legitimate, write is not.
# A rule counts when it applies to the object itself, or (for a folder) when new children inherit it: inherit-only rules on a parent are exactly
# what a directory created by the migration would receive.
function Get-SL2AclFindings($Rules, [ValidateSet('private', 'binaries')][string]$Class, [bool]$IsContainer) {
    $mask = if ($Class -eq 'private') { $script:AclRead -bor $script:AclWrite } else { $script:AclWrite }
    foreach ($rule in @($Rules)) {
        if (-not $rule -or -not $rule.Allow -or -not (Test-SL2BroadSid $rule.Sid)) { continue }
        $self = -not $rule.InheritOnly
        $children = $IsContainer -and ($rule.ContainerInherit -or $rule.ObjectInherit)
        if ((-not $self -and -not $children) -or -not ([int64]$rule.Rights -band $mask)) { continue }
        [pscustomobject]@{
            sid = $rule.Sid; principal = (Get-SL2BroadName $rule.Sid)
            access = $(if ([int64]$rule.Rights -band $script:AclWrite) { 'write' } else { 'read' })
            rights = ('0x{0:X8}' -f [int64]$rule.Rights); inherited = [bool]$rule.Inherited
            applies = $(if ($self -and $children) { 'this folder and new children' } elseif ($self) { 'this object' } else { 'new children only' })
        }
    }
}

# Audits one path (and, with -Recurse, every descendant). A missing path has no findings; the caller decides whether that is acceptable.
function Get-SL2AclAudit([string]$Path, [string]$Class, [string]$Role, [switch]$Recurse) {
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ path = $Path; role = $Role; class = $Class; exists = $false; findings = @() } }
    $item = Get-Item -LiteralPath $Path -Force
    $findings = @(Get-SL2AclFindings @(Get-SL2AclRules $Path) $Class $item.PSIsContainer | ForEach-Object { $_ | Add-Member -NotePropertyName path -NotePropertyValue $Path -PassThru })
    if ($Recurse -and $item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $Path -Recurse -Force) {
            if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            $findings += @(Get-SL2AclFindings @(Get-SL2AclRules $child.FullName) $Class $child.PSIsContainer | Where-Object { -not $_.inherited } |
                ForEach-Object { $_ | Add-Member -NotePropertyName path -NotePropertyValue $child.FullName -PassThru })
        }
    }
    [pscustomobject]@{ path = $Path; role = $Role; class = $Class; exists = $true; findings = $findings }
}

# The paths a migration (or a protected deployment) depends on, each with its class. Descendant findings that only repeat an inherited rule of the
# audited root are folded into the root's finding.
function Get-SL2AclPlan($Source, $Target, [string]$KeyPath = '') {
    $plan = [System.Collections.Generic.List[object]]::new()
    if ($Source) {
        if (-not $KeyPath) {
            $pointer = Join-SL2 $Source.DataDirectory 'backup-key-location.json'
            if (Test-Path -LiteralPath $pointer) { $KeyPath = "$((Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json).path)" }
        }
        $plan.Add([pscustomobject]@{ Path = $Source.DataDirectory; Class = 'private'; Role = 'source data'; Recurse = $true; Grant = 'M' })
        $plan.Add([pscustomobject]@{ Path = $Source.BackupRoot; Class = 'private'; Role = 'source pre-deployment backups'; Recurse = $true; Grant = '' })
        $plan.Add([pscustomobject]@{ Path = (Split-Path $Source.CertificatePath); Class = 'private'; Role = 'source TLS'; Recurse = $true; Grant = 'R' })
        if ($KeyPath) { $plan.Add([pscustomobject]@{ Path = (Split-Path $KeyPath); Class = 'private'; Role = 'source backup key'; Recurse = $true; Grant = 'R' }) }
        $plan.Add([pscustomobject]@{ Path = $Source.WorkRoot; Class = 'private'; Role = 'source deployment state'; Recurse = $false; Grant = '' })
        $plan.Add([pscustomobject]@{ Path = $Source.ReleasesRoot; Class = 'binaries'; Role = 'source releases'; Recurse = $false; Grant = 'RX' })
        $plan.Add([pscustomobject]@{ Path = $Source.ConfigFile; Class = 'binaries'; Role = 'source configuration'; Recurse = $false; Grant = '' })
        # The installation folder that holds the configuration (for example C:\saplens2): no broad write, so nobody can plant files or folders there.
        $plan.Add([pscustomobject]@{ Path = (Split-Path $Source.ConfigFile); Class = 'binaries'; Role = 'source installation folder'; Recurse = $false; Grant = '' })
    }
    if ($Target) {
        # A new target root inherits from its parent. Audit the parent that will hold it (or, while that parent is missing, the nearest existing
        # ancestor): private targets need a private parent, the release root only a parent without broad write.
        $roots = @(
            @($Target.DataDirectory, 'private'), @($Target.BackupRoot, 'private'), @((Split-Path $Target.CertificatePath), 'private'),
            @((Join-SL2 (Split-Path $Target.DataDirectory) 'backup'), 'private'), @($Target.WorkRoot, 'private'), @($Target.ReleasesRoot, 'binaries'))
        $parents = [ordered]@{}
        foreach ($root in $roots) {
            $parent = Split-Path $root[0]
            if ($parents.Contains($parent)) { if ($root[1] -eq 'private') { $parents[$parent] = 'private' } } else { $parents[$parent] = $root[1] }
        }
        foreach ($parent in $parents.Keys) {
            $existing = $parent
            while ($existing -and -not (Test-Path -LiteralPath $existing)) { $existing = Split-Path $existing }
            $plan.Add([pscustomobject]@{ Path = $parent; Class = $parents[$parent]; Role = 'target parent'; Recurse = $false; Grant = ''; Existing = $existing })
        }
        $plan.Add([pscustomobject]@{ Path = $Target.ConfigFile; Class = 'binaries'; Role = 'target configuration'; Recurse = $false; Grant = '' })
    }
    $plan.ToArray()
}

function Get-SL2AclReport($Plan) {
    $entries = foreach ($entry in @($Plan)) {
        $audited = if ($entry.PSObject.Properties['Existing'] -and $entry.Existing -ne $entry.Path) { $entry.Existing } else { $entry.Path }
        $audit = if ($audited) { Get-SL2AclAudit $audited $entry.Class $entry.Role -Recurse:$entry.Recurse } else { [pscustomobject]@{ path = ''; findings = @(); exists = $false } }
        $provision = $entry.Role -eq 'target parent' -and -not (Test-Path -LiteralPath $entry.Path) -and
            -not (Test-SL2AclForbidden $entry.Path) -and $audited -and (Test-SL2ProvisioningAncestor $audited)
        $required = $true
        if (Test-Path -LiteralPath $entry.Path) { try { Assert-SL2AclRequiredAccess $entry.Path } catch { $required = $false } }
        [pscustomobject]@{ path = $entry.Path; audited = $audited; role = $entry.Role; class = $entry.Class; exists = (Test-Path -LiteralPath $entry.Path)
            provisioning_required = $provision; blocking = -not $provision; required_access_verified = $required; findings = @($audit.findings) }
    }
    $entries = @($entries)
    [pscustomobject]@{ safe = (@($entries | Where-Object { $_.blocking -and ($_.findings.Count -gt 0 -or -not $_.required_access_verified) }).Count -eq 0); entries = $entries
        provisioning_required = @($entries | Where-Object provisioning_required | ForEach-Object path) }
}

function Format-SL2AclFindings($Report, [int]$Limit = 6) {
    $lines = foreach ($entry in @($Report.entries)) {
        if (-not $entry.required_access_verified) { "$($entry.path) ($($entry.role)): required SYSTEM/Administrators access is unverified" }
        foreach ($finding in @($entry.findings)) {
        '{0} ({1}): {2} has {3} access ({4}, {5}, {6})' -f $finding.path, $entry.role, $finding.principal, $finding.access, $finding.rights,
            $(if ($finding.inherited) { 'inherited' } else { 'explicit' }), $finding.applies } }
    $lines = @($lines)
    (@($lines | Select-Object -First $Limit) + $(if ($lines.Count -gt $Limit) { @("... and $($lines.Count - $Limit) more (run -Action AuditAcl)") } else { @() })) -join '; '
}

# Throws a refusal that names every unsafe path, principal and right (used by the migration preflight).
function Assert-SL2AclPlan($Plan, [string]$What) {
    $report = Get-SL2AclReport $Plan
    if (-not $report.safe) { Stop-SL2 "$What has broad NTFS access; review it with -Action AuditAcl and prepare it with -Action ProtectAcl: $(Format-SL2AclFindings $report)" }
    $report
}

# ---- remediation (explicit, approved; never run by the preflight or a deployment)

# System locations whose ACLs SAP Lens never changes, however a configuration names them.
function Test-SL2AclForbidden([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if (-not [IO.Path]::GetDirectoryName($full) -or $full -eq [IO.Path]::GetPathRoot($full).TrimEnd('\', '/')) { return $true }
    foreach ($name in 'ProgramData', 'SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'USERPROFILE', 'PUBLIC') {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value -and $full -ieq [IO.Path]::GetFullPath($value).TrimEnd('\', '/')) { return $true }
    }
    $drive = [Environment]::GetEnvironmentVariable('SystemDrive')
    if ($drive -and $full -ieq "$drive\Users") { return $true }
    $false
}

function Invoke-SL2Icacls([string[]]$Arguments) {
    $result = Invoke-SL2Process 'icacls.exe' $Arguments ''
    if ($result.ExitCode -ne 0) { Stop-SL2 "icacls $($Arguments -join ' ') failed ($(($result.Output | Select-Object -Last 1)))." 1 }
}

# The identity entries of a protected DACL: SYSTEM and Administrators full control, the service's virtual account (only for an NT SERVICE account;
# LocalSystem is SYSTEM) with the access its role needs, and read/execute for authenticated users on release binaries.
function Get-SL2AclGrants($Entry, [string]$ServiceAccount, [bool]$IsContainer) {
    $inherit = if ($IsContainer) { '(OI)(CI)' } else { '' }
    $grants = @("*${script:AclSystem}:${inherit}F", "*${script:AclAdministrators}:${inherit}F")
    if ($Entry.Grant -and $ServiceAccount -like 'NT SERVICE\*') { $grants += "${ServiceAccount}:${inherit}$($Entry.Grant)" }
    $grants
}

function Test-SL2PathWithin([string]$Path, [string]$Root) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $full -ieq $base -or $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-SL2AclApproved([string]$Path, [string[]]$ApprovedRoots) {
    if (-not $ApprovedRoots -or $ApprovedRoots.Count -eq 0) { Stop-SL2 'ACL changes require explicit -ApprovedAclRoot application-owned roots.' }
    if (-not [IO.Path]::IsPathRooted($Path) -or (Test-SL2AclForbidden $Path)) { Stop-SL2 "Refusing ACL changes at system location or relative path $Path." }
    foreach ($root in $ApprovedRoots) {
        if (-not [IO.Path]::IsPathRooted($root) -or (Test-SL2AclForbidden $root)) { Stop-SL2 'Approved ACL roots must be dedicated absolute application folders, never system locations.' }
        Test-SL2PathTree $root
    }
    if (-not @($ApprovedRoots | Where-Object { Test-SL2PathWithin $Path $_ }).Count) { Stop-SL2 "ACL path $Path is outside the explicitly approved application roots." }
    Test-SL2PathTree $Path
}

function Get-SL2AclSnapshot([string]$Path) {
    Test-SL2PathTree $Path
    $items = @((Get-Item -LiteralPath $Path -Force))
    if ($items[0].PSIsContainer) {
        $null = @(Get-SL2TreeFiles $Path) # reject descendant links before recursing
        $items += @(Get-ChildItem -LiteralPath $Path -Force -Recurse | Sort-Object FullName)
    }
    foreach ($item in $items) {
        [pscustomobject]@{ path = $item.FullName; dacl = (Get-Acl -LiteralPath $item.FullName).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) }
    }
}

function Assert-SL2AclRequiredAccess([string]$Path) {
    $rules = @(Get-SL2AclRules $Path)
    foreach ($sid in $script:AclSystem, $script:AclAdministrators) {
        if (@($rules | Where-Object { $_.Sid -eq $sid -and -not $_.Allow -and -not $_.InheritOnly }).Count -or
            -not @($rules | Where-Object { $_.Sid -eq $sid -and $_.Allow -and -not $_.InheritOnly -and ($_.Rights -band 0x1F01FF) -eq 0x1F01FF }).Count) {
            Stop-SL2 "Required SYSTEM/Administrators full control is not verified at $Path."
        }
    }
}

function Test-SL2ProvisioningAncestor([string]$Path) {
    foreach ($rule in @(Get-SL2AclRules $Path)) {
        if ($rule.Allow -and -not $rule.InheritOnly -and (Test-SL2BroadSid $rule.Sid) -and
            ($rule.Rights -band (64 + 65536 + 262144 + 524288 + 1073741824 + 268435456))) { return $false }
    }
    $true
}

# One native create operation supplies the DACL. No inheritance-then-protect window and no overwrite on a raced path.
function Test-SL2DaclEqual([string]$Expected, [string]$Actual) {
    $a = [Security.AccessControl.RawSecurityDescriptor]::new($Expected)
    $b = [Security.AccessControl.RawSecurityDescriptor]::new($Actual)
    $protected = [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected
    if (-not $a.DiscretionaryAcl -or -not $b.DiscretionaryAcl -or ($a.ControlFlags -band $protected) -ne ($b.ControlFlags -band $protected)) { return $false }
    $left = New-Object byte[] $a.DiscretionaryAcl.BinaryLength
    $right = New-Object byte[] $b.DiscretionaryAcl.BinaryLength
    $a.DiscretionaryAcl.GetBinaryForm($left, 0); $b.DiscretionaryAcl.GetBinaryForm($right, 0)
    # Windows clears AUTO_INHERITED on a newly created protected DACL. Compare the ACE bytes and protection, not that bookkeeping flag.
    [Convert]::ToBase64String($left) -ceq [Convert]::ToBase64String($right)
}

function New-SL2DirectoryWithAcl([string]$Path, [Security.AccessControl.DirectorySecurity]$Security) {
    if ([IO.Path]::DirectorySeparatorChar -ne '\') { Stop-SL2 'Secure provisioning requires Windows NTFS.' }
    if (-not $Security.AreAccessRulesProtected) { Stop-SL2 'Secure creation requires a protected DACL.' }
    Test-SL2PathTree $Path
    if ([IO.DriveInfo]::new([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))).DriveFormat -ne 'NTFS') { Stop-SL2 'Secure provisioning requires local NTFS.' }
    if (-not (Test-SL2ProvisioningAncestor (Split-Path $Path))) { Stop-SL2 'The provisioning parent permits broad replacement or ACL changes; choose a protected application backup/provisioning root.' }
    if (-not ('SapLens.NativeDirectory' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace SapLens {
    public static class NativeDirectory {
        [StructLayout(LayoutKind.Sequential)] public struct Attributes {
            public int Length; public IntPtr Descriptor; [MarshalAs(UnmanagedType.Bool)] public bool Inherit;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CreateDirectoryW(string path, ref Attributes attributes);
        public static int Create(string path, byte[] descriptor) {
            var pin = GCHandle.Alloc(descriptor, GCHandleType.Pinned);
            try {
                var attributes = new Attributes { Length = Marshal.SizeOf(typeof(Attributes)), Descriptor = pin.AddrOfPinnedObject(), Inherit = false };
                return CreateDirectoryW(path, ref attributes) ? 0 : Marshal.GetLastWin32Error();
            } finally { pin.Free(); }
        }
    }
}
'@
    }
    $errorCode = [SapLens.NativeDirectory]::Create($Path, $Security.GetSecurityDescriptorBinaryForm())
    if ($errorCode) { Stop-SL2 "Exclusive secure directory creation failed at $Path (Windows error $errorCode). Nothing was overwritten." }
    Test-SL2PathTree $Path
    $access = [Security.AccessControl.AccessControlSections]::Access
    if (-not (Test-SL2DaclEqual $Security.GetSecurityDescriptorSddlForm($access) (Get-Acl -LiteralPath $Path).GetSecurityDescriptorSddlForm($access))) {
        Stop-SL2 "Created directory security differs at $Path; no sensitive file may be written." 4
    }
}

function New-SL2SecureDirectory([string]$Path, [string[]]$ApprovedRoots, [switch]$Exclusive) {
    Assert-SL2AclApproved $Path $ApprovedRoots
    if (Test-Path -LiteralPath $Path) {
        if ($Exclusive) { Stop-SL2 'Migration never merges or overwrites existing staging.' }
        Assert-SL2AclRequiredAccess $Path
        $audit = Get-SL2AclAudit $Path 'private' 'secure provisioning'
        if ($audit.findings.Count) { Stop-SL2 "Existing application path $Path is insecure; explicit ACL remediation is required." }
        return
    }
    $parent = Split-Path $Path
    if (-not (Test-Path -LiteralPath $parent)) { New-SL2SecureDirectory $parent $ApprovedRoots }
    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sid in $script:AclSystem, $script:AclAdministrators) {
        $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), 'FullControl',
            [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))
    }
    New-SL2DirectoryWithAcl $Path $security
    Assert-SL2AclRequiredAccess $Path
    if ((Get-SL2AclAudit $Path 'private' 'secure provisioning').findings.Count) { Stop-SL2 'Secure provisioning verification failed; no sensitive file may be written.' }
}

# Saves the ACLs (with descendants) of every path that will change into a new protected backup folder, then applies protected DACLs: inheritance
# removed, explicit broad grants removed, SYSTEM/Administrators/service grants set, and descendants reset to inherit (their explicit grants are in
# the backup). Missing target parents are created protected. ProgramData, Program Files, the Windows folder, user roots and drive roots are
# refused. The running service keeps its access (SYSTEM, or its own grant), so nothing is stopped.
function Invoke-SL2ProtectAcl($Source, $Target, [string]$BackupRoot, [string[]]$ApprovedRoots) {
    $serviceAccount = if ($Source) { $Source.ServiceAccount } else { $Target.ServiceAccount }
    $plan = @(Get-SL2AclPlan $Source $Target)
    # Validate the entire scope before creating even the ACL backup folder.
    Assert-SL2AclApproved $BackupRoot $ApprovedRoots
    foreach ($entry in $plan) {
        Assert-SL2AclApproved $entry.Path $ApprovedRoots; Test-SL2PathTree $entry.Path
        if (Test-SL2PathOverlap $entry.Path $BackupRoot) { Stop-SL2 'ACL backup storage must be disjoint from every affected application tree; supply a dedicated -AclBackupRoot.' }
    }
    $report = Get-SL2AclReport $plan
    $changes = @(foreach ($entry in $plan) {
        $row = @($report.entries | Where-Object { $_.path -eq $entry.Path -and $_.role -eq $entry.Role })[0]
        $create = $entry.Role -eq 'target parent' -and -not (Test-Path -LiteralPath $entry.Path)
        if ($row.findings.Count -eq 0 -and $row.required_access_verified -and -not $create) { continue }
        [pscustomobject]@{ Entry = $entry; Create = $create; BroadSids = @($row.findings | ForEach-Object sid | Sort-Object -Unique) }
    })
    if (-not $changes.Count) { return [pscustomobject]@{ changed = @(); created = @(); backup = $null; after = $report } }
    $backup = Join-SL2 $BackupRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N'))
    New-SL2SecureDirectory $backup $ApprovedRoots
    $records = [Collections.Generic.List[object]]::new(); $index = 0
    foreach ($change in $changes) {
        $path = $change.Entry.Path
        if ($change.Create) { $records.Add([pscustomobject]@{ path = $path; created = $true; file = ''; parent = ''; sha256 = ''; snapshot = @() }); continue }
        $snapshot = @(Get-SL2AclSnapshot $path)
        $file = Join-SL2 $backup ('{0:D2}.acl' -f ++$index)
        $arguments = @($path, '/save', $file, '/C', '/Q'); if ((Get-Item -LiteralPath $path -Force).PSIsContainer) { $arguments += '/T' }
        Invoke-SL2Icacls $arguments
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-Item -LiteralPath $file).Length -eq 0) { Stop-SL2 'ACL backup was not written; application permissions are unchanged.' }
        $records.Add([pscustomobject]@{ path = $path; created = $false; file = $file; parent = (Split-Path $path)
            sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash; snapshot = $snapshot })
    }
    [IO.File]::WriteAllText((Join-SL2 $backup 'acl-backup.json'), ([pscustomobject]@{ schema = 2; entries = $records.ToArray() } | ConvertTo-Json -Depth 8))
    foreach ($change in $changes) {
        $path = $change.Entry.Path
        if ($change.Create) { New-SL2SecureDirectory $path $ApprovedRoots; continue }
        $isContainer = (Get-Item -LiteralPath $path -Force).PSIsContainer
        Invoke-SL2Icacls (@($path, '/inheritance:r', '/grant:r') + @(Get-SL2AclGrants $change.Entry $serviceAccount $isContainer))
        $broad = @(@($script:BroadSids.Keys) + @($change.BroadSids) | Sort-Object -Unique | ForEach-Object { "*$_" })
        Invoke-SL2Icacls (@($path, '/remove:g') + $broad)
        if ($change.Entry.Class -eq 'binaries' -and $change.Entry.Role -notin @('source configuration', 'target configuration')) {
            Invoke-SL2Icacls @($path, '/grant:r', "*S-1-5-11:$(if ($isContainer) { '(OI)(CI)' })RX")
        }
        if ($isContainer -and $change.Entry.Recurse -and @(Get-ChildItem -LiteralPath $path -Force).Count) {
            Invoke-SL2Icacls @((Join-SL2 $path '*'), '/reset', '/T', '/C', '/Q')
        }
        Assert-SL2AclRequiredAccess $path
    }
    $after = Get-SL2AclReport (Get-SL2AclPlan $Source $Target)
    if (-not $after.safe) { Stop-SL2 "ACL remediation verification failed; retain $backup for reviewed restoration." 1 }
    [pscustomobject]@{ changed = @($changes | ForEach-Object { $_.Entry.Path }); created = @($changes | Where-Object Create | ForEach-Object { $_.Entry.Path })
        backup = $backup; after = $after }
}

function Invoke-SL2RestoreAcl([string]$Backup, [string[]]$ApprovedRoots) {
    Assert-SL2AclApproved $Backup $ApprovedRoots
    Test-SL2PathTree $Backup
    if ((Get-SL2AclAudit $Backup 'private' 'ACL backup' -Recurse).findings.Count) { Stop-SL2 'ACL backup storage is not private; review it before restoration.' }
    if (-not (Test-Path -LiteralPath (Join-SL2 $Backup 'acl-backup.json') -PathType Leaf)) { Stop-SL2 'This is not an ACL backup.' }
    $saved = Get-Content -LiteralPath (Join-SL2 $Backup 'acl-backup.json') -Raw | ConvertFrom-Json
    if ($saved.schema -ne 2) { Stop-SL2 'This ACL backup lacks verified schema-2 inventories; retain it for reviewed manual restoration.' }
    $entries = @($saved.entries); [Array]::Reverse($entries)
    if (-not $entries.Count) { Stop-SL2 'The ACL backup contains no inventories.' }
    # Check every record before restoring the first one, including the saved file and inventory scope.
    foreach ($entry in $entries) {
        Assert-SL2AclApproved $entry.path $ApprovedRoots; Test-SL2PathTree $entry.path
        if ($entry.created) { continue }
        if ($entry.parent -ne (Split-Path $entry.path) -or (Split-Path $entry.file) -ne $Backup) { Stop-SL2 'ACL backup paths do not match their reviewed scope.' }
        Test-SL2PathTree $entry.file
        if (-not (Test-Path -LiteralPath $entry.file -PathType Leaf) -or (Get-FileHash -LiteralPath $entry.file -Algorithm SHA256).Hash -ne $entry.sha256) { Stop-SL2 'ACL backup is missing or its checksum differs; nothing was restored.' }
        foreach ($item in @($entry.snapshot)) {
            Assert-SL2AclApproved $item.path $ApprovedRoots
            if ($item.path -ne $entry.path -and -not (Test-SL2PathWithin $item.path $entry.path)) { Stop-SL2 'ACL inventory escapes its saved root.' }
        }
        Test-SL2AclBackupFile $entry
    }
    foreach ($entry in $entries) {
        if ($entry.created) { continue }
        Invoke-SL2Icacls @($entry.parent, '/restore', $entry.file, '/C', '/Q')
        foreach ($item in @($entry.snapshot)) {
            Test-SL2PathTree $item.path
            if (-not (Test-Path -LiteralPath $item.path) -or
                (Get-Acl -LiteralPath $item.path).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) -cne $item.dacl) {
                Stop-SL2 'Restored ACL inventory differs; manual recovery is required.' 4
            }
        }
    }
    [pscustomobject]@{ verified = $true; restored = @($entries | Where-Object { -not $_.created } | ForEach-Object path)
        kept_created = @($entries | Where-Object created | ForEach-Object path) }
}

# icacls /save stores UTF-16 path/DACL pairs. Validate their destinations as well as the file checksum before invoking /restore.
function Test-SL2AclBackupFile($Entry) {
    $lines = [IO.File]::ReadAllLines($Entry.file, [Text.Encoding]::Unicode)
    if (-not $lines.Count -or $lines.Count % 2 -ne 0 -or $lines.Count / 2 -ne @($Entry.snapshot).Count) { Stop-SL2 'ACL backup inventory format differs.' }
    $seen = @{}
    for ($i = 0; $i -lt $lines.Count; $i += 2) {
        if ([IO.Path]::IsPathRooted($lines[$i])) { Stop-SL2 'ACL backup contains an absolute restore path.' }
        $full = [IO.Path]::GetFullPath((Join-SL2 $Entry.parent $lines[$i]))
        $expected = @($Entry.snapshot | Where-Object path -eq $full)
        if (-not (Test-SL2PathWithin $full $Entry.path) -or $expected.Count -ne 1 -or $seen.ContainsKey($full)) { Stop-SL2 'ACL backup restore paths escape or differ from the saved inventory.' }
        if (-not (Test-SL2DaclEqual $expected[0].dacl $lines[$i + 1])) { Stop-SL2 'ACL backup DACL differs from its saved inventory.' }
        $seen[$full] = $true
    }
}
