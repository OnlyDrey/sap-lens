# Phase 1 Windows feasibility: shared, side-effect-free helpers. Dot-sourced by the harness and by the Linux logic self-test.
# Nothing here changes policy, registry, services or files outside paths the caller passes in. Pure functions take data, so they run on any
# platform with PowerShell (PowerShell 5.1 compatible: no ternary, no &&, no -AsHashtable).
$ErrorActionPreference = 'Stop'

# Constants are functions, not script-scoped variables: scripts run in-process by Run-Phase1.ps1 have their own script scope and would not see them.
function Get-ValidStatuses { return @('PASS', 'FAIL', 'BLOCKED', 'NOT EXECUTED', 'HARNESS ERROR') }
# ERROR_ACCESS_DISABLED_BY_POLICY, ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION: the only native codes treated as policy refusal (same rule as the product's evidence tooling).
function Get-PolicyBlockCodes { return @(1260, 4551) }

function New-StageResult([string]$Id, [string]$Status, [string]$Detail, $Evidence) {
    if ((Get-ValidStatuses) -notcontains $Status) { throw "Invalid status '$Status'" }
    return [ordered]@{ id = $Id; status = $Status; detail = $Detail; evidence = $Evidence }
}

function Get-OverallVerdict($Stages) {
    # HARNESS ERROR outranks everything (the results cannot be trusted). BLOCKED outranks FAIL: a refused file means nothing about the application was
    # verified. Any NOT EXECUTED stage prevents an overall PASS.
    $statuses = @($Stages | ForEach-Object { $_.status })
    if ($statuses -contains 'HARNESS ERROR') { return 'HARNESS ERROR' }
    if ($statuses.Count -eq 0 -or @($statuses | Where-Object { $_ -ne 'NOT EXECUTED' }).Count -eq 0) { return 'NOT EXECUTED' }
    if ($statuses -contains 'BLOCKED') { return 'BLOCKED' }
    if ($statuses -contains 'FAIL') { return 'FAIL' }
    if ($statuses -contains 'NOT EXECUTED') { return 'INCOMPLETE' }
    return 'PASS'
}

function ConvertTo-RelativeKey([string]$Path, [string]$Root) {
    # Whole-path comparison against a root, tolerant of the \Device\HarddiskVolumeN form Code Integrity reports. Returns the relative path or $null.
    if (-not $Path) { return $null }
    $p = $Path
    foreach ($prefix in @('\??\', '\\?\')) { if ($p.StartsWith($prefix)) { $p = $p.Substring($prefix.Length) } }
    $r = $Root.TrimEnd('\')
    $device = [regex]::Match($p, '^\\Device\\HarddiskVolume\d+(\\.*)$')
    if ($device.Success -and $r -match '^[A-Za-z]:\\') { $p = 'X:' + $device.Groups[1].Value; $r = 'X:' + $r.Substring(2) }
    $prefix = $r + '\'
    if ($p.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return $p.Substring($prefix.Length).Replace('\', '/') }
    return $null
}

function Select-RuntimeIntegrityRecords($Records, [string]$Root, [datetime]$From, [datetime]$To) {
    # Records: hashtables {Id, Time, File, PolicyId}. Keeps 3076 (audit), 3077 (blocked) and 3033 (signing level) inside the window and below the runtime root.
    $kept = @()
    foreach ($record in @($Records)) {
        if (@(3076, 3077, 3033) -notcontains [int]$record.Id) { continue }
        if ($record.Time -lt $From -or $record.Time -gt $To) { continue }
        $relative = ConvertTo-RelativeKey $record.File $Root
        if ($null -eq $relative) { continue }
        $kept += @{ Id = [int]$record.Id; Relative = $relative; PolicyId = $record.PolicyId; Enforced = ([int]$record.Id -ne 3076) }
    }
    return $kept
}

function Get-FileKind([string]$Relative) {
    $lower = $Relative.ToLowerInvariant()
    if ($lower -eq 'python/python.exe' -or $lower -eq 'python/pythonw.exe') { return 'interpreter' }
    if ($lower.EndsWith('.pyd')) { return 'native_extension' }
    if ($lower.EndsWith('.dll')) { return 'dll' }
    if ($lower.EndsWith('.exe')) { return 'executable' }
    return 'other'
}

function Get-FailureClass([string]$Stage, $NativeErrorCode, [string]$ExceptionName, $IntegrityRecords, $Context) {
    # Stage: host | interpreter | extension | application | installer. Returns @{ Class; Evidence }.
    # Never classifies by translated message text. A block needs a documented native code or an enforced Code Integrity record for the file in question.
    $enforced = @($IntegrityRecords | Where-Object { $_.Enforced })
    $audit = @($IntegrityRecords | Where-Object { -not $_.Enforced })
    $byCode = ($null -ne $NativeErrorCode) -and ((Get-PolicyBlockCodes) -contains [int]$NativeErrorCode)
    switch ($Stage) {
        'host' {
            if ($byCode -or ($enforced | Where-Object { (Get-FileKind $_.Relative) -eq 'executable' -and $_.Relative -like '*saplens-host*' })) { return @{ Class = 'executable_blocked_by_policy'; Evidence = 'native_code_or_event' } }
            if ($null -ne $NativeErrorCode) { return @{ Class = 'executable_start_failure_unclassified'; Evidence = "native_code_$NativeErrorCode" } }
            return @{ Class = 'ok'; Evidence = 'process_created' }
        }
        'interpreter' {
            if ($byCode -or ($enforced | Where-Object { (Get-FileKind $_.Relative) -eq 'interpreter' -or $_.Relative -like 'python/python3*.dll' })) { return @{ Class = 'interpreter_blocked'; Evidence = 'native_code_or_event' } }
            if ($null -ne $NativeErrorCode) { return @{ Class = 'interpreter_start_failure_unclassified'; Evidence = "native_code_$NativeErrorCode" } }
            if ($Context.ExitCode -ne 0) { return @{ Class = 'application_startup_failure'; Evidence = "interpreter_exit_$($Context.ExitCode)" } }
            return @{ Class = 'ok'; Evidence = 'interpreter_ran' }
        }
        'extension' {
            $hit = @($enforced | Where-Object { @('native_extension', 'dll') -contains (Get-FileKind $_.Relative) })
            if ($hit.Count -gt 0) { return @{ Class = 'native_extension_blocked'; Evidence = ($hit | ForEach-Object { $_.Relative }) -join ',' } }
            if ($Context.ExitCode -eq 0) { return @{ Class = 'ok'; Evidence = 'import_succeeded' } }
            if ($ExceptionName -eq 'ModuleNotFoundError') { return @{ Class = 'missing_dependency'; Evidence = 'ModuleNotFoundError' } }
            if ($ExceptionName -eq 'ImportError') {
                # A DLL load failure without an enforced event is NOT proof of a policy block (missing runtime DLL, bad search path, audit-only record).
                $note = 'ImportError without enforced Code Integrity record'
                if ($audit.Count -gt 0) { $note = 'ImportError with audit-only (3076) record: would be blocked, was allowed' }
                return @{ Class = 'native_load_failure_unclassified'; Evidence = $note }
            }
            return @{ Class = 'application_startup_failure'; Evidence = "exception_$ExceptionName" }
        }
        'application' {
            if ($enforced.Count -gt 0) { return @{ Class = 'blocked_component_during_startup'; Evidence = ($enforced | ForEach-Object { $_.Relative }) -join ',' } }
            return @{ Class = 'application_startup_failure'; Evidence = 'no_enforced_integrity_record' }
        }
        'installer' { return @{ Class = 'installer_failure'; Evidence = 'out_of_scope_for_phase1_no_installer_exists' } }
    }
    throw "Unknown stage '$Stage'"
}

function Get-PydModuleNames([string[]]$RelativePaths) {
    # python/Lib/site-packages/pkg/_x.cp312-win_amd64.pyd -> pkg._x ; top-level modules map to their own name. Only site-packages extensions are probed.
    $names = @()
    foreach ($path in $RelativePaths) {
        $m = [regex]::Match($path.Replace('\', '/'), '^python/Lib/site-packages/(.+?)\.(?:cp\d+-win_amd64|pyd|abi3)(?:\.pyd)?$')
        if (-not $m.Success) { continue }
        $name = ($m.Groups[1].Value -replace '\.(cp\d+-win_amd64|abi3)$', '') -replace '/', '.'
        if ($name -match '^[A-Za-z_][A-Za-z0-9_.]*$') { $names += $name }
    }
    return @($names | Sort-Object -Unique)
}

function Find-Secret([string]$Secret, [string[]]$Haystacks) {
    # Returns the indexes of haystacks that contain the secret. The secret is never returned or printed.
    $found = @()
    if (-not $Secret -or $Secret.Length -lt 16) { return $found }
    for ($i = 0; $i -lt $Haystacks.Count; $i++) { if ($Haystacks[$i] -and $Haystacks[$i].Contains($Secret)) { $found += $i } }
    return $found
}

function Test-ManifestIntegrity([string]$Root) {
    # Recomputes SHA-256 of every file against manifest.json (the same record Phase 0 writes). Returns problems; empty means intact.
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $problems = @(); $seen = @{}
    foreach ($entry in $manifest.files) {
        if ($entry.type -ne 'file') { continue }
        $seen[$entry.path] = $true
        $full = Join-Path $Root ($entry.path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { $problems += "missing: $($entry.path)"; continue }
        if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { $problems += "changed: $($entry.path)" }
    }
    $rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -File -Force) {
        $relative = $file.FullName.Substring($rootFull.Length + 1).Replace('\', '/')
        if ($relative -ne 'manifest.json' -and -not $seen.ContainsKey($relative)) { $problems += "unexpected: $relative" }
    }
    return $problems
}

function Get-ImageRecord([string]$FullPath, [string]$Relative) {
    $signature = Get-AuthenticodeSignature -LiteralPath $FullPath
    $subject = ''
    if ($signature.SignerCertificate) { $subject = $signature.SignerCertificate.Subject }
    return [ordered]@{ path = $Relative; kind = (Get-FileKind $Relative); size = (Get-Item -LiteralPath $FullPath).Length; sha256 = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256).Hash.ToLowerInvariant();
                       signature = [string]$signature.Status; signer = $subject }
}

function Get-SignatureInventory([string]$Root) {
    # Read-only: SHA-256, size and Authenticode state for every executable image. Absence of a signature is recorded, never treated as a block.
    $rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $rows = @()
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Where-Object { @('.exe', '.dll', '.pyd') -contains $_.Extension.ToLowerInvariant() }) {
        $relative = $file.FullName.Substring($rootFull.Length + 1).Replace('\', '/')
        $rows += Get-ImageRecord $file.FullName $relative
    }
    return $rows
}

function Invoke-LoopbackRequest([string]$Url, [hashtable]$Headers, [string]$HostHeader, [int]$TimeoutMs = 5000) {
    # No proxy, no redirects, bounded. Returns @{ Status; Body }; Status 0 means no HTTP response.
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Proxy = $null; $request.AllowAutoRedirect = $false; $request.Timeout = $TimeoutMs; $request.ReadWriteTimeout = $TimeoutMs
    if ($HostHeader) { $request.Host = $HostHeader }
    foreach ($key in $Headers.Keys) { $request.Headers.Add($key, [string]$Headers[$key]) }
    try { $response = $request.GetResponse() } catch [System.Net.WebException] { $response = $_.Exception.Response; if (-not $response) { return @{ Status = 0; Body = '' } } }
    try {
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $body = $reader.ReadToEnd(); $reader.Dispose()
        return @{ Status = [int]$response.StatusCode; Body = $body }
    } finally { $response.Close() }
}

function Get-CodeIntegrityRecords([datetime]$From, [datetime]$To) {
    # Windows only, read-only, bounded. Returns @{ Records; Limitations }. A missing log or right is a limitation, never an error and never proof of no block.
    $limitations = @(); $records = @()
    try {
        $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-CodeIntegrity/Operational'; Id = @(3076, 3077, 3033); StartTime = $From; EndTime = $To } -MaxEvents 256 -ErrorAction Stop)
        if ($events.Count -eq 256) { $limitations += 'Event query limit reached; evidence may be incomplete.' }
        foreach ($event in $events) {
            [xml]$xml = $event.ToXml(); $fields = @{}
            foreach ($field in $xml.Event.EventData.Data) { $name = ([string]$field.Name -replace '[^A-Za-z0-9]', '').ToLowerInvariant(); if ($name) { $fields[$name] = [string]$field.'#text' } }
            $policy = 'not recorded'
            foreach ($key in @('policyid', 'policyguid')) { if ($fields.ContainsKey($key) -and $fields[$key]) { $policy = $fields[$key]; break } }
            $records += @{ Id = [int]$event.Id; Time = $event.TimeCreated; File = [string]$fields['filename']; PolicyId = $policy }
        }
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { $limitations += "Code Integrity log unavailable ($($_.Exception.GetType().Name))." }
    }
    return @{ Records = $records; Limitations = $limitations }
}

function Get-ActivePolicyListing {
    # Read-only. CiTool is present on Windows 11 and recent Windows 10 servicing; absence is recorded, not an error. Output is parsed into counts and IDs only.
    $tool = Join-Path $env:SystemRoot 'System32\CiTool.exe'
    if (-not (Test-Path -LiteralPath $tool)) { return @{ Available = $false; Detail = 'CiTool.exe not present' } }
    try {
        $text = (& $tool --list-policies -json 2>&1 | Out-String)
        $parsed = $text | ConvertFrom-Json
        $items = @($parsed.Policies | ForEach-Object { [ordered]@{ id = $_.PolicyID; name = $_.FriendlyName; enforced = $_.IsEnforced; signed = $_.IsSignedPolicy; base = $_.IsOnDisk } })
        return @{ Available = $true; Count = $items.Count; Policies = $items }
    } catch { return @{ Available = $true; Detail = "CiTool query failed ($($_.Exception.GetType().Name)); elevation may be required" } }
}

function Get-ProcessTable { return @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop) }

function Get-Descendants($Table, [int]$RootId) {
    $ids = @($RootId); $queue = @($RootId)
    while ($queue.Count -gt 0) {
        $current = $queue[0]; $queue = @($queue | Select-Object -Skip 1)
        foreach ($child in @($Table | Where-Object { $_.ParentProcessId -eq $current })) { $ids += [int]$child.ProcessId; $queue += [int]$child.ProcessId }
    }
    return $ids
}


# ---- Phase 1 runner support: pure, testable on any platform --------------------------------------------------------------------------------------------

function Get-SumsLinePattern { return '^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9_.\-/]*)$' }
function Get-RequiredBundleFiles { return @('saplens-host.exe', 'runtime.tar.gz', 'scripts/Run-Phase1.ps1', 'scripts/Test-WindowsFeasibility.ps1', 'scripts/Get-AppControlDiagnostics.ps1',
                                            'scripts/Phase1Common.ps1', 'scripts/Test-Phase1Logic.ps1') }

function ConvertTo-SafeMessage([string]$Text, [int]$Max = 300) {
    # Error text for reports: user profile folder abbreviated, control characters removed, bounded. No environment values, no credentials.
    if (-not $Text) { return '' }
    $clean = $Text
    foreach ($pair in @(@($env:USERPROFILE, '%USERPROFILE%'), @($env:HOME, '%HOME%'))) { if ($pair[0] -and $pair[0].Length -gt 3) { $clean = $clean.Replace($pair[0], $pair[1]) } }
    $clean = [regex]::Replace($clean, '[\x00-\x1f]+', ' ')
    $clean = [regex]::Replace($clean, '(?i)\b(password|passwd|token|secret|api[-_]?key|authorization|capability)\b(\s*[=:]\s*)\S+', '$1$2<redacted>')
    if ($clean.Length -gt $Max) { $clean = $clean.Substring(0, $Max) + '...' }
    return $clean.Trim()
}

function Write-JsonFile([string]$Path, $Object) {
    # Cmdlets only, so it also works in Constrained Language Mode.
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    ($Object | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-BundleSums([string]$Dir, [string]$TrustedSha256) {
    # Verifies a bundle directory against a SEPARATELY SUPPLIED checksum of SHA256SUMS.txt. Returns a list of problems; an empty list means intact.
    # The sums file is not trusted until its own hash matches; only then are its lines parsed, strictly, and every listed file hashed.
    $problems = @()
    $sums = Join-Path $Dir 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $sums -PathType Leaf)) { return @('SHA256SUMS.txt is missing') }
    if ($TrustedSha256 -notmatch '^[0-9a-fA-F]{64}$') { return @('the trusted checksum is not a SHA-256 hex string') }
    if ((Get-FileHash -LiteralPath $sums -Algorithm SHA256).Hash.ToLowerInvariant() -ne $TrustedSha256.ToLowerInvariant()) { return @('SHA256SUMS.txt does not match the trusted checksum') }
    $listed = @{}
    foreach ($line in @(Get-Content -LiteralPath $sums -Encoding ASCII)) {
        if (-not $line) { continue }
        $m = [regex]::Match($line, (Get-SumsLinePattern))
        if (-not $m.Success -or ($m.Groups[2].Value -split '/') -contains '..' -or ($m.Groups[2].Value -split '/') -contains '' -or ($m.Groups[2].Value -split '/') -contains '.') { $problems += "malformed or unsafe SHA256SUMS line: $(ConvertTo-SafeMessage $line 80)"; continue }
        if ($listed.ContainsKey($m.Groups[2].Value)) { $problems += "duplicate entry: $($m.Groups[2].Value)"; continue }
        $listed[$m.Groups[2].Value] = $m.Groups[1].Value
    }
    foreach ($required in (Get-RequiredBundleFiles)) { if (-not $listed.ContainsKey($required)) { $problems += "required file not listed: $required" } }
    $root = (Resolve-Path -LiteralPath $Dir).Path.TrimEnd('\', '/')
    foreach ($relative in @($listed.Keys | Sort-Object)) {
        $full = Join-Path $root ($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
        if (-not $item -or $item.PSIsContainer) { $problems += "missing: $relative"; continue }
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $problems += "link not allowed: $relative"; continue }
        if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant() -ne $listed[$relative]) { $problems += "changed: $relative" }
    }
    foreach ($item in @(Get-ChildItem -LiteralPath $root -Recurse -Force)) {
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $problems += "link not allowed: $($item.Name)"; continue }
        if ($item.PSIsContainer) { continue }
        $relative = $item.FullName.Substring($root.Length + 1).Replace('\', '/')
        if ($relative -ne 'SHA256SUMS.txt' -and -not $listed.ContainsKey($relative)) { $problems += "unexpected file: $relative" }
    }
    return $problems
}

function Get-ArchiveListing([string]$TarPath, [string]$Archive) {
    # Names from `tar -tzf`, entry types from the first character of `tar -tvzf`. Raw exit codes are returned, never masked.
    $names = @(& $TarPath -tzf $Archive); $namesExit = $LASTEXITCODE
    $verbose = @(& $TarPath -tvzf $Archive); $verboseExit = $LASTEXITCODE
    $types = @($verbose | ForEach-Object { if ($_) { ([string]$_).Substring(0, 1) } })
    return @{ Names = $names; Types = $types; NamesExit = $namesExit; VerboseExit = $verboseExit }
}

function Test-ArchiveMembers([string[]]$Names, [string[]]$Types, [string]$Destination, [int]$MaxPath = 259) {
    # Refuses anything that could land outside the extraction directory or behave unexpectedly on Windows. Returns problems; empty means every member is safe.
    $problems = @()
    if ($Names.Count -eq 0) { return @('archive lists no members') }
    if ($Names.Count -ne $Types.Count) { return @('member names and types do not line up') }
    $longest = 0
    for ($i = 0; $i -lt $Names.Count; $i++) {
        $name = [string]$Names[$i]; $type = [string]$Types[$i]
        if (@('-', 'd') -notcontains $type) { $problems += "member type '$type' not allowed (only files and directories): $(ConvertTo-SafeMessage $name 60)"; continue }
        if ($name -match '[\x00-\x1f]') { $problems += 'control character in a member name'; continue }
        if ($name.Contains('\')) { $problems += "backslash in member name: $(ConvertTo-SafeMessage $name 60)"; continue }
        if ($name.Contains(':')) { $problems += "colon (drive or stream) in member name: $(ConvertTo-SafeMessage $name 60)"; continue }
        if ($name.StartsWith('/')) { $problems += "absolute member name: $(ConvertTo-SafeMessage $name 60)"; continue }
        foreach ($segment in ($name.TrimEnd('/') -split '/')) {
            if ($segment -eq '..') { $problems += "path traversal: $(ConvertTo-SafeMessage $name 60)"; break }
            if ($segment -match '^(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$') { $problems += "reserved device name: $(ConvertTo-SafeMessage $name 60)"; break }
            if ($segment -ne '.' -and $segment -match '[. ]$') { $problems += "trailing dot or space: $(ConvertTo-SafeMessage $name 60)"; break }
        }
        if ($name.Length -gt $longest) { $longest = $name.Length }
    }
    if ($Destination -and ($Destination.TrimEnd('\', '/').Length + 1 + $longest) -gt $MaxPath) { $problems += "longest member would exceed $MaxPath characters below the destination; use a shorter work directory" }
    return $problems
}

function Get-OwnedLeftovers($Table, $Owned, [string]$RuntimeDir, [string]$HostExe) {
    # Processes created by THIS run that are still alive. Owned entries are @{ Pid; Start } recorded when each process was created. A process qualifies only if
    #   (a) it is an owned process still alive with the recorded start time, or
    #   (b) its parent is a qualifying or recorded-owned process, it started no earlier than that parent (guards PID reuse) and it runs from the runtime tree or the host file.
    # Nothing is matched by file name alone, so another run, another user or an installed SAP Lens is never selected.
    $rows = @($Table)
    $selected = @{}; $frontier = @()
    $prefix = $RuntimeDir.Replace('/', '\').TrimEnd('\') + '\'
    $under = { param($path) $normal = $(if ($path) { ([string]$path).Replace('/', '\') } else { '' }); $normal -and ($normal.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) -or [string]::Equals($normal, $HostExe.Replace('/', '\'), [System.StringComparison]::OrdinalIgnoreCase)) }
    foreach ($owned in @($Owned)) {
        $row = $rows | Where-Object { [int]$_.ProcessId -eq [int]$owned.Pid -and [math]::Abs(($_.CreationDate - $owned.Start).TotalSeconds) -lt 2 } | Select-Object -First 1
        if ($row) { $selected[[int]$row.ProcessId] = $row }
        $frontier += @{ Pid = [int]$owned.Pid; Start = $owned.Start }
    }
    while ($frontier.Count -gt 0) {
        $parent = $frontier[0]; $frontier = @($frontier | Select-Object -Skip 1)
        foreach ($child in @($rows | Where-Object { [int]$_.ParentProcessId -eq $parent.Pid -and $_.CreationDate -ge $parent.Start.AddSeconds(-1) })) {
            if ($selected.ContainsKey([int]$child.ProcessId) -or -not (& $under $child.ExecutablePath)) { continue }
            $selected[[int]$child.ProcessId] = $child
            $frontier += @{ Pid = [int]$child.ProcessId; Start = $child.CreationDate }
        }
    }
    return @($selected.Values)
}

function Resolve-HarnessOutcome($ExitCode, [string]$JsonPath) {
    # Turns a harness run into ONE classification. A missing, unreadable or inconsistent result is a HARNESS ERROR, never a FAIL and never a PASS.
    $expected = @{ 'PASS' = 0; 'FAIL' = 1; 'BLOCKED' = 2; 'INCOMPLETE' = 3; 'NOT EXECUTED' = 3; 'HARNESS ERROR' = 4 }
    if ($null -eq $ExitCode) { return @{ Status = 'HARNESS ERROR'; Reason = 'the harness did not complete (no exit code)'; Overall = $null } }
    if (-not (Test-Path -LiteralPath $JsonPath -PathType Leaf)) { return @{ Status = 'HARNESS ERROR'; Reason = "result file missing (exit code $ExitCode)"; Overall = $null } }
    try { $result = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return @{ Status = 'HARNESS ERROR'; Reason = "result file unreadable (exit code $ExitCode)"; Overall = $null } }
    $stages = @($result.stages)
    if ($result.schema -ne 1 -or -not $result.overall -or $stages.Count -eq 0) { return @{ Status = 'HARNESS ERROR'; Reason = "result file has an unexpected shape (exit code $ExitCode)"; Overall = $null } }
    foreach ($stage in $stages) { if ((Get-ValidStatuses) -notcontains [string]$stage.status) { return @{ Status = 'HARNESS ERROR'; Reason = "unknown stage status '$($stage.status)'"; Overall = $null } } }
    $recomputed = Get-OverallVerdict @($stages | ForEach-Object { @{ status = [string]$_.status } })
    if ($recomputed -ne [string]$result.overall) { return @{ Status = 'HARNESS ERROR'; Reason = "recorded overall '$($result.overall)' differs from the stages ('$recomputed')"; Overall = [string]$result.overall } }
    if (-not $expected.ContainsKey([string]$result.overall) -or [int]$ExitCode -ne $expected[[string]$result.overall]) { return @{ Status = 'HARNESS ERROR'; Reason = "exit code $ExitCode does not match overall '$($result.overall)'"; Overall = [string]$result.overall } }
    $status = [string]$result.overall; if ($status -eq 'INCOMPLETE') { $status = 'NOT EXECUTED' }
    return @{ Status = $status; Reason = "harness reported $($result.overall) (exit code $ExitCode)"; Overall = [string]$result.overall }
}

function Get-RunExitCode([string]$Status) {
    switch ($Status) { 'PASS' { return 0 } 'FAIL' { return 1 } 'BLOCKED' { return 2 } 'NOT EXECUTED' { return 3 } 'HARNESS ERROR' { return 4 } default { return 4 } }
}

function Get-RunStatus([string]$StopReason, [string]$SelfTest, [string]$Harness, [int]$EnforcedBlocks) {
    # StopReason: set when a precondition or integrity check stopped the run before the harness (nothing was verified). SelfTest and Harness are statuses or $null.
    if ($StopReason) { return 'NOT EXECUTED' }
    if ($SelfTest -and $SelfTest -ne 'PASS') { return 'HARNESS ERROR' }
    if (-not $Harness) { return 'NOT EXECUTED' }
    if ($Harness -eq 'PASS' -and $EnforcedBlocks -gt 0) { return 'HARNESS ERROR' }   # evidence conflict: a block the harness did not notice
    return $Harness
}


function ConvertTo-ArgumentString([string[]]$Arguments) {
    # Windows command-line quoting (CommandLineToArgvW rules): quotes escaped, backslashes before quotes and at the end doubled.
    return (($Arguments | ForEach-Object { if ($_ -match '[\s"]' -or $_ -eq '') { '"' + ($_ -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"' } else { $_ } }) -join ' ')
}

function Invoke-Native([string]$File, [string[]]$Arguments, [int]$TimeoutSeconds, [hashtable]$Environment, [string]$LogPath, [string]$WorkingDirectory, [string]$RuntimeDir, [string]$HostExe) {
    # Starts ONE child process, captures its output and returns its RAW exit code (never remapped). On timeout only this child and the processes this child
    # created (recorded PID and start time, runtime tree or host file) are stopped.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $File; $info.Arguments = ConvertTo-ArgumentString $Arguments; $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    if ($WorkingDirectory) { $info.WorkingDirectory = $WorkingDirectory }
    foreach ($key in @($Environment.Keys)) { $info.EnvironmentVariables[$key] = [string]$Environment[$key] }
    $result = [ordered]@{ Started = $false; ExitCode = $null; TimedOut = $false; Pid = $null; Error = $null; Output = '' }
    try { $p = [System.Diagnostics.Process]::Start($info) } catch { $result.Error = ConvertTo-SafeMessage ("$($_.Exception.GetType().Name): $($_.Exception.Message)"); return $result }
    $result.Started = $true; $result.Pid = $p.Id; $start = $p.StartTime
    $outTask = $p.StandardOutput.ReadToEndAsync(); $errTask = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($TimeoutSeconds * 1000)) {
        $result.TimedOut = $true
        try {
            if ($RuntimeDir -and $HostExe) {
                foreach ($row in @(Get-OwnedLeftovers (Get-ProcessTable) @(@{ Pid = $p.Id; Start = $start }) $RuntimeDir $HostExe)) { if ([int]$row.ProcessId -ne $p.Id) { try { Stop-Process -Id ([int]$row.ProcessId) -Force } catch { } } }
            }
        } catch { }
        try { $p.Kill() } catch { }
        [void]$p.WaitForExit(10000)
    }
    $result.ExitCode = $p.ExitCode
    $text = [string]$outTask.Result + [string]$errTask.Result
    foreach ($pair in @(@($env:USERPROFILE, '%USERPROFILE%'), @($env:HOME, '%HOME%'))) { if ($pair[0] -and $pair[0].Length -gt 3) { $text = $text.Replace($pair[0], $pair[1]) } }
    if ($LogPath) { $text | Set-Content -LiteralPath $LogPath -Encoding UTF8 }
    $result.Output = $text
    return $result
}


# ---- script authorization: Mark-of-the-Web, execution policy and in-process execution -----------------------------------------------------------------------
# Windows asks for confirmation before running a script that carries a Mark-of-the-Web (Zone.Identifier) when the effective policy is Unrestricted, and
# refuses it when the policy is RemoteSigned or stricter. A child PowerShell started with -NonInteractive cannot answer the prompt and fails with
# "AuthorizationManager check failed". The runner therefore runs the bundle's scripts in ITS OWN interactive session, where the standard prompt can be
# answered by the person at the keyboard. Nothing here unblocks files, removes the Mark-of-the-Web, changes the policy or bypasses authorization.

function Get-ZoneIdentifierState([string]$Path) {
    # Read-only. Returns @{ Present = $true/$false/$null (unknown); ZoneId = number or $null }.
    try {
        $stream = Get-Item -LiteralPath $Path -Stream 'Zone.Identifier' -ErrorAction Stop
        $zone = $null
        try { $m = [regex]::Match([string](Get-Content -LiteralPath $Path -Stream 'Zone.Identifier' -Raw -ErrorAction Stop), 'ZoneId=(\d+)'); if ($m.Success) { $zone = [int]$m.Groups[1].Value } } catch { }
        return @{ Present = $true; ZoneId = $zone }
    } catch {
        if ($_.FullyQualifiedErrorId -like 'GetItemNotFound*' -or $_.CategoryInfo.Category -eq 'ObjectNotFound') { return @{ Present = $false; ZoneId = $null } }
        return @{ Present = $null; ZoneId = $null }    # alternate data streams not supported here (non-Windows) or not readable
    }
}

function Get-ScriptAuthorizationAdvice([string]$EffectivePolicy, [int]$MarkedScripts, [bool]$Interactive) {
    # What PowerShell is expected to do with the bundle's scripts. Expectation: none, prompt, refused, prompt-impossible (needs an interactive session).
    $policy = ([string]$EffectivePolicy).ToLowerInvariant()
    if ($policy -eq 'bypass') { return @{ Expectation = 'none'; Message = 'Execution policy Bypass: no authorization prompts (the policy is the organization''s, nothing was changed).' } }
    if ($policy -in @('restricted', 'allsigned')) { return @{ Expectation = 'refused'; Message = "Execution policy $EffectivePolicy refuses unsigned scripts. Nothing can be run without a signature approved by IT; do not work around this." } }
    if ($MarkedScripts -le 0) { return @{ Expectation = 'none'; Message = 'No Mark-of-the-Web on the bundle scripts: no authorization prompts expected.' } }
    if ($policy -eq 'unrestricted') {
        if (-not $Interactive) { return @{ Expectation = 'prompt-impossible'; Message = 'The scripts carry a Mark-of-the-Web and the policy is Unrestricted, so PowerShell must ask for confirmation, but this session is not interactive. Start the runner from an interactive PowerShell window.' } }
        return @{ Expectation = 'prompt'; Message = "PowerShell will ask 'Run once' for each of the $MarkedScripts marked scripts it loads. Answer R for each. Nothing is unblocked." }
    }
    if ($policy -in @('remotesigned', 'undefined')) { return @{ Expectation = 'refused'; Message = "Execution policy $EffectivePolicy refuses scripts that carry a Mark-of-the-Web and are not signed. Obtain the bundle through a channel that does not add it (network share, USB) or ask IT; the runner does not unblock files." } }
    return @{ Expectation = 'none'; Message = "Execution policy ${EffectivePolicy}: no specific expectation." }
}

function Test-SecurityRecord($Record) {
    # Typed detection only (never message text): PowerShell reports an authorization or execution-policy refusal as PSSecurityException / SecurityError.
    if ($null -eq $Record) { return $false }
    $exception = $Record.Exception
    if ($exception -is [System.Management.Automation.PSSecurityException]) { return $true }
    $info = $Record.CategoryInfo
    return ($null -ne $info -and [string]$info.Category -eq 'SecurityError')
}

function Invoke-PhaseScript([string]$Script, [hashtable]$Arguments, [hashtable]$Environment, [string]$LogPath, [string]$ErrorLogPath, [bool]$Echo = $true) {
    # Runs one script of the bundle IN THIS SESSION (call operator; the script's own `exit` returns here with $LASTEXITCODE), with process environment
    # overrides that are restored afterwards. Returns the raw exit code, the captured output, and, for a terminating error, its type, id and message
    # unchanged. Security = the failure was an authorization or execution-policy refusal (typed), which is not a failed assertion.
    $result = [ordered]@{ Started = $false; ExitCode = $null; Security = $false; ErrorType = $null; ErrorId = $null; Error = $null; Output = '' }
    $state = @{ Security = $false; Builder = (New-Object System.Text.StringBuilder) }
    $saved = @{}
    foreach ($key in @($Environment.Keys)) { $saved[$key] = [System.Environment]::GetEnvironmentVariable($key); [System.Environment]::SetEnvironmentVariable($key, [string]$Environment[$key]) }
    $arguments = $Arguments; if ($null -eq $arguments) { $arguments = @{} }
    try {
        $global:LASTEXITCODE = $null
        & $Script @arguments *>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord] -and (Test-SecurityRecord $_)) { $state.Security = $true }
            $line = [string]$_
            [void]$state.Builder.AppendLine($line)
            if ($Echo) { Write-Host $line }
        }
        $result.Started = -not $state.Security
        $result.ExitCode = $global:LASTEXITCODE
    } catch {
        $record = $_
        $result.ErrorType = $record.Exception.GetType().FullName
        $result.ErrorId = [string]$record.FullyQualifiedErrorId
        $result.Error = ConvertTo-SafeMessage ([string]$record.Exception.Message) 1000
        $state.Security = (Test-SecurityRecord $record)
        $result.Started = $false
        if ($ErrorLogPath) { ConvertTo-SafeMessage (($record | Out-String)) 8000 | Set-Content -LiteralPath $ErrorLogPath -Encoding UTF8 }
    } finally {
        foreach ($key in @($saved.Keys)) { $previous = $saved[$key]; if ($null -eq $previous) { $previous = [NullString]::Value }; [System.Environment]::SetEnvironmentVariable($key, $previous) }   # a variable that did not exist is removed again
    }
    $result.Security = $state.Security
    $text = $state.Builder.ToString()
    $result.Output = $text
    if ($LogPath) { $text | Set-Content -LiteralPath $LogPath -Encoding UTF8 }
    return $result
}

function Resolve-ScriptStep($Run, [string]$Name) {
    # One classification for a script step run by Invoke-PhaseScript. Security restrictions are NOT EXECUTED (nothing was verified and nothing failed);
    # anything the tooling did wrong is a HARNESS ERROR. The caller maps a clean exit code further (self-test: 0 = PASS; harness: Resolve-HarnessOutcome).
    if ($Run.Security) { return @{ Status = 'NOT EXECUTED'; Kind = 'security'; Reason = "security restriction: PowerShell did not authorize $Name ($($Run.ErrorType), id $($Run.ErrorId)). This is not a failed assertion. Original message: $($Run.Error)" } }
    if ($Run.ErrorType) { return @{ Status = 'HARNESS ERROR'; Kind = 'error'; Reason = "$Name ended with an unexpected terminating error ($($Run.ErrorType), id $($Run.ErrorId)): $($Run.Error)" } }
    if ($null -eq $Run.ExitCode) { return @{ Status = 'HARNESS ERROR'; Kind = 'noexit'; Reason = "$Name ended without an exit code" } }
    return @{ Status = $null; Kind = 'exit'; Reason = "$Name returned exit code $($Run.ExitCode)" }
}
