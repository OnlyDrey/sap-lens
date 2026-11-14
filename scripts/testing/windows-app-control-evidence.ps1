# Windows App Control (Code Integrity) evidence for native smoke and installer acceptance. Dot-sourced; pure functions that take events and
# paths as data, so they run against synthetic input on any platform with PowerShell. They never change policy and never query the log themselves.
#
# A missing signature is NOT proof of a block. A launch counts as policy-blocked only with (a) a native error code Windows documents as a policy
# refusal, or (b) a Code Integrity event 3077 or 3033 whose file path matches the executable and whose time lies inside the bounded launch window.
$ErrorActionPreference = 'Stop'

# ERROR_ACCESS_DISABLED_BY_POLICY and ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION. Other codes (for example 577, invalid image hash) are not proof.
$script:PolicyBlockCodes = @{ 1260 = 'ERROR_ACCESS_DISABLED_BY_POLICY'; 4551 = 'ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION' }
$script:PolicyIdPattern = '^\{?[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}?$'

function Get-PolicyBlockName($Code) {
    if ($null -eq $Code) { return $null }
    $key = [int]$Code
    if ($script:PolicyBlockCodes.ContainsKey($key)) { return $script:PolicyBlockCodes[$key] }
    return $null
}

function ConvertTo-CodeIntegrityEvent($Event) {
    # Field names differ in spelling and spacing between Windows builds ('FileName', 'File Name'): compare them normalised, never by message text.
    [xml]$xml = $Event.ToXml()
    $fields = @{}
    foreach ($field in $xml.Event.EventData.Data) {
        $name = ([string]$field.Name -replace '[^A-Za-z0-9]', '').ToLowerInvariant()
        if ($name) { $fields[$name] = [string]$field.'#text' }
    }
    $file = [string]$fields['filename']
    if ($file.StartsWith('\??\')) { $file = $file.Substring(4) }
    if ($file.StartsWith('\\?\')) { $file = $file.Substring(4) }
    $policy = 'not recorded'
    foreach ($key in @('policyid', 'policyguid')) {
        if ($fields.ContainsKey($key) -and $fields[$key] -match $script:PolicyIdPattern) { $policy = $fields[$key]; break }
    }
    return @{ Id = [int]$Event.Id; Time = $Event.TimeCreated; File = $file; PolicyId = $policy }
}

function Get-CodeIntegrityPathMatch([string]$File, [string]$Expected, [string]$DevicePath) {
    # Whole-path comparison only, never a file-name or arbitrary suffix match. Returns the correlation kind or $null.
    if (-not $File) { return $null }
    if ([string]::Equals($File, $Expected, [System.StringComparison]::OrdinalIgnoreCase)) { return 'exact_path' }
    if ($DevicePath -and [string]::Equals($File, $DevicePath, [System.StringComparison]::OrdinalIgnoreCase)) { return 'device_path' }
    # Without a drive-to-device mapping (for example when Add-Type is itself restricted) accept the same path below any HarddiskVolume device.
    if ($Expected -match '^[A-Za-z]:(\\.+)$' -and $File -match '^\\Device\\HarddiskVolume\d+(\\.+)$') {
        $rest = $Matches[1]
        if ([string]::Equals($rest, $Expected.Substring(2), [System.StringComparison]::OrdinalIgnoreCase)) { return 'volume_relative_path' }
    }
    return $null
}

function Get-InstallerTempPayloadMatch([string]$File) {
    # Inno Setup extracts the payload to a random 'is-XXXXX.tmp' folder it deletes afterwards, so the exact path cannot be known in advance.
    # The file name AND that folder shape must both match; this is weaker evidence than an exact path and is labelled as such.
    if ($File -match '\\is-[A-Za-z0-9]+\.tmp\\SAP-Lens\.exe$') { return 'installer_temp_payload_pattern' }
    return $null
}

function Select-CorrelatedCodeIntegrityEvents($Events, [string]$ExpectedPath, [string]$DevicePath, [datetime]$From, [datetime]$To, [switch]$InstallerTempPayload) {
    $records = @(); $limitations = @()
    foreach ($event in @($Events)) {
        if ($event.Id -notin @(3077, 3033) -or $event.TimeCreated -lt $From -or $event.TimeCreated -gt $To) { continue }
        try {
            $record = ConvertTo-CodeIntegrityEvent $event
            $kind = Get-CodeIntegrityPathMatch $record.File $ExpectedPath $DevicePath
            if (-not $kind -and $InstallerTempPayload) { $kind = Get-InstallerTempPayloadMatch $record.File }
            if ($kind) { $record.Correlation = $kind; $records += $record }
        } catch { $limitations += "An event could not be parsed ($($_.Exception.GetType().Name))." }
    }
    return @{ Records = $records; Limitations = $limitations }
}

function Get-ExceptionNativeErrorCode($Exception) {
    # Start-Process wraps Win32Exception in PowerShell exceptions; never classify translated messages.
    for ($depth = 0; $Exception -and $depth -lt 12; $depth++) {
        if ($Exception -is [System.ComponentModel.Win32Exception]) { return [int]$Exception.NativeErrorCode }
        $Exception = $Exception.InnerException
    }
    return $null
}

function Get-CodeIntegrityEvents([datetime]$From, [datetime]$To) {
    # Read-only, bounded query. A missing log, a missing right or an empty result is reported as a limitation, never as an error.
    $limitations = @(); $events = @()
    try {
        $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-CodeIntegrity/Operational'; Id = @(3077, 3033); StartTime = $From; EndTime = $To } -MaxEvents 128 -ErrorAction Stop)
        if ($events.Count -eq 128) { $limitations += 'Event query limit reached; evidence may be incomplete.' }
    } catch {
        if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { $limitations += "Code Integrity log unavailable ($($_.Exception.GetType().Name))." }
    }
    return @{ Events = $events; Limitations = $limitations }
}

function ConvertTo-SafeLogTail($Lines, [hashtable]$Replacements, [int]$MaxLines = 25, [int]$MaxLength = 240) {
    # Last lines of an installer log with the user's profile folders abbreviated, long lines cut and credential-looking values removed.
    $kept = @($Lines | Where-Object { $_ -and "$_".Trim() } | Select-Object -Last $MaxLines)
    return @($kept | ForEach-Object {
        $line = [string]$_
        foreach ($key in $Replacements.Keys) { if ($key) { $line = $line.Replace($key, $Replacements[$key]) } }
        $line = [regex]::Replace($line, '(?i)\b(password|passwd|token|secret|api[-_]?key|authorization)\b(\s*[=:]\s*)\S+', '$1$2<redacted>')
        if ($line.Length -gt $MaxLength) { $line = $line.Substring(0, $MaxLength) + '...' }
        $line
    })
}

function Get-NativeSmokeVerdict([string]$FailureClass) {
    # blocked: the operating system refused to run the file, so nothing about the application was verified. failed: everything else.
    if ($FailureClass -eq 'windows_application_control_blocked') { return @{ Status = 'blocked'; Reason = 'environment_policy_blocked' } }
    return @{ Status = 'failed'; Reason = $FailureClass }
}

function Write-NativeResult([string]$Path, [hashtable]$Result) {
    # Machine-readable evidence: no environment variables, tokens or directory names; only the executable's file name.
    $Result.schema = 1
    $Result.recorded_utc = (Get-Date).ToUniversalTime().ToString('o')
    try {
        $directory = Split-Path $Path -Parent
        if ($directory) { New-Item -ItemType Directory -Force $directory | Out-Null }
        [System.IO.File]::WriteAllText($Path, ($Result | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
    } catch { Write-Host "::warning::The native result could not be saved ($($_.Exception.GetType().Name))." }
}

function ConvertTo-EvidenceRecords($Records) {
    return @($Records | ForEach-Object { @{ event_id = $_.Id; policy_id = $_.PolicyId; correlation = $_.Correlation } })
}
