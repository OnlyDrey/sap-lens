<#
.SYNOPSIS
  Read-only Windows App Control diagnostics for the Go + Python experiment. Collects evidence; never changes, disables or weakens any policy.
.DESCRIPTION
  Lists active App Control policies (CiTool, read-only), reads Code Integrity events 3076 (audit), 3077 (blocked) and 3033 (signing level) for a bounded
  time window, keeps those whose file lies below the runtime tree or is the host executable, and for each file records the SHA-256, size and Authenticode
  state. Each blocked file is assigned to the stage where it failed: host, interpreter, native extension or other component. A missing signature is recorded
  but is never treated as proof of a block, and a signature is never treated as a guarantee of acceptance.
.EXAMPLE
  powershell -NoProfile -File .\Get-AppControlDiagnostics.ps1 -RuntimeDir C:\poc\runtime -HostExe C:\poc\saplens-host.exe -SinceMinutes 30 -OutDir C:\poc\evidence
#>
param(
    [Parameter(Mandatory = $true)][string]$RuntimeDir,
    [string]$HostExe,
    [int]$SinceMinutes = 60,
    [string]$OutDir
)
. (Join-Path $PSScriptRoot 'Phase1Common.ps1')
if ($env:OS -ne 'Windows_NT') { Write-Host 'NOT EXECUTED: Code Integrity evidence exists only on Windows.'; exit 3 }
if ($SinceMinutes -lt 1 -or $SinceMinutes -gt 1440) { throw 'SinceMinutes must be 1..1440 (bounded query).' }
$RuntimeDir = (Resolve-Path -LiteralPath $RuntimeDir).Path.TrimEnd('\')
$to = Get-Date; $from = $to.AddMinutes(-$SinceMinutes)
$query = Get-CodeIntegrityRecords $from $to
$below = @(Select-RuntimeIntegrityRecords $query.Records $RuntimeDir $from $to)
$hostRecords = @()
if ($HostExe) {
    $hostDir = Split-Path ((Resolve-Path -LiteralPath $HostExe).Path) -Parent; $leaf = Split-Path $HostExe -Leaf
    $hostRecords = @(Select-RuntimeIntegrityRecords $query.Records $hostDir $from $to | Where-Object { $_.Relative -eq $leaf } | ForEach-Object { $_.Relative = "host:$($_.Relative)"; $_ })
}
$userProfile = $env:USERPROFILE
$rows = @()
foreach ($record in @($below) + @($hostRecords)) {
    $isHost = $record.Relative.StartsWith('host:')
    $kind = 'executable'; if (-not $isHost) { $kind = Get-FileKind $record.Relative }
    $stage = 'other_component'
    if ($isHost) { $stage = 'host' } elseif ($kind -eq 'interpreter') { $stage = 'interpreter' } elseif (@('native_extension', 'dll') -contains $kind) { $stage = 'extension' }
    $class = Get-FailureClass $(if ($stage -eq 'other_component') { 'application' } else { $stage }) $null '' @($record) @{ ExitCode = 1 }
    $path = $null
    if ($isHost) { $path = (Resolve-Path -LiteralPath $HostExe).Path } else { $path = Join-Path $RuntimeDir ($record.Relative -replace '/', '\') }
    $image = $null; if (Test-Path -LiteralPath $path -PathType Leaf) { $image = Get-ImageRecord $path $record.Relative.Replace('host:', '') }
    $rows += [ordered]@{ event_id = $record.Id; enforced = $record.Enforced; policy_id = $record.PolicyId; file = $record.Relative; stage = $stage; classification = $class.Class
                         sha256 = $(if ($image) { $image.sha256 } else { $null }); size = $(if ($image) { $image.size } else { $null }); signature = $(if ($image) { $image.signature } else { $null }); signer = $(if ($image) { $image.signer } else { $null }) }
}
$report = [ordered]@{ schema = 1; recorded_utc = (Get-Date).ToUniversalTime().ToString('o'); window_minutes = $SinceMinutes; policies = (Get-ActivePolicyListing); limitations = $query.Limitations;
                      enforced_blocks = @($rows | Where-Object { $_.enforced }).Count; audit_only = @($rows | Where-Object { -not $_.enforced }).Count; records = $rows
                      interpretation = 'A signature is necessary but not sufficient. Audit-only (3076) records mean the file would be blocked under enforcement. No record does not prove acceptance when the log is unavailable (see limitations).' }
$json = ($report | ConvertTo-Json -Depth 8)
if ($userProfile) { $json = $json.Replace($userProfile.Replace('\', '\\'), '%USERPROFILE%') }
if ($OutDir) { New-Item -ItemType Directory -Force $OutDir | Out-Null; [System.IO.File]::WriteAllText((Join-Path $OutDir 'app-control-diagnostics.json'), $json, (New-Object System.Text.UTF8Encoding($false))) }
Write-Host $json
if ($report.enforced_blocks -gt 0) { exit 2 } else { exit 0 }
