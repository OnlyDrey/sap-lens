# Repeatable Windows benchmark. No supplied paths: every operation uses a fresh synthetic repository fixture.
[CmdletBinding()]
param([ValidateRange(1, 10000)][int]$Objects = 100, [switch]$SkipBaseline)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '../deploy/AuthLens.Deploy.psm1') -Force
if ([IO.Path]::DirectorySeparatorChar -ne '\') { throw 'This benchmark requires Windows NTFS.' }
$artifacts = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../build/test-artifacts'))
$run = Join-Path $artifacts ('acl-benchmark-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $run 'synthetic'
[void][IO.Directory]::CreateDirectory($root)
$wall = [Diagnostics.Stopwatch]::StartNew()
Start-Transcript -Path (Join-Path $run 'benchmark.log') | Out-Null
try {
Write-Host "ACL benchmark: Windows $($PSVersionTable.PSVersion); synthetic files=$Objects; fixture=$run"
for ($i = 0; $i -lt $Objects; $i++) {
    $directory = Join-Path $root ('d{0:D2}' -f ($i % 10))
    [void][IO.Directory]::CreateDirectory($directory)
    [IO.File]::WriteAllText((Join-Path $directory "$i.txt"), 'synthetic benchmark data')
}
$timer = [Diagnostics.Stopwatch]::StartNew()
$snapshot = @(Get-ALAclSnapshot $root)
$inventorySeconds = $timer.Elapsed.TotalSeconds
$baselineSave = $null; $baselineReset = $null
if (-not $SkipBaseline) {
    Write-Host 'Stage: 8ee1cc6 per-object native backup baseline'
    # Original algorithm, including the repeated ancestor validation and icacls result comparison.
    $timer.Restart(); $lines = [Collections.Generic.List[string]]::new()
    $file = Join-Path $run 'baseline.acl'
    foreach ($item in $snapshot) {
        Test-ALPathTree $item.path
        Invoke-ALIcacls @($item.path, '/save', "$file.part", '/L', '/C', '/Q')
        $saved = [IO.File]::ReadAllLines("$file.part", [Text.Encoding]::Unicode)
        if ($saved.Count -ne 2 -or -not (Test-ALDaclEqual $item.dacl $saved[1])) { throw 'Baseline backup mismatch.' }
        $lines.Add($item.path.Substring($run.Length + 1)); $lines.Add($saved[1])
    }
    [IO.File]::WriteAllLines($file, $lines.ToArray(), [Text.Encoding]::Unicode)
    $baselineSave = $timer.Elapsed.TotalSeconds
}
Write-Host 'Stage: optimized backup and indexed recovery validation'
$timer.Restart()
$optimized = Join-Path $run 'optimized.acl'
Save-ALAclInventory $snapshot $run $optimized
$optimizedSave = $timer.Elapsed.TotalSeconds
$timer.Restart()
Test-ALAclBackupFile ([pscustomobject]@{ path=$root; parent=$run; file=$optimized; snapshot=$snapshot })
$validationSeconds = $timer.Elapsed.TotalSeconds
$equal = if ($SkipBaseline) { $null } else { [IO.File]::ReadAllText($file) -ceq [IO.File]::ReadAllText($optimized) }
if (-not $SkipBaseline -and -not $equal) { throw 'Optimized backup differs from the baseline.' }
$files = @($snapshot | Where-Object { -not ([IO.File]::GetAttributes($_.path) -band [IO.FileAttributes]::Directory) })
if (-not $SkipBaseline) {
    Write-Host 'Stage: per-file icacls reset baseline (synthetic files only)'
    $timer.Restart()
    foreach ($item in $files) { Test-ALPathTree $item.path; Invoke-ALIcacls @($item.path, '/reset', '/L', '/C', '/Q') }
    $baselineReset = $timer.Elapsed.TotalSeconds
}
Write-Host 'Stage: file-handle native reset (synthetic files only; directory reset is unchanged)'
$timer.Restart()
foreach ($item in $files) { Reset-ALAclFile $item.path }
$optimizedReset = $timer.Elapsed.TotalSeconds
$result = [ordered]@{ files=$files.Count; objects=$snapshot.Count; inventory_seconds=$inventorySeconds
    baseline_backup_seconds=$baselineSave; optimized_backup_seconds=$optimizedSave; backup_byte_equal=$equal
    baseline_backup_processes=$(if ($SkipBaseline) { $null } else { $snapshot.Count }); optimized_backup_processes=0
    indexed_validation_seconds=$validationSeconds; baseline_file_reset_seconds=$baselineReset; optimized_file_reset_seconds=$optimizedReset
    baseline_file_reset_processes=$(if ($SkipBaseline) { $null } else { $files.Count }); optimized_file_reset_processes=0
    fixture=$run; powershell=$PSVersionTable.PSVersion.ToString() }
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'benchmark.json') -Encoding UTF8
Write-Host "Summary: $($result | ConvertTo-Json -Compress)"
Write-Host "Result: Passed | Duration: $($wall.Elapsed) | Exit code: 0. Fixture and measurements retained; no installation paths used."
} finally { Stop-Transcript | Out-Null }
