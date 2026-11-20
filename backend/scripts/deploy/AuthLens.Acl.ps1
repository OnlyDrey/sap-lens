# Part of AuthLens.Deploy, dot-sourced into the same module. No operations run on import.
# NTFS policy for AuthLens private state and release binaries. Principals are compared by well-known SID, never
# by (localized) account name. Audit is read-only; Invoke-ALProtectAcl changes ACLs only after an explicit, approved call (Deploy-AuthLens.ps1
# -Action ProtectAcl -Yes), saves every affected DACL first (icacls-compatible inventories, restorable with -Action RestoreAcl) and never touches system roots.

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

function Test-ALBroadSid([string]$Sid) { $script:BroadSids.Contains($Sid) -or $Sid -match '^S-1-5-21-\d+-\d+-\d+-51[34]$' }

function Get-ALBroadName([string]$Sid) {
    if ($script:BroadSids.Contains($Sid)) { return $script:BroadSids[$Sid] }
    if ($Sid -like '*-513') { 'Domain Users' } else { 'Domain Guests' }
}

# The explicit and inherited allow/deny rules of a path as plain objects (Windows only; tests replace it). Rights are unsigned 32-bit values so the
# generic bits compare correctly in Windows PowerShell 5.1 and PowerShell 7.
function Get-ALAclRules([string]$Path) {
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

# Pure policy. Class 'private' (data, backups, keys, TLS, deployment state): no broad read or write.
# Class 'binaries' (release folders, configuration files and the parents of new release roots): broad read and execute are legitimate, write is not.
# A rule counts when it applies to the object itself, or (for a folder) when new children inherit it: inherit-only rules on a parent are exactly
# what a directory created by the migration would receive.
function Get-ALAclFindings($Rules, [ValidateSet('private', 'binaries')][string]$Class, [bool]$IsContainer) {
    $mask = if ($Class -eq 'private') { $script:AclRead -bor $script:AclWrite } else { $script:AclWrite }
    foreach ($rule in @($Rules)) {
        if (-not $rule -or -not $rule.Allow -or -not (Test-ALBroadSid $rule.Sid)) { continue }
        $self = -not $rule.InheritOnly
        $children = $IsContainer -and ($rule.ContainerInherit -or $rule.ObjectInherit)
        if ((-not $self -and -not $children) -or -not ([int64]$rule.Rights -band $mask)) { continue }
        [pscustomobject]@{
            sid = $rule.Sid; principal = (Get-ALBroadName $rule.Sid)
            access = $(if ([int64]$rule.Rights -band $script:AclWrite) { 'write' } else { 'read' })
            rights = ('0x{0:X8}' -f [int64]$rule.Rights); inherited = [bool]$rule.Inherited
            applies = $(if ($self -and $children) { 'this folder and new children' } elseif ($self) { 'this object' } else { 'new children only' })
        }
    }
}

# Audits one path (and, with -Recurse, every descendant). A missing path has no findings; the caller decides whether that is acceptable.
function Get-ALAclAudit([string]$Path, [string]$Class, [string]$Role, [switch]$Recurse) {
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ path = $Path; role = $Role; class = $Class; exists = $false; findings = @() } }
    $item = Get-Item -LiteralPath $Path -Force
    $findings = [Collections.Generic.List[object]]::new()
    foreach ($finding in @(Get-ALAclFindings @(Get-ALAclRules $Path) $Class $item.PSIsContainer)) {
        $finding | Add-Member -NotePropertyName path -NotePropertyValue $Path
        $findings.Add($finding)
    }
    if ($Recurse -and $item.PSIsContainer) {
        Write-ALAclProgress 'audit_inventory' -Stage $Path
        $children = @(Get-ALAclItems $Path | Where-Object FullName -ne $item.FullName)
        $processed = 0
        foreach ($child in $children) {
            foreach ($finding in @(Get-ALAclFindings @(Get-ALAclRules $child.FullName) $Class $child.PSIsContainer | Where-Object { -not $_.inherited })) {
                $finding | Add-Member -NotePropertyName path -NotePropertyValue $child.FullName
                $findings.Add($finding)
            }
            Write-ALAclProgress 'audit' (++$processed) $children.Count $Path
        }
        Write-ALAclProgress 'audit' $processed $children.Count $Path -Force
    }
    [pscustomobject]@{ path = $Path; role = $Role; class = $Class; exists = $true; findings = $findings.ToArray() }
}

# The paths an installation depends on, each with its class and the access its service needs: data (database, logs, backups, accounts) modify;
# TLS and the backup key read; release binaries read/execute; pre-deployment backups, deployment state and configuration nothing beyond
# SYSTEM/Administrators. Descendant findings that only repeat an inherited rule of the audited root are folded into the root's finding.
function Get-ALAclPlan($Config, [string]$KeyPath = '') {
    if (-not $KeyPath) {
        $pointer = Join-AL $Config.DataDirectory 'backup-key-location.json'
        if (Test-Path -LiteralPath $pointer) { $KeyPath = "$((Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json).path)" }
    }
    @(
        [pscustomobject]@{ Path = $Config.DataDirectory; Class = 'private'; Role = 'data'; Recurse = $true; Grant = 'M' }
        [pscustomobject]@{ Path = $Config.BackupRoot; Class = 'private'; Role = 'pre-deployment backups'; Recurse = $true; Grant = '' }
        [pscustomobject]@{ Path = (Split-Path $Config.CertificatePath); Class = 'private'; Role = 'TLS'; Recurse = $true; Grant = 'R' }
        if ($KeyPath) { [pscustomobject]@{ Path = (Split-Path $KeyPath); Class = 'private'; Role = 'backup key'; Recurse = $true; Grant = 'R' } }
        [pscustomobject]@{ Path = $Config.WorkRoot; Class = 'private'; Role = 'deployment state'; Recurse = $false; Grant = '' }
        [pscustomobject]@{ Path = $Config.ReleasesRoot; Class = 'binaries'; Role = 'releases'; Recurse = $false; Grant = 'RX' }
        [pscustomobject]@{ Path = $Config.ConfigFile; Class = 'binaries'; Role = 'configuration'; Recurse = $false; Grant = '' }
        # The folder that holds the configuration (C:\ProgramData\AuthLens\config): no broad write, so nobody can plant files or folders there.
        [pscustomobject]@{ Path = (Split-Path $Config.ConfigFile); Class = 'binaries'; Role = 'configuration folder'; Recurse = $false; Grant = '' }
    )
}

function Get-ALAclReport($Plan) {
    $entries = foreach ($entry in @($Plan)) {
        $audit = Get-ALAclAudit $entry.Path $entry.Class $entry.Role -Recurse:$entry.Recurse
        $required = $true
        if (Test-Path -LiteralPath $entry.Path) { try { Assert-ALAclRequiredAccess $entry.Path } catch { $required = $false } }
        [pscustomobject]@{ path = $entry.Path; role = $entry.Role; class = $entry.Class; exists = (Test-Path -LiteralPath $entry.Path)
            required_access_verified = $required; findings = @($audit.findings) }
    }
    $entries = @($entries)
    [pscustomobject]@{ safe = (@($entries | Where-Object { $_.findings.Count -gt 0 -or -not $_.required_access_verified }).Count -eq 0); entries = $entries }
}

function Format-ALAclFindings($Report, [int]$Limit = 6) {
    $lines = foreach ($entry in @($Report.entries)) {
        if (-not $entry.required_access_verified) { "$($entry.path) ($($entry.role)): required SYSTEM/Administrators access is unverified" }
        foreach ($finding in @($entry.findings)) {
        '{0} ({1}): {2} has {3} access ({4}, {5}, {6})' -f $finding.path, $entry.role, $finding.principal, $finding.access, $finding.rights,
            $(if ($finding.inherited) { 'inherited' } else { 'explicit' }), $finding.applies } }
    $lines = @($lines)
    (@($lines | Select-Object -First $Limit) + $(if ($lines.Count -gt $Limit) { @("... and $($lines.Count - $Limit) more (run -Action AuditAcl)") } else { @() })) -join '; '
}

# Throws a refusal that names every unsafe path, principal and right.
function Assert-ALAclPlan($Plan, [string]$What) {
    $report = Get-ALAclReport $Plan
    if (-not $report.safe) { Stop-AL "$What has broad NTFS access; review it with -Action AuditAcl and prepare it with -Action ProtectAcl: $(Format-ALAclFindings $report)" }
    $report
}

# ---- remediation (explicit, approved; never run by a deployment)

# System locations whose ACLs AuthLens never changes, however a configuration names them.
function Test-ALAclForbidden([string]$Path) {
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

function Invoke-ALIcacls([string[]]$Arguments) {
    $result = Invoke-ALProcess 'icacls.exe' $Arguments ''
    if ($result.ExitCode -ne 0) { Stop-AL "icacls $($Arguments -join ' ') failed ($(($result.Output | Select-Object -Last 1)))." 1 }
}

# The identity entries of a protected DACL: SYSTEM and Administrators full control, the service's virtual account (only for an NT SERVICE account;
# LocalSystem is SYSTEM) with the access its role needs, and read/execute for authenticated users on release binaries.
function Get-ALAclGrants($Entry, [string]$ServiceAccount, [bool]$IsContainer) {
    $inherit = if ($IsContainer) { '(OI)(CI)' } else { '' }
    $grants = @("*${script:AclSystem}:${inherit}F", "*${script:AclAdministrators}:${inherit}F")
    if ($Entry.Grant -and $ServiceAccount -like 'NT SERVICE\*') { $grants += "${ServiceAccount}:${inherit}$($Entry.Grant)" }
    $grants
}

function Test-ALPathWithin([string]$Path, [string]$Root) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $full -ieq $base -or $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-ALAclApproved([string]$Path, [string[]]$ApprovedRoots) {
    if (-not $ApprovedRoots -or $ApprovedRoots.Count -eq 0) { Stop-AL 'ACL changes require explicit -ApprovedAclRoot application-owned roots.' }
    if (-not [IO.Path]::IsPathRooted($Path) -or (Test-ALAclForbidden $Path)) { Stop-AL "Refusing ACL changes at system location or relative path $Path." }
    foreach ($root in $ApprovedRoots) {
        if (-not [IO.Path]::IsPathRooted($root) -or (Test-ALAclForbidden $root)) { Stop-AL 'Approved ACL roots must be dedicated absolute application folders, never system locations.' }
        Test-ALPathTree $root
    }
    if (-not @($ApprovedRoots | Where-Object { Test-ALPathWithin $Path $_ }).Count) { Stop-AL "ACL path $Path is outside the explicitly approved application roots." }
    Test-ALPathTree $Path
}

# The sole ACL-inventory exception: the configured source releases/current junction. Never traverse it.
function Get-ALReleaseJunction([string]$ReleasesRoot, [string[]]$ApprovedRoots = @()) {
    Test-ALPathTree $ReleasesRoot
    $path = Join-AL $ReleasesRoot 'current'
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return $null }
    if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.LinkType -cne 'Junction' -or @($item.Target).Count -ne 1) {
        Stop-AL 'The configured releases/current must be a directory junction, not another link or ordinary directory.'
    }
    $raw = [string]@($item.Target)[0]
    if (-not [IO.Path]::IsPathRooted($raw) -or $raw -match '(^|[\\/])\.\.?([\\/]|$)') { Stop-AL 'Release junction target must be an absolute physical release path.' }
    $target = [IO.Path]::GetFullPath($raw).TrimEnd('\', '/')
    $root = [IO.Path]::GetFullPath($ReleasesRoot).TrimEnd('\', '/')
    if ((Split-Path $target) -cne $root -or (Split-Path $target -Leaf) -ieq 'current') { Stop-AL 'Release junction target must be a direct physical release inside the configured releases root.' }
    Test-ALPathTree $target
    if (-not (Test-Path -LiteralPath $target -PathType Container) -or
        -not (Test-Path -LiteralPath (Join-AL $target 'build-manifest.json') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-AL $target 'server') -PathType Container)) { Stop-AL 'Release junction target is missing or is not a release directory.' }
    $null = @(Get-ALTreeFiles $target) # reject links anywhere in the physical target, including empty directory links
    if ($ApprovedRoots.Count) {
        Assert-ALAclApproved $target $ApprovedRoots
        $exact = @($ApprovedRoots | Where-Object {
            $approved = [IO.Path]::GetFullPath($_).TrimEnd('\', '/')
            $target -ceq $approved -or $target.StartsWith($approved + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)
        })
        if (-not $exact.Count) { Stop-AL 'Junction target must match the exact spelling of an approved physical root.' }
    }
    [pscustomobject]@{ path = [IO.Path]::GetFullPath($path); target = $target }
}

function Test-ALAclPhysicalPath([string]$Path) {
    # Existing objects only. Use the native filesystem API rather than two PowerShell providers per ancestor.
    # Every ancestor is still checked on every use; missing objects, access errors and links fail closed.
    $physical = [IO.Path]::GetFullPath($Path)
    while ($physical) {
        if ([IO.File]::GetAttributes($physical) -band [IO.FileAttributes]::ReparsePoint) { Stop-AL 'Installation paths must not traverse reparse points.' }
        $physical = [IO.Path]::GetDirectoryName($physical)
    }
}

function Get-ALAclItems([string]$Path, [string]$ReleasesRoot = '') {
    Test-ALAclPhysicalPath $Path
    $item = Get-Item -LiteralPath $Path -Force
    $progress = Get-Variable AclProgress -Scope Script -ErrorAction SilentlyContinue
    if ($progress) {
        $progress.Value.walkProcessed++
        Write-ALAclProgress $progress.Value.phase $progress.Value.walkProcessed 0 $progress.Value.stage
    }
    $item
    if (-not $item.PSIsContainer) { return }
    foreach ($child in Get-ChildItem -LiteralPath $Path -Force | Sort-Object FullName) {
        if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            if (-not $ReleasesRoot -or $child.FullName -cne [IO.Path]::GetFullPath((Join-AL $ReleasesRoot 'current'))) { Stop-AL 'Unexpected reparse point in ACL inventory.' }
            if (-not (Get-ALReleaseJunction $ReleasesRoot)) { Stop-AL 'Expected release junction disappeared during ACL inventory.' }
            continue
        }
        Get-ALAclItems $child.FullName $ReleasesRoot
    }
}

function Get-ALAclSnapshot([string]$Path, [string]$ReleasesRoot = '') {
    $count = 0
    Write-ALAclProgress 'inventory' -Stage $Path
    $items = @(Get-ALAclItems $Path $ReleasesRoot)
    foreach ($item in $items) {
        [pscustomobject]@{ path = $item.FullName; dacl = (Get-Acl -LiteralPath $item.FullName).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) }
        Write-ALAclProgress 'snapshot' (++$count) $items.Count $Path
    }
    Write-ALAclProgress 'snapshot' $count $items.Count $Path -Force
}

function Start-ALAclProgress {
    $script:AclProgress = @{ clock = [Diagnostics.Stopwatch]::StartNew(); last = -10.0; phase = ''; stage = ''; phaseStart = 0.0; walkProcessed = 0
        journal = ''; mutation_started = $false }
}

function Get-ALAclOperationStatus([string]$Backup) {
    Test-ALAclPhysicalPath $Backup
    $journal = Join-AL $Backup 'acl-operation.jsonl'
    $manifest = [IO.File]::Exists((Join-AL $Backup 'acl-backup.json'))
    if (-not [IO.File]::Exists($journal)) {
        return [pscustomobject]@{ phase = 'legacy_unknown'; incomplete = $true; last_record_truncated = $false
            manifest_present = $manifest; application_changes_may_have_started = $true; last_event = $null }
    }
    Test-ALAclPhysicalPath $journal
    $lines = [IO.File]::ReadAllLines($journal); $last = $null; $truncated = $false; $mayHaveChanged = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        try { $event = $lines[$i] | ConvertFrom-Json -ErrorAction Stop }
        catch { if ($i -ne $lines.Count - 1) { Stop-AL 'ACL journal is corrupt; retain all artifacts for manual review.' }; $truncated = $true; break }
        if (-not $event.PSObject.Properties['phase'] -or -not $event.PSObject.Properties['mutation_started']) { Stop-AL 'ACL journal event is invalid.' }
        if ($event.mutation_started) { $mayHaveChanged = $true }
        $last = $event
    }
    [pscustomobject]@{ phase = $(if ($last) { $last.phase } else { 'unknown' }); incomplete = ($truncated -or -not $last -or $last.phase -ne 'complete')
        last_record_truncated = $truncated; manifest_present = $manifest
        application_changes_may_have_started = ($mayHaveChanged -or -not $last -or $truncated); last_event = $last }
}

# Host output never contaminates the JSON result. A flushed append-only journal survives a killed process;
# its last complete event is a checkpoint, not permission to resume an interrupted operation.
function Write-ALAclProgress([string]$Phase, [int]$Processed = 0, [int]$Total = 0, [string]$Stage = '', [switch]$Force) {
    $variable = Get-Variable AclProgress -Scope Script -ErrorAction SilentlyContinue
    if (-not $variable) { return }
    $state = $variable.Value
    $elapsed = $state.clock.Elapsed.TotalSeconds
    if ($state.phase -ne $Phase -or $state.stage -ne $Stage) { $state.phaseStart = $elapsed; $state.walkProcessed = 0; $Force = $true }
    if (-not $Force -and $elapsed - $state.last -lt 5) { return }
    $state.phase = $Phase; $state.stage = $Stage; $state.last = $elapsed
    $duration = $elapsed - $state.phaseStart
    $eta = if ($Total -gt $Processed -and $Processed -ge 100 -and $duration -ge 5) { [math]::Round($duration * ($Total - $Processed) / $Processed, 1) } else { $null }
    $event = [ordered]@{ at = [DateTime]::UtcNow.ToString('o'); phase = $Phase; stage = $Stage; processed = $Processed
        total = $(if ($Total) { $Total } else { $null }); elapsed_seconds = [math]::Round($elapsed, 1); eta_seconds = $eta
        mutation_started = $state.mutation_started }
    Write-ALLog ("ACL {0}: {1}/{2} objects; elapsed={3}s; ETA={4}; stage={5}" -f $Phase, $Processed, $(if ($Total) { $Total } else { '?' }),
        $event.elapsed_seconds, $(if ($null -eq $eta) { 'unknown' } else { "${eta}s" }), $Stage)
    if ($state.journal) {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($event | ConvertTo-Json -Compress) + "`n")
        $stream = [IO.File]::Open($state.journal, 'Append', 'Write', 'Read')
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    }
}

function Save-ALAclInventory($Snapshot, [string]$Parent, [string]$File) {
    # Preserve icacls' UTF-16 path/SDDL format, but do not start a process to read a DACL we already captured.
    # Re-read and compare each physical object before publishing; no recursive native save or overwrite.
    $relativeOffset = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/').Length + 1
    $part = "$File.part"
    if ([IO.File]::Exists($File)) { Stop-AL 'ACL recovery file already exists; nothing was overwritten.' }
    $stream = [IO.File]::Open($part, 'CreateNew', 'Write', 'None')
    $writer = [IO.StreamWriter]::new($stream, [Text.Encoding]::Unicode)
    $count = 0; $total = @($Snapshot).Count
    try {
        foreach ($item in $Snapshot) {
            Test-ALAclPhysicalPath $item.path
            if (-not (Test-ALPathWithin $item.path $Parent)) { Stop-AL 'ACL inventory escapes its saved parent.' }
            if ($item.path.IndexOfAny([char[]]"`r`n") -ge 0) { Stop-AL 'ACL inventory paths cannot contain line breaks.' }
            $current = (Get-Acl -LiteralPath $item.path).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)
            if (-not (Test-ALDaclEqual $item.dacl $current)) { Stop-AL 'ACL save differs from its inventory; application permissions are unchanged.' }
            $writer.WriteLine($item.path.Substring($relativeOffset)); $writer.WriteLine($item.dacl)
            Write-ALAclProgress 'backup' (++$count) $total (Split-Path $File -Leaf)
        }
        $writer.Flush(); $stream.Flush($true)
    } finally { $writer.Dispose() }
    [IO.File]::Move($part, $File)
    Write-ALAclProgress 'backup' $count $total (Split-Path $File -Leaf) -Force
}

function Assert-ALAclRecordTree($Entry, [string[]]$ApprovedRoots) {
    Write-ALAclProgress 'physical_validation' -Stage $Entry.path
    $context = if ($Entry.PSObject.Properties['releases_root']) { $Entry.releases_root } else { '' }
    if ($context) {
        Assert-ALAclApproved $context $ApprovedRoots
        $actual = Get-ALReleaseJunction $context $ApprovedRoots
        $expected = $Entry.junction
        if (($actual | ConvertTo-Json -Compress) -cne ($expected | ConvertTo-Json -Compress)) { Stop-AL 'Release junction binding changed since the ACL backup; nothing further may be modified.' }
    }
    $null = @(Get-ALAclItems $Entry.path $context)
}

# File-only reset: opening the final object as a reparse point lets us reject links on the handle.
# Directory resets retain icacls /L: SetSecurityInfo on a directory can propagate permissions recursively.
function Reset-ALAclFile([string]$Path) {
    Test-ALAclPhysicalPath $Path
    if (-not ('AuthLens.NativeFileAcl' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace AuthLens {
    public static class NativeFileAcl {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
        [StructLayout(LayoutKind.Sequential)] struct Tag { public uint Attributes; public uint ReparseTag; }
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int kind, out Tag tag, uint size);
        [DllImport("advapi32.dll")]
        static extern uint SetSecurityInfo(SafeFileHandle handle, int kind, uint flags, IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);
        public static void Reset(string path) {
            // WRITE_DAC | READ_CONTROL, share read/write/delete, OPEN_EXISTING, OPEN_REPARSE_POINT.
            using (var file = CreateFileW(path, 0x60000, 7, IntPtr.Zero, 3, 0x00200000, IntPtr.Zero)) {
                if (file.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
                Tag tag;
                if (!GetFileInformationByHandleEx(file, 9, out tag, 8)) throw new Win32Exception(Marshal.GetLastWin32Error());
                if ((tag.Attributes & (0x400U | 0x10U)) != 0) throw new InvalidOperationException("ACL reset requires an ordinary physical file.");
                // A real empty ACL, NEVER a null DACL. Windows supplies the parent's inheritable ACEs.
                var acl = new byte[] { 2, 0, 8, 0, 0, 0, 0, 0 };
                var pin = GCHandle.Alloc(acl, GCHandleType.Pinned);
                try {
                    uint error = SetSecurityInfo(file, 1, 0x20000004, IntPtr.Zero, IntPtr.Zero, pin.AddrOfPinnedObject(), IntPtr.Zero);
                    if (error != 0) throw new Win32Exception((int)error);
                } finally { pin.Free(); }
            }
        }
    }
}
'@
    }
    [AuthLens.NativeFileAcl]::Reset([IO.Path]::GetFullPath($Path))
}

function Assert-ALAclRequiredAccess([string]$Path) {
    $rules = @(Get-ALAclRules $Path)
    foreach ($sid in $script:AclSystem, $script:AclAdministrators) {
        if (@($rules | Where-Object { $_.Sid -eq $sid -and -not $_.Allow -and -not $_.InheritOnly }).Count -or
            -not @($rules | Where-Object { $_.Sid -eq $sid -and $_.Allow -and -not $_.InheritOnly -and ($_.Rights -band 0x1F01FF) -eq 0x1F01FF }).Count) {
            Stop-AL "Required SYSTEM/Administrators full control is not verified at $Path."
        }
    }
}

function Test-ALProvisioningAncestor([string]$Path) {
    foreach ($rule in @(Get-ALAclRules $Path)) {
        if ($rule.Allow -and -not $rule.InheritOnly -and (Test-ALBroadSid $rule.Sid) -and
            ($rule.Rights -band (64 + 65536 + 262144 + 524288 + 1073741824 + 268435456))) { return $false }
    }
    $true
}

# One native create operation supplies the DACL. No inheritance-then-protect window and no overwrite on a raced path.
function Test-ALDaclEqual([string]$Expected, [string]$Actual) {
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

function New-ALDirectoryWithAcl([string]$Path, $Security) {
    if ([IO.Path]::DirectorySeparatorChar -ne '\') { Stop-AL 'Secure provisioning requires Windows NTFS.' }
    if (-not $Security.AreAccessRulesProtected) { Stop-AL 'Secure creation requires a protected DACL.' }
    Test-ALPathTree $Path
    if ([IO.DriveInfo]::new([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))).DriveFormat -ne 'NTFS') { Stop-AL 'Secure provisioning requires local NTFS.' }
    if (-not (Test-ALProvisioningAncestor (Split-Path $Path))) { Stop-AL 'The provisioning parent permits broad replacement or ACL changes; choose a protected application backup/provisioning root.' }
    if (-not ('AuthLens.NativeDirectory' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace AuthLens {
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
    $errorCode = [AuthLens.NativeDirectory]::Create($Path, $Security.GetSecurityDescriptorBinaryForm())
    if ($errorCode) { Stop-AL "Exclusive secure directory creation failed at $Path (Windows error $errorCode). Nothing was overwritten." }
    Test-ALPathTree $Path
    $access = [Security.AccessControl.AccessControlSections]::Access
    if (-not (Test-ALDaclEqual $Security.GetSecurityDescriptorSddlForm($access) (Get-Acl -LiteralPath $Path).GetSecurityDescriptorSddlForm($access))) {
        Stop-AL "Created directory security differs at $Path; no sensitive file may be written." 4
    }
}

# A protected DACL: inheritance removed, SYSTEM and Administrators full control (Windows only; tests replace it).
function New-ALProtectedDirectorySecurity {
    $security = [Security.AccessControl.DirectorySecurity]::new()
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sid in $script:AclSystem, $script:AclAdministrators) {
        $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid), 'FullControl',
            [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))
    }
    $security
}

function New-ALSecureDirectory([string]$Path, [string[]]$ApprovedRoots, [switch]$Exclusive) {
    Assert-ALAclApproved $Path $ApprovedRoots
    if (Test-Path -LiteralPath $Path) {
        if ($Exclusive) { Stop-AL 'An existing directory is never merged or overwritten.' }
        Assert-ALAclRequiredAccess $Path
        $audit = Get-ALAclAudit $Path 'private' 'secure provisioning'
        if ($audit.findings.Count) { Stop-AL "Existing application path $Path is insecure; explicit ACL remediation is required." }
        return
    }
    $parent = Split-Path $Path
    if (-not (Test-Path -LiteralPath $parent)) { New-ALSecureDirectory $parent $ApprovedRoots }
    New-ALDirectoryWithAcl $Path (New-ALProtectedDirectorySecurity)
    Assert-ALAclRequiredAccess $Path
    if ((Get-ALAclAudit $Path 'private' 'secure provisioning').findings.Count) { Stop-AL 'Secure provisioning verification failed; no sensitive file may be written.' }
}

# Saves the ACLs (with descendants) of every path that will change into a new protected backup folder, then applies protected DACLs: inheritance
# removed, explicit broad grants removed, SYSTEM/Administrators/service grants set, and descendants reset to inherit (their explicit grants are in
# the backup). Missing paths are left to Initialize-ALInstallation. ProgramData, Program Files, the Windows folder, user roots and drive roots
# are refused. The running service keeps its access (SYSTEM, or its own grant), so nothing is stopped.
function Invoke-ALProtectAcl($Config, [string]$BackupRoot, [string[]]$ApprovedRoots) {
    Start-ALAclProgress
    try {
    Write-ALAclProgress 'validate' -Stage 'approved roots and physical inventory'
    $serviceAccount = $Config.ServiceAccount
    $plan = @(Get-ALAclPlan $Config)
    # Validate the entire scope before creating even the ACL backup folder.
    Assert-ALAclApproved $BackupRoot $ApprovedRoots
    foreach ($entry in $plan) {
        Assert-ALAclApproved $entry.Path $ApprovedRoots; Test-ALPathTree $entry.Path
        if (Test-ALPathOverlap $entry.Path $BackupRoot) { Stop-AL 'ACL backup storage must be disjoint from every affected application tree; supply a dedicated -AclBackupRoot.' }
    }
    foreach ($entry in $plan) {
        if (Test-Path -LiteralPath $entry.Path) {
            Write-ALAclProgress 'validate' -Stage $entry.Path
            $context = if ($entry.Role -in @('releases', 'configuration folder')) { $Config.ReleasesRoot } else { '' }
            if ($context) { $null = Get-ALReleaseJunction $context $ApprovedRoots }
            $null = @(Get-ALAclItems $entry.Path $context)
        }
    }
    Write-ALAclProgress 'audit' -Stage 'initial policy'
    $report = Get-ALAclReport $plan
    $changes = @(foreach ($entry in $plan) {
        $row = @($report.entries | Where-Object { $_.path -eq $entry.Path -and $_.role -eq $entry.Role })[0]
        if (-not $row.exists -or ($row.findings.Count -eq 0 -and $row.required_access_verified)) { continue }
        [pscustomobject]@{ Entry = $entry; BroadSids = @($row.findings | ForEach-Object sid | Sort-Object -Unique) }
    })
    if (-not $changes.Count) { Write-ALAclProgress 'complete' -Stage 'no changes required'; return [pscustomobject]@{ changed = @(); backup = $null; after = $report } }
    $backup = Join-AL $BackupRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N'))
    New-ALSecureDirectory $backup $ApprovedRoots
    $script:AclProgress.journal = Join-AL $backup 'acl-operation.jsonl'
    # Exclusive journal creation: old or incomplete recovery artifacts are never reused.
    $journalStream = [IO.File]::Open($script:AclProgress.journal, 'CreateNew', 'Write', 'Read'); $journalStream.Dispose()
    Write-ALAclProgress 'backup' -Stage 'operation created' -Force
    $records = [Collections.Generic.List[object]]::new(); $index = 0
    foreach ($change in $changes) {
        $path = $change.Entry.Path
        $context = if ($change.Entry.Role -in @('releases', 'configuration folder')) { $Config.ReleasesRoot } else { '' }
        $junction = if ($context) { Get-ALReleaseJunction $context $ApprovedRoots } else { $null }
        $snapshot = @(Get-ALAclSnapshot $path $context)
        # The root is approved above; inventory walks only physical descendants of that root.
        foreach ($item in $snapshot) { if (-not (Test-ALPathWithin $item.path $path)) { Stop-AL 'ACL inventory escapes its approved root.' } }
        $file = Join-AL $backup ('{0:D2}.acl' -f ++$index)
        Save-ALAclInventory $snapshot (Split-Path $path) $file
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-Item -LiteralPath $file).Length -eq 0) { Stop-AL 'ACL backup was not written; application permissions are unchanged.' }
        $record = [pscustomobject]@{ path = $path; created = $false; file = $file; parent = (Split-Path $path)
            sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash; snapshot = $snapshot; releases_root = $context; junction = $junction }
        Test-ALAclBackupFile $record
        $records.Add($record)
    }
    $manifestBytes = [Text.Encoding]::UTF8.GetBytes(([pscustomobject]@{ schema = 2; entries = $records.ToArray() } | ConvertTo-Json -Depth 8))
    $manifestPart = Join-AL $backup 'acl-backup.json.part'
    $manifestStream = [IO.File]::Open($manifestPart, 'CreateNew', 'Write', 'None')
    try { $manifestStream.Write($manifestBytes, 0, $manifestBytes.Length); $manifestStream.Flush($true) } finally { $manifestStream.Dispose() }
    [IO.File]::Move($manifestPart, (Join-AL $backup 'acl-backup.json'))
    Write-ALAclProgress 'backups_complete' -Stage 'all inventories and manifest flushed' -Force
    $script:AclProgress.mutation_started = $true
    Write-ALAclProgress 'remediation' -Stage 'before first application ACL change' -Force
    foreach ($change in $changes) {
        $path = $change.Entry.Path
        $record = @($records | Where-Object path -eq $path)[0]
        Assert-ALAclRecordTree $record $ApprovedRoots
        $isContainer = (Get-Item -LiteralPath $path -Force).PSIsContainer
        Invoke-ALIcacls (@($path, '/L', '/inheritance:r', '/grant:r') + @(Get-ALAclGrants $change.Entry $serviceAccount $isContainer))
        $broad = @(@($script:BroadSids.Keys) + @($change.BroadSids) | Sort-Object -Unique | ForEach-Object { "*$_" })
        Invoke-ALIcacls (@($path, '/L', '/remove:g') + $broad)
        if ($change.Entry.Class -eq 'binaries' -and $change.Entry.Role -ne 'configuration') {
            Invoke-ALIcacls @($path, '/L', '/grant:r', "*S-1-5-11:$(if ($isContainer) { '(OI)(CI)' })RX")
        }
        if ($isContainer -and $change.Entry.Recurse) {
            $children = @($record.snapshot | Where-Object path -ne $path | Sort-Object { $_.path.Length }, path)
            $processed = 0
            foreach ($child in $children) {
                Test-ALAclPhysicalPath $child.path
                if ([IO.File]::GetAttributes($child.path) -band [IO.FileAttributes]::Directory) {
                    Invoke-ALIcacls @($child.path, '/reset', '/L', '/C', '/Q')
                } else { Reset-ALAclFile $child.path }
                Write-ALAclProgress 'remediation' (++$processed) $children.Count $path
            }
            Write-ALAclProgress 'remediation' $processed $children.Count $path -Force
        }
        Assert-ALAclRequiredAccess $path
    }
    try {
        foreach ($record in $records) { if (-not $record.created) { Assert-ALAclRecordTree $record $ApprovedRoots } }
    } catch { Stop-AL "ACL verification detected changed tree/junction state; retain $backup for manual review." 4 }
    Write-ALAclProgress 'verification' -Stage 'final policy and physical tree'
    $after = Get-ALAclReport (Get-ALAclPlan $Config)
    if (-not $after.safe) { Stop-AL "ACL remediation verification failed; retain $backup for reviewed restoration." 1 }
    Write-ALAclProgress 'complete' -Stage 'verified' -Force
    [pscustomobject]@{ changed = @($changes | ForEach-Object { $_.Entry.Path }); backup = $backup; after = $after }
    } catch {
        try { Write-ALAclProgress 'failed' -Stage 'retain recovery artifacts; manual review required' -Force } catch { Write-Warning 'ACL journal update failed; retain the operation directory for manual review.' }
        throw
    } finally { Remove-Variable AclProgress -Scope Script -ErrorAction SilentlyContinue }
}

function Invoke-ALRestoreAcl([string]$Backup, [string[]]$ApprovedRoots) {
    Start-ALAclProgress
    try {
    Write-ALAclProgress 'restore_validation' -Stage 'all backup inventories before first change'
    Assert-ALAclApproved $Backup $ApprovedRoots
    Test-ALPathTree $Backup
    if ((Get-ALAclAudit $Backup 'private' 'ACL backup' -Recurse).findings.Count) { Stop-AL 'ACL backup storage is not private; review it before restoration.' }
    if (-not (Test-Path -LiteralPath (Join-AL $Backup 'acl-backup.json') -PathType Leaf)) { Stop-AL 'This is not an ACL backup.' }
    $saved = Get-Content -LiteralPath (Join-AL $Backup 'acl-backup.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.schema -ne 2) { Stop-AL 'This ACL backup lacks verified schema-2 inventories; retain it for reviewed manual restoration.' }
    $entries = @($saved.entries); [Array]::Reverse($entries)
    if (-not $entries.Count) { Stop-AL 'The ACL backup contains no inventories.' }
    # Check every record before restoring the first one, including the saved file and inventory scope.
    foreach ($entry in $entries) {
        Assert-ALAclApproved $entry.path $ApprovedRoots; Test-ALPathTree $entry.path
        if ($entry.created) { continue }
        Assert-ALAclRecordTree $entry $ApprovedRoots
        if ($entry.parent -ne (Split-Path $entry.path) -or (Split-Path $entry.file) -ne $Backup) { Stop-AL 'ACL backup paths do not match their reviewed scope.' }
        Test-ALPathTree $entry.file
        if (-not (Test-Path -LiteralPath $entry.file -PathType Leaf) -or (Get-FileHash -LiteralPath $entry.file -Algorithm SHA256).Hash -ne $entry.sha256) { Stop-AL 'ACL backup is missing or its checksum differs; nothing was restored.' }
        foreach ($item in @($entry.snapshot)) {
            if ($item.path -ne $entry.path -and -not (Test-ALPathWithin $item.path $entry.path)) { Stop-AL 'ACL inventory escapes its saved root.' }
            Test-ALAclPhysicalPath $item.path
        }
        Test-ALAclBackupFile $entry
    }
    $script:AclProgress.journal = Join-AL $Backup ('acl-restore-' + [guid]::NewGuid().ToString('N') + '.jsonl')
    $journalStream = [IO.File]::Open($script:AclProgress.journal, 'CreateNew', 'Write', 'Read'); $journalStream.Dispose()
    $script:AclProgress.mutation_started = $true
    Write-ALAclProgress 'restoration' -Stage 'before first saved DACL replay' -Force
    foreach ($entry in $entries) {
        if ($entry.created) { continue }
        Assert-ALAclRecordTree $entry $ApprovedRoots
        Invoke-ALIcacls @($entry.parent, '/restore', $entry.file, '/L', '/C', '/Q')
        $processed = 0
        foreach ($item in @($entry.snapshot)) {
            Test-ALAclPhysicalPath $item.path
            if (-not (Test-Path -LiteralPath $item.path) -or
                (Get-Acl -LiteralPath $item.path).GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) -cne $item.dacl) {
                Stop-AL 'Restored ACL inventory differs; manual recovery is required.' 4
            }
            Write-ALAclProgress 'restore_verification' (++$processed) @($entry.snapshot).Count $entry.path
        }
        Write-ALAclProgress 'restore_verification' $processed @($entry.snapshot).Count $entry.path -Force
    }
    try {
        foreach ($entry in $entries) { if (-not $entry.created) { Assert-ALAclRecordTree $entry $ApprovedRoots } }
    } catch { Stop-AL 'Restored ACL tree/junction state changed; manual recovery is required.' 4 }
    Write-ALAclProgress 'complete' -Stage 'restoration verified' -Force
    [pscustomobject]@{ verified = $true; restored = @($entries | Where-Object { -not $_.created } | ForEach-Object path)
        kept_created = @($entries | Where-Object created | ForEach-Object path) }
    } catch {
        try { Write-ALAclProgress 'failed' -Stage 'retain recovery artifacts; manual review required' -Force } catch { Write-Warning 'ACL restore journal update failed; retain all recovery artifacts.' }
        throw
    } finally { Remove-Variable AclProgress -Scope Script -ErrorAction SilentlyContinue }
}

# icacls /save stores UTF-16 path/DACL pairs. Validate their destinations as well as the file checksum before invoking /restore.
function Test-ALAclBackupFile($Entry) {
    $lines = [IO.File]::ReadAllLines($Entry.file, [Text.Encoding]::Unicode)
    if (-not $lines.Count -or $lines.Count % 2 -ne 0 -or $lines.Count / 2 -ne @($Entry.snapshot).Count) { Stop-AL 'ACL backup inventory format differs.' }
    $seen = @{}
    $expected = @{}
    foreach ($item in $Entry.snapshot) {
        if ($expected.ContainsKey($item.path)) { Stop-AL 'Duplicate ACL inventory path.' }
        $expected[$item.path] = $item.dacl
    }
    for ($i = 0; $i -lt $lines.Count; $i += 2) {
        if ([IO.Path]::IsPathRooted($lines[$i])) { Stop-AL 'ACL backup contains an absolute restore path.' }
        $full = [IO.Path]::GetFullPath((Join-AL $Entry.parent $lines[$i]))
        if (-not (Test-ALPathWithin $full $Entry.path) -or -not $expected.ContainsKey($full) -or $seen.ContainsKey($full)) { Stop-AL 'ACL backup restore paths escape or differ from the saved inventory.' }
        if (-not (Test-ALDaclEqual $expected[$full] $lines[$i + 1])) { Stop-AL 'ACL backup DACL differs from its saved inventory.' }
        $seen[$full] = $true
    }
}
