# Test-only helpers. No production data or service API imports.
$ErrorActionPreference = 'Stop'
$script:ScmHelperFile=$PSCommandPath
function Assert-NoReparse([IO.FileSystemInfo]$Entry) {
    if ($Entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'SCM acceptance refuses reparse points.' }
}
function New-ScmWorkspace([string]$Parent) {
    $parentPath = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $ancestor = Get-Item -LiteralPath $parentPath -Force
    while ($ancestor) { Assert-NoReparse $ancestor; $ancestor = $ancestor.Parent }
    $root = Join-Path $parentPath ('sap-lens-scm-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($owner in @($sid,(New-Object Security.Principal.SecurityIdentifier('S-1-5-18')))) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($owner,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $root -AclObject $acl
    $workspace = @{ Root=$root; Parent=$parentPath; Sid=$sid.Value; Token=[guid]::NewGuid().ToString('N') }
    [IO.File]::WriteAllText((Join-Path $root '.scm-test-owner.json'),($workspace | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    return $workspace
}
function Assert-ScmTestPath($Workspace,[string]$Path) {
    $caller=[Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        if ($caller.User.Value -ne $Workspace.Sid) { throw 'SCM workspace belongs to another caller.' }
    } finally { $caller.Dispose() }
    $root = [IO.Path]::GetFullPath($Workspace.Root).TrimEnd('\')
    if ((Split-Path $root -Leaf) -notmatch '^sap-lens-scm-[a-f0-9]{32}$' -or
        (Split-Path $root -Parent) -ne $Workspace.Parent) { throw 'Invalid SCM workspace boundary.' }
    if (-not [IO.Path]::IsPathRooted($Path)) { throw 'Use an absolute test path.' }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($full -ne $root -and -not $full.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Path is outside the SCM test workspace.' }
    # Preserve per-operation boundary/link checks, avoiding PowerShell provider
    # round-trips for every ancestor of every file.
    $ancestor=$root
    while ($ancestor) {
        if ([IO.File]::GetAttributes($ancestor) -band [IO.FileAttributes]::ReparsePoint) { throw 'SCM acceptance refuses reparse points.' }
        $ancestor=[IO.Path]::GetDirectoryName($ancestor)
    }
    $marker=Join-Path $root '.scm-test-owner.json'
    if ([IO.File]::GetAttributes($marker) -band [IO.FileAttributes]::ReparsePoint) { throw 'SCM acceptance refuses reparse points.' }
    $text=[IO.File]::ReadAllText($marker)
    $proof=$Workspace['_MarkerProof']
    if (-not $proof) {
        $saved=$text | ConvertFrom-Json
        if ($saved.Token -ne $Workspace.Token -or $saved.Root -ne $root -or $saved.Sid -ne $Workspace.Sid) { throw 'SCM workspace ownership marker differs.' }
        $proof=@{Text=$text;Token=$saved.Token;Root=$saved.Root;Sid=$saved.Sid}
        $Workspace['_MarkerProof']=$proof
    }
    if ($text -cne $proof.Text -or $proof.Token -ne $Workspace.Token -or $proof.Root -ne $root -or $proof.Sid -ne $Workspace.Sid) { throw 'SCM workspace ownership marker differs.' }
    $parent=[IO.Path]::GetDirectoryName($full)
    while ($parent -and ($parent -eq $root -or $parent.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase))) {
        try {
            $attributes=[IO.File]::GetAttributes($parent)
            if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'SCM acceptance refuses reparse points.' }
            if (-not ($attributes -band [IO.FileAttributes]::Directory)) { throw 'SCM path parent is not a directory.' }
        } catch [IO.FileNotFoundException] {
            # ZIP members may omit explicit directory entries. Validate existing
            # ancestors without creating anything or skipping higher ancestors.
        } catch [IO.DirectoryNotFoundException] {
            # Missing intermediate parents are legitimate before extraction.
        }
        # Access denied, invalid paths and every other I/O error propagate.
        $parent=[IO.Path]::GetDirectoryName($parent)
    }
    return $full
}
function Grant-ScmTestEntry($Workspace,[IO.FileSystemInfo]$Entry) {
    $path = Assert-ScmTestPath $Workspace $Entry.FullName
    Assert-NoReparse $Entry
    # Only one verified entry at a time. Never /R, /T, wildcard, broad group or production path.
    $global:LASTEXITCODE=1
    & (Join-Path $env:SystemRoot 'System32/takeown.exe') /F $path | Out-Null
    if ($global:LASTEXITCODE -ne 0) { throw 'Test-only ownership recovery failed.' }
    $global:LASTEXITCODE=1
    & (Join-Path $env:SystemRoot 'System32/icacls.exe') $path /grant:r ('*'+$Workspace.Sid+':F') /L /Q | Out-Null
    if ($global:LASTEXITCODE -ne 0) { throw 'Test-only current-user ACL recovery failed.' }
    Assert-NoReparse (Get-Item -LiteralPath $path -Force)
}
function Write-ScmCleanupProgress($Workspace,$State,[switch]$Force) {
    if (-not $Force -and $State.Clock.Elapsed.TotalSeconds-$State.Last -lt 5) { return }
    $State.Last=$State.Clock.Elapsed.TotalSeconds
    $snapshot=@{phase=$State.Phase;elapsed=[int]$State.Clock.Elapsed.TotalSeconds;files=$State.Files;directories=$State.Directories;deleted=$State.Deleted;last=$State.LastPath}
    $path=Join-Path $Workspace.Root '.scm-cleanup-progress.json'
    $null=Assert-ScmTestPath $Workspace $path
    try {
        if ([IO.File]::GetAttributes($path) -band [IO.FileAttributes]::ReparsePoint) { throw 'Cleanup diagnostic must not be a reparse point.' }
    } catch [IO.FileNotFoundException] { } # First checkpoint; all other errors fail closed.
    [IO.File]::WriteAllText($path,($snapshot | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    Write-Host ('[SCM cleanup] '+($snapshot | ConvertTo-Json -Compress))
}
function Remove-ScmWorkspace($Workspace) {
    $state=@{Clock=[Diagnostics.Stopwatch]::StartNew();Last=-5;Phase='validate';Files=0;Directories=0;Deleted=0;LastPath='.'}
    $cleanupDeadline=[DateTime]::UtcNow.AddSeconds(120)
    $root = Assert-ScmTestPath $Workspace $Workspace.Root
    Write-ScmCleanupProgress $Workspace $state -Force
    $pending = New-Object 'System.Collections.Generic.Queue[System.IO.DirectoryInfo]'
    $pending.Enqueue((Get-Item -LiteralPath $root -Force))
    $entries = New-Object 'System.Collections.Generic.List[System.IO.FileSystemInfo]'
    while ($pending.Count) {
        if ([DateTime]::UtcNow -ge $cleanupDeadline) { throw 'Workspace cleanup exceeded 120 seconds; workspace retained.' }
        $directory=$pending.Dequeue()
        $state.Phase='enumerate'; $state.LastPath=$directory.FullName.Substring($root.Length).TrimStart('\')
        Write-ScmCleanupProgress $Workspace $state
        $null=Assert-ScmTestPath $Workspace $directory.FullName
        Assert-NoReparse $directory
        try { $children=@(Get-ChildItem -LiteralPath $directory.FullName -Force -ErrorAction Stop) }
        catch [System.UnauthorizedAccessException] {
            Grant-ScmTestEntry $Workspace $directory
            $children=@(Get-ChildItem -LiteralPath $directory.FullName -Force -ErrorAction Stop)
        }
        foreach ($entry in $children) {
            $null=Assert-ScmTestPath $Workspace $entry.FullName
            Assert-NoReparse $entry
            $entries.Add($entry)
            if ($entry -is [IO.DirectoryInfo]) { $state.Directories++; $pending.Enqueue($entry) } else { $state.Files++ }
            Write-ScmCleanupProgress $Workspace $state
        }
    }
    # Reject the whole tree before deleting anything. Keep the marker until all children are gone.
    $marker=Join-Path $root '.scm-test-owner.json'
    foreach ($entry in @($entries | Sort-Object { $_.FullName.Length } -Descending)) {
        if ([DateTime]::UtcNow -ge $cleanupDeadline) { throw 'Workspace cleanup exceeded 120 seconds; workspace retained.' }
        if ($entry.FullName -eq $marker -or $entry.FullName -eq (Join-Path $root '.scm-cleanup-progress.json')) { continue }
        $state.Phase='delete';$state.LastPath=$entry.FullName.Substring($root.Length+1)
        Write-ScmCleanupProgress $Workspace $state
        Remove-ScmTestEntry $Workspace $entry
        $state.Deleted++

    }
    $null=Assert-ScmTestPath $Workspace $root
    $ownerText=[IO.File]::ReadAllText($marker)
    $rootEntry=Get-Item -LiteralPath $root -Force
    if ($rootEntry.Attributes -band [IO.FileAttributes]::ReadOnly) { $rootEntry.Attributes=$rootEntry.Attributes -band (-bnot [IO.FileAttributes]::ReadOnly) }
    try {
        Remove-Item -LiteralPath (Join-Path $root '.scm-cleanup-progress.json') -Force
        Remove-Item -LiteralPath $marker -Force
        [IO.Directory]::Delete($root,$false)
    } catch {
        $primaryFailure=$_
        try {
            # Root deletion can fail after children were removed. Restore diagnostics
            # only after verifying its ancestor chain again; never follow a link.
            $ancestor=$root
            while ($ancestor) {
                if ([IO.File]::GetAttributes($ancestor) -band [IO.FileAttributes]::ReparsePoint) { throw 'Root recovery refuses reparse points.' }
                $ancestor=[IO.Path]::GetDirectoryName($ancestor)
            }
            if (-not [IO.File]::Exists($marker)) {
                $stream=[IO.File]::Open($marker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
                try { $bytes=[Text.Encoding]::UTF8.GetBytes($ownerText);$stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
            }
            $state.Phase='remove-root';$state.LastPath='.'
            Write-ScmCleanupProgress $Workspace $state -Force
        } catch { Write-Warning 'Unable to restore final cleanup metadata; preserve the failed workspace and console diagnostics.' }
        throw $primaryFailure
    }
}
function Get-SafeScmZipPath([string]$Name) {
    $name=$Name.Replace('\','/')
    if (-not $name -or $name.StartsWith('/') -or $name.Contains(':')) { throw 'Unsafe ZIP path.' }
    $parts=$name.TrimEnd('/').Split('/')
    foreach ($part in $parts) {
        if (-not $part -or $part -in @('.','..') -or $part -match '[. ]$' -or $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') { throw 'Unsafe ZIP path component.' }
    }
    return ($parts -join [IO.Path]::DirectorySeparatorChar)
}
function Copy-ScmBundle([string]$InputPath,$Workspace) {
    $source=Get-Item -LiteralPath $InputPath -Force
    Assert-NoReparse $source
    $ancestor=if ($source -is [IO.DirectoryInfo]) { $source } else { $source.Directory }
    while ($ancestor) { Assert-NoReparse $ancestor; $ancestor=$ancestor.Parent }
    $destination=Join-Path $Workspace.Root 'bundle'
    $null=Assert-ScmTestPath $Workspace $destination
    $requiredFiles=@('manage-server-service.ps1','SAPLensService.exe','app/SAP-Lens.exe','verification-report.json')
    if ($source -is [IO.DirectoryInfo]) {
        foreach ($required in $requiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $source.FullName $required) -PathType Leaf)) { throw "Incomplete service bundle: missing $required." }
        }
        $queue=New-Object 'System.Collections.Generic.Queue[System.IO.DirectoryInfo]'; $queue.Enqueue($source)
        $files=New-Object 'System.Collections.Generic.List[System.IO.FileSystemInfo]'
        while ($queue.Count) {
            $directory=$queue.Dequeue(); Assert-NoReparse $directory
            foreach ($entry in @(Get-ChildItem -LiteralPath $directory.FullName -Force)) {
                Assert-NoReparse $entry; $files.Add($entry)
                if ($entry -is [IO.DirectoryInfo]) { $queue.Enqueue($entry) }
            }
        }
        New-Item -ItemType Directory -Path $destination | Out-Null
        foreach ($entry in $files) {
            $target=Join-Path $destination $entry.FullName.Substring($source.FullName.TrimEnd('\').Length+1)
            if ($entry -is [IO.DirectoryInfo]) { New-Item -ItemType Directory -Path $target -Force | Out-Null }
            elseif ($entry.Name -ne 'SAPLensService.xml') { Copy-Item -LiteralPath $entry.FullName -Destination $target }
        }
    } elseif ($source.Extension -ieq '.zip') {
        # Preserve origin-zone metadata; safe extraction must not implicitly unblock downloaded code.
        $zone=$null
        $streams=@(Get-Item -LiteralPath $source.FullName -Stream '*' -ErrorAction Stop)
        if ($streams | Where-Object { $_.Stream -eq 'Zone.Identifier' }) {
            $zoneStream=[IO.File]::OpenRead($source.FullName+':Zone.Identifier')
            try {
                if ($zoneStream.Length -gt 65536) { throw 'ZIP origin metadata is too large.' }
                $zone=New-Object byte[] ([int]$zoneStream.Length)
                $offset=0
                while ($offset -lt $zone.Length) {
                    $read=$zoneStream.Read($zone,$offset,$zone.Length-$offset)
                    if (-not $read) { throw 'ZIP origin metadata read was interrupted.' }
                    $offset+=$read
                }
            } finally { $zoneStream.Dispose() }
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive=[IO.Compression.ZipFile]::OpenRead($source.FullName)
        try {
            $names=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
            $total=[long]0
            if ($archive.Entries.Count -gt 20000) { throw 'SCM bundle ZIP has too many entries.' }
            foreach ($entry in $archive.Entries) {
                $relative=Get-SafeScmZipPath $entry.FullName
                if (-not $names.Add($relative) -or (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000 -or ($entry.ExternalAttributes -band 0x400)) { throw 'Duplicate or linked ZIP entry.' }
                $total+=$entry.Length
                if ($entry.Length -gt 536870912 -or $total -gt 2147483648) { throw 'SCM bundle ZIP is too large.' }
            }
            foreach ($required in $requiredFiles) {
                if (-not $names.Contains((Get-SafeScmZipPath $required))) { throw "Incomplete service ZIP: missing $required." }
            }
            New-Item -ItemType Directory -Path $destination | Out-Null
            foreach ($entry in $archive.Entries) {
                $target=Join-Path $destination (Get-SafeScmZipPath $entry.FullName)
                $null=Assert-ScmTestPath $Workspace $target
                if ($entry.FullName.Replace('\','/').EndsWith('/')) { New-Item -ItemType Directory -Path $target -Force | Out-Null }
                else {
                    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
                    # The two-argument overload refuses existing files and works on Windows PowerShell 5.1 frameworks.
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target)
                    if ($null -ne $zone) { [IO.File]::WriteAllBytes($target+':Zone.Identifier',$zone) }
                }
            }
        } finally { $archive.Dispose() }
    } else { throw 'Bundle must be an extracted service directory or .zip archive.' }
    foreach ($required in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $destination $required) -PathType Leaf)) { throw "Incomplete service bundle: missing $required." }
    }
    return $destination
}

function Remove-ScmTestEntry($Workspace,[IO.FileSystemInfo]$Entry) {
    $path=Assert-ScmTestPath $Workspace $Entry.FullName
    for ($attempt=0; $attempt -lt 5; $attempt++) {
        $operation='inspect entry'; $attributes='unknown'
        try {
            $current=Get-Item -LiteralPath $path -Force -ErrorAction Stop
            Assert-NoReparse $current
            $operation='inspect attributes'
            $attributes=[int]$current.Attributes
            # FileInfo deletion uses Remove-Item -Force; do not round-trip file
            # attributes through FileInfo.set_Attributes (Windows ERROR_INVALID_PARAMETER).
            if ($current -is [IO.DirectoryInfo] -and ($attributes -band 1)) {
                $operation='clear directory read-only'
                $current.Attributes=[IO.FileAttributes]($attributes -band (-bnot 1))
            }
            $operation='delete entry'

            if ($Entry -is [IO.DirectoryInfo]) { [IO.Directory]::Delete($path,$false) }
            else { Remove-Item -LiteralPath $path -Force -ErrorAction Stop }
            return
        } catch {
            $failureException=$_.Exception
            while ($failureException.InnerException) { $failureException=$failureException.InnerException }
            $code=$failureException.HResult -band 0xffff
            if ($code -notin @(5,32,33) -or $attempt -eq 4) {
                $relative=$path.Substring($Workspace.Root.TrimEnd('\').Length+1)
                throw "SCM cleanup failed: $relative ($($Entry.GetType().Name), code=$code, operation=$operation, attributes=$attributes). Workspace retained."
            }
            if ($code -eq 5) { Grant-ScmTestEntry $Workspace $Entry }
            # Only confirmed access/sharing/lock failures, bounded to 1.5s total backoff.
            Start-Sleep -Milliseconds (100 * [math]::Pow(2,$attempt))
        }
    }
}
function Wait-ScmWorkspaceProcesses($Workspace) {
    $root=Assert-ScmTestPath $Workspace $Workspace.Root
    $deadline=[DateTime]::UtcNow.AddSeconds(15)
    do {
        $active=New-Object 'System.Collections.Generic.List[int]'
        foreach ($process in @(Get-CimInstance Win32_Process -OperationTimeoutSec 5 -ErrorAction Stop)) {
            try {
                if ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) {
                    $active.Add([int]$process.ProcessId)
                }
            } finally { $process.Dispose() }
        }
        if (-not $active.Count) { return }
        if ([DateTime]::UtcNow -ge $deadline) { throw ('Test-owned processes remain (PIDs '+($active -join ',')+'); workspace retained.') }
        Start-Sleep -Milliseconds 250
    } while ($true)
}
function Copy-ScmReplacementBundle([string]$Bundle,$Workspace,$Report) {
    $destination=Join-Path $Workspace.Root 'replacement'
    $null=Assert-ScmTestPath $Workspace $destination
    New-Item -ItemType Directory -Path $destination -ErrorAction Stop | Out-Null
    $names=@('verification-report.json') + @($Report.files.PSObject.Properties.Name)
    $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in $names) {
        $relative=Get-SafeScmZipPath $name
        if (-not $seen.Add($relative)) { throw 'Duplicate replacement manifest path.' }
        $source=Join-Path $Bundle $relative
        $null=Assert-ScmTestPath $Workspace $source
        $entry=Get-Item -LiteralPath $source -Force -ErrorAction Stop
        Assert-NoReparse $entry
        if ($entry.PSIsContainer) { throw "Replacement file is a directory: $relative" }
        if ($name -ne 'verification-report.json' -and
            (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Report.files.PSObject.Properties[$name].Value) { throw "Replacement checksum mismatch: $relative" }
        $target=Join-Path $destination $relative
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target
    }
    return $destination
}

function Write-ScmEvidence([string]$Path,$Receipt) {
    # CreateNew protects earlier acceptance evidence and never follows a pre-existing link.
    $stream=$null; $writer=$null
    try {
        $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($false))
        $writer.Write(($Receipt | ConvertTo-Json -Depth 12)); $writer.Flush(); $stream.Flush($true)
    } finally {
        if ($writer) { $writer.Dispose() } elseif ($stream) { $stream.Dispose() }
    }
    $saved=Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json
    if ($saved.schema -ne 1 -or $saved.kind -ne 'windows-scm' -or $saved.status -ne 'passed' -or
        $saved.package_sha256 -ne $Receipt.package_sha256 -or -not $saved.cleanup_complete -or
        ($saved.identity | ConvertTo-Json -Depth 12 -Compress) -ne ($Receipt.identity | ConvertTo-Json -Depth 12 -Compress)) {
        throw 'SCM evidence read-back validation failed.'
    }
}

function Get-ScmExitCode($Process) {
    if (-not $Process.HasExited) { throw 'Management process has not exited; exit code is unavailable.' }
    $code=$Process.ExitCode
    if ($null -eq $code -or $code -isnot [int]) { throw 'Management process exited without an available integer exit code; acceptance refused.' }
    return $code
}
function Invoke-ScmManagementHost([string]$HostPath,[string]$EncodedCommand,[string]$Stage,[ValidateRange(1,180)][int]$TimeoutSeconds=180,[switch]$StreamProgress) {
    $child=[Diagnostics.Process]::new()
    $stdout=$null; $stderr=$null; $started=$false
    $watch=[Diagnostics.Stopwatch]::StartNew()
    try {
        # Own the original process handle. Start-Process -PassThru on Windows
        # PowerShell 5.1 can return a detached process with unavailable ExitCode.
        $child.StartInfo.FileName=$HostPath
        $child.StartInfo.Arguments='-NoProfile -NonInteractive -EncodedCommand '+$EncodedCommand
        $child.StartInfo.UseShellExecute=$false
        $child.StartInfo.CreateNoWindow=$true
        $child.StartInfo.RedirectStandardOutput=$true
        $child.StartInfo.RedirectStandardError=$true
        if (-not $child.Start()) { throw 'Management host could not be started.' }
        $started=$true
        $null=$child.Handle
        # Drain both pipes concurrently without PowerShell event callbacks.
        $stdout=if ($StreamProgress) { $child.StandardOutput.ReadLineAsync() } else { $child.StandardOutput.ReadToEndAsync() }
        $stderr=$child.StandardError.ReadToEndAsync()
        $lastHeartbeat=-5
        do {
            if ($StreamProgress) {
                while ($stdout -and $stdout.IsCompleted) {
                    $line=$stdout.Result
                    if ($null -eq $line) { $stdout=$null; break }
                    Write-Host $line
                    $stdout=$child.StandardOutput.ReadLineAsync()
                }
            }
            if ($watch.Elapsed.TotalSeconds-$lastHeartbeat -ge 5) {
                Write-Host ('[SCM] RUNNING | '+$Stage+' | elapsed '+[int]$watch.Elapsed.TotalSeconds+'s')
                $lastHeartbeat=$watch.Elapsed.TotalSeconds
            }
            $exited=$child.WaitForExit(250)
        } while (-not $exited -and $watch.Elapsed.TotalSeconds -lt $TimeoutSeconds)
        if (-not $child.HasExited) {
            $child.Kill()
            if (-not $child.WaitForExit(10000)) { throw 'Owned management host did not exit after termination; workspace retained.' }
            throw "Owned management host exceeded $TimeoutSeconds seconds; inspect service state and retained workspace."
        }
        if ($StreamProgress) {
            $drain=[Diagnostics.Stopwatch]::StartNew()
            while ($stdout) {
                $remaining=[math]::Max(0,5000-[int]$drain.ElapsedMilliseconds)
                if (-not $stdout.Wait($remaining)) { throw 'Management output capture did not complete; acceptance refused.' }
                $line=$stdout.Result
                if ($null -eq $line) { $stdout=$null;break }
                Write-Host $line
                $stdout=$child.StandardOutput.ReadLineAsync()
            }
        }
        if (($stdout -and -not $stdout.Wait(5000)) -or -not $stderr.Wait(5000)) { throw 'Management output capture did not complete; acceptance refused.' }
        $exitCode=Get-ScmExitCode $child
        if ($exitCode -ne 0) { throw "Service management failed (exit $exitCode)." }
    } finally {
        if ($started) {
            try {
                if (-not $child.HasExited) {
                    $child.Kill()
                    if (-not $child.WaitForExit(10000)) { Write-Warning 'Owned management process remains after termination; retain workspace.' }
                }
            } catch { Write-Warning 'Unable to confirm owned management process termination; retain workspace.' }
        }
        # Never wait indefinitely for a descendant retaining an inherited pipe.
        foreach ($output in @($stdout,$stderr)) {
            if ($null -ne $output) {
                if ($output.IsCompleted -and -not $output.IsFaulted -and -not $output.IsCanceled) {
                    if ($output.Result) { Write-Host $output.Result }
                } else { Write-Warning 'Management output capture incomplete; inspect retained workspace logs.' }
            }
        }
        $child.Dispose()
    }
}

function Invoke-ScmCleanupWorker($Workspace,[ValidateRange(1,120)][int]$TimeoutSeconds=120) {
    # The watchdog lives outside filesystem traversal: even a blocked filesystem
    # or ACL command is bounded. Only this explicitly created child may be killed.
    $helper=$script:ScmHelperFile
    $values=@('Root','Parent','Sid','Token') | ForEach-Object {
        "'"+$_+"'='"+([string]$Workspace[$_]).Replace("'","''")+"'"
    }
    $code="$"+'ErrorActionPreference=''Stop''; . '+"'"+$helper.Replace("'","''")+"'; "+'$workspace=@{'+($values -join ';')+'}; Remove-ScmWorkspace $workspace'
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
    Invoke-ScmManagementHost (Get-Process -Id $PID).Path $encoded 'workspace cleanup' $TimeoutSeconds -StreamProgress
}
