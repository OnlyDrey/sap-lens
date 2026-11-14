# Phase 1 Windows feasibility: shared, side-effect-free helpers. Dot-sourced by the harness and by the Linux logic self-test.
# Nothing here changes policy, registry, services or files outside paths the caller passes in. Pure functions take data, so they run on any
# platform with PowerShell (PowerShell 5.1 compatible: no ternary, no &&, no -AsHashtable).
$ErrorActionPreference = 'Stop'

$script:ValidStatus = @('PASS', 'FAIL', 'BLOCKED', 'NOT EXECUTED')
# ERROR_ACCESS_DISABLED_BY_POLICY, ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION: the only native codes treated as policy refusal (same rule as the product's evidence tooling).
$script:PolicyCodes = @(1260, 4551)

function New-StageResult([string]$Id, [string]$Status, [string]$Detail, $Evidence) {
    if ($script:ValidStatus -notcontains $Status) { throw "Invalid status '$Status'" }
    return [ordered]@{ id = $Id; status = $Status; detail = $Detail; evidence = $Evidence }
}

function Get-OverallVerdict($Stages) {
    # BLOCKED outranks FAIL: a refused file means nothing about the application was verified. Any NOT EXECUTED stage prevents an overall PASS.
    $statuses = @($Stages | ForEach-Object { $_.status })
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
    $byCode = ($null -ne $NativeErrorCode) -and ($script:PolicyCodes -contains [int]$NativeErrorCode)
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
