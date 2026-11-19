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
        [pscustomobject]@{ path = $entry.Path; audited = $audited; role = $entry.Role; class = $entry.Class; exists = (Test-Path -LiteralPath $entry.Path)
            findings = @($audit.findings) }
    }
    $entries = @($entries)
    [pscustomobject]@{ safe = (@($entries | Where-Object { $_.findings.Count -gt 0 }).Count -eq 0); entries = $entries }
}

function Format-SL2AclFindings($Report, [int]$Limit = 6) {
    $lines = foreach ($entry in @($Report.entries)) { foreach ($finding in @($entry.findings)) {
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

# Saves the ACLs (with descendants) of every path that will change into a new protected backup folder, then applies protected DACLs: inheritance
# removed, explicit broad grants removed, SYSTEM/Administrators/service grants set, and descendants reset to inherit (their explicit grants are in
# the backup). Missing target parents are created protected. ProgramData, Program Files, the Windows folder, user roots and drive roots are
# refused. The running service keeps its access (SYSTEM, or its own grant), so nothing is stopped.
function Invoke-SL2ProtectAcl($Source, $Target, [string]$BackupRoot) {
    $serviceAccount = if ($Source) { $Source.ServiceAccount } else { $Target.ServiceAccount }
    $report = Get-SL2AclReport (Get-SL2AclPlan $Source $Target)
    $plan = @(Get-SL2AclPlan $Source $Target)
    $changes = foreach ($entry in $plan) {
        $row = @($report.entries | Where-Object { $_.path -eq $entry.Path -and $_.role -eq $entry.Role })[0]
        $missingParent = $entry.Role -eq 'target parent' -and -not (Test-Path -LiteralPath $entry.Path)
        if ($row.findings.Count -eq 0 -and -not $missingParent) { continue }
        if (Test-SL2AclForbidden $entry.Path) { Stop-SL2 "Refusing to change the ACL of $($entry.Path): it is a system location. Choose a dedicated folder below it." }
        if ($entry.Role -eq 'target parent' -and $row.audited -ne $entry.Path -and -not $missingParent) { continue }
        [pscustomobject]@{ Entry = $entry; Create = $missingParent; BroadSids = @($row.findings | ForEach-Object sid | Sort-Object -Unique) }
    }
    $changes = @($changes)
    if ($changes.Count -eq 0) { return [pscustomobject]@{ changed = @(); backup = $null; after = $report } }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $backup = Join-SL2 $BackupRoot $stamp
    if (Test-Path -LiteralPath $backup) { Stop-SL2 "$backup exists; nothing was changed." }
    New-Item -ItemType Directory -Force $backup | Out-Null
    Invoke-SL2Icacls @($backup, '/inheritance:r', '/grant:r', "*${script:AclSystem}:(OI)(CI)F", "*${script:AclAdministrators}:(OI)(CI)F")
    $records = [System.Collections.Generic.List[object]]::new()
    $index = 0
    foreach ($change in $changes) {
        $path = $change.Entry.Path
        if ($change.Create) { $records.Add([pscustomobject]@{ path = $path; created = $true; file = ''; parent = '' }); continue }
        $file = Join-SL2 $backup ('{0:D2}.acl' -f ++$index)
        $isContainer = (Get-Item -LiteralPath $path -Force).PSIsContainer
        $arguments = @($path, '/save', $file, '/C', '/Q'); if ($isContainer) { $arguments += '/T' }
        Invoke-SL2Icacls $arguments
        $records.Add([pscustomobject]@{ path = $path; created = $false; file = $file; parent = (Split-Path $path) })
    }
    [IO.File]::WriteAllText((Join-SL2 $backup 'acl-backup.json'), ([pscustomobject]@{ schema = 1; created_utc = $stamp; entries = $records.ToArray() } | ConvertTo-Json -Depth 5))
    foreach ($change in $changes) {
        $path = $change.Entry.Path
        if ($change.Create) { New-Item -ItemType Directory -Path $path | Out-Null }
        $isContainer = (Get-Item -LiteralPath $path -Force).PSIsContainer
        Invoke-SL2Icacls (@($path, '/inheritance:r', '/grant:r') + @(Get-SL2AclGrants $change.Entry $serviceAccount $isContainer))
        # Domain Users/Guests are recognized by domain SID pattern, so include the actual audited SIDs too.
        $broad = @(@($script:BroadSids.Keys) + @($change.BroadSids) | Sort-Object -Unique | ForEach-Object { "*$_" })
        Invoke-SL2Icacls (@($path, '/remove:g') + $broad)
        if ($change.Entry.Class -eq 'binaries' -and $change.Entry.Role -ne 'source configuration' -and $change.Entry.Role -ne 'target configuration') {
            Invoke-SL2Icacls @($path, '/grant:r', "*S-1-5-11:$(if ($isContainer) { '(OI)(CI)' })RX")
        }
        if ($isContainer -and $change.Entry.Recurse -and @(Get-ChildItem -LiteralPath $path -Force).Count) {
            Invoke-SL2Icacls @((Join-SL2 $path '*'), '/reset', '/T', '/C', '/Q')
        }
    }
    $after = Get-SL2AclReport (Get-SL2AclPlan $Source $Target)
    [pscustomobject]@{ changed = @($changes | ForEach-Object { $_.Entry.Path }); created = @($changes | Where-Object Create | ForEach-Object { $_.Entry.Path })
        backup = $backup; after = $after }
}

# Restores every ACL saved by Invoke-SL2ProtectAcl (newest change first). Folders it created are kept (empty, protected) and reported.
function Invoke-SL2RestoreAcl([string]$Backup) {
    $record = Join-SL2 $Backup 'acl-backup.json'
    if (-not (Test-Path -LiteralPath $record -PathType Leaf)) { Stop-SL2 "$record is missing; this is not an ACL backup." }
    $saved = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
    if ($saved.schema -ne 1) { Stop-SL2 'Unsupported ACL backup.' }
    $entries = @($saved.entries); [Array]::Reverse($entries)
    foreach ($entry in $entries) {
        if ($entry.created) { continue }
        if (-not (Test-Path -LiteralPath $entry.file -PathType Leaf)) { Stop-SL2 "$($entry.file) is missing; nothing further was restored." 1 }
        Invoke-SL2Icacls @($entry.parent, '/restore', $entry.file, '/C', '/Q')
    }
    [pscustomobject]@{ restored = @($entries | Where-Object { -not $_.created } | ForEach-Object path); kept_created = @($entries | Where-Object created | ForEach-Object path) }
}
