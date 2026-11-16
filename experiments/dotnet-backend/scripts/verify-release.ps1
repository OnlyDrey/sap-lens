<#
.SYNOPSIS
  Verifies a SAP Lens 2 release folder written by build-release.ps1 or build-release.sh: every file listed in build-manifest.json exists with its size and
  SHA-256, no unlisted file was added, and SHA256SUMS matches (it also covers build-manifest.json). Read-only. Exit code 0 valid, 1 invalid.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -ReleasePath C:\saplens2\builds\SAP-Lens-2-...-win-x64
#>
param([Parameter(Mandatory = $true)][string]$ReleasePath)
$ErrorActionPreference = 'Stop'
$problems = New-Object System.Collections.Generic.List[string]
$root = (Resolve-Path -LiteralPath $ReleasePath).ProviderPath.TrimEnd('\', '/')
$manifestPath = Join-Path $root 'build-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { [Console]::Error.WriteLine("verify-release: $manifestPath is missing."); exit 1 }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

$listed = @{}
foreach ($artifact in @($manifest.artifacts)) {
    $listed[$artifact.path] = $true
    $file = Join-Path $root ($artifact.path -replace '/', [System.IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { $problems.Add("missing: $($artifact.path)"); continue }
    if ((Get-Item -LiteralPath $file).Length -ne [long]$artifact.bytes) { $problems.Add("size differs: $($artifact.path)") }
    elseif ((Hash $file) -ne $artifact.sha256) { $problems.Add("checksum differs: $($artifact.path)") }
}
foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File) {
    $relative = $file.FullName.Substring($root.Length + 1).Replace('\', '/')
    if ($relative -notin 'build-manifest.json', 'SHA256SUMS' -and -not $listed.ContainsKey($relative)) { $problems.Add("not in the manifest: $relative") }
}
foreach ($executable in @($manifest.executables.PSObject.Properties | ForEach-Object { $_.Value })) { if (-not $listed.ContainsKey($executable)) { $problems.Add("executable not listed: $executable") } }
$sums = Join-Path $root 'SHA256SUMS'
if (-not (Test-Path -LiteralPath $sums -PathType Leaf)) { $problems.Add('SHA256SUMS is missing') }
else {
    foreach ($line in Get-Content -LiteralPath $sums | Where-Object { $_ }) {
        if ($line -notmatch '^([0-9a-f]{64})  \./(.+)$') { $problems.Add("SHA256SUMS line not understood: $line"); continue }
        $file = Join-Path $root ($Matches[2] -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { $problems.Add("SHA256SUMS lists a missing file: $($Matches[2])") }
        elseif ((Hash $file) -ne $Matches[1]) { $problems.Add("SHA256SUMS checksum differs: $($Matches[2])") }
    }
}
if ($problems.Count -gt 0) {
    foreach ($problem in $problems) { [Console]::Error.WriteLine("verify-release: $problem") }
    exit 1
}
$built = $manifest.build_timestamp_utc
if ($built -is [datetime]) { $built = $built.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }   # PowerShell 7 parses ISO dates
Write-Host "Release verified: $(@($manifest.artifacts).Count) artifacts, commit $($manifest.source_sha), built $built for $($manifest.target_platform)."
exit 0
