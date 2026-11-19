<#
.SYNOPSIS
  Verifies a SAP Lens release folder written by build-release.ps1 or build-release.sh: the build-manifest.json contract (schema 1, the same for
  win-x64 and linux-x64 apart from the platform rules below), every listed file with its size and SHA-256, no unlisted file, and SHA256SUMS
  covering every file (build-manifest.json included). Read-only. Exit code 0 valid, 1 invalid.

  Platform rules: win-x64 lists server/SapLens.Api.exe and a desktop executable and describes desktop_native_libraries; linux-x64 lists only
  server/SapLens.Api. Releases built before the rename to SAP Lens (product "SAP Lens 2", desktop/SapLens2Prototype.exe, a SAP Lens 1
  ui_source_version) keep verifying: the migration preflight verifies the release an existing service runs.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -ReleasePath C:\sap-lens\acceptance\builds\SAP-Lens-...-win-x64
#>
param([Parameter(Mandatory = $true)][string]$ReleasePath)
$ErrorActionPreference = 'Stop'
$problems = New-Object System.Collections.Generic.List[string]
$root = (Resolve-Path -LiteralPath $ReleasePath).ProviderPath.TrimEnd('\', '/')
$manifestPath = Join-Path $root 'build-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { [Console]::Error.WriteLine("verify-release: $manifestPath is missing."); exit 1 }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Field([string]$Name) { if ($manifest.PSObject.Properties.Name -contains $Name) { $manifest.$Name } else { $null } }
function Text($Value) { $Value -is [string] -and $Value.Trim().Length -gt 0 }
function Stamp($Value) { $Value -is [datetime] -or ((Text $Value) -and [DateTimeOffset]::TryParse($Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref][DateTimeOffset]::MinValue)) }

# Manifest contract (schema 1).
foreach ($name in 'schema', 'product', 'version', 'channel', 'file_version', 'ui_source_version', 'source_sha', 'source_dirty', 'source_committed_at', 'branch',
    'build_timestamp_utc', 'target_platform', 'dotnet_sdk', 'node', 'publish', 'executables', 'artifacts') {
    if ($manifest.PSObject.Properties.Name -notcontains $name) { $problems.Add("manifest field missing: $name") }
}
if ((Field 'schema') -ne 1) { $problems.Add("manifest schema '$(Field 'schema')' is not 1") }
# "SAP Lens 2" is the product name of releases built before the rename (docs/architecture/VERSIONING.md, naming register).
if ((Field 'product') -notin 'SAP Lens', 'SAP Lens 2') { $problems.Add("manifest product '$(Field 'product')' is not SAP Lens") }
if ("$(Field 'source_sha')" -cnotmatch '^[0-9a-f]{40}$') { $problems.Add("manifest source_sha '$(Field 'source_sha')' is not a 40-character commit id") }
if ((Field 'source_dirty') -isnot [bool]) { $problems.Add('manifest source_dirty is not true or false') }
foreach ($name in 'source_committed_at', 'build_timestamp_utc') { if (-not (Stamp (Field $name))) { $problems.Add("manifest $name is not a timestamp") } }
foreach ($name in 'ui_source_version', 'branch', 'dotnet_sdk', 'node') { if (-not (Text (Field $name))) { $problems.Add("manifest $name is empty") } }
$platform = Field 'target_platform'
$executables = Field 'executables'; $publish = Field 'publish'
$names = if ($executables) { @($executables.PSObject.Properties.Name) } else { @() }
switch ($platform) {
    'win-x64' {
        if ($executables.server -ne 'server/SapLens.Api.exe') { $problems.Add('win-x64: executables.server is not server/SapLens.Api.exe') }
        if ("$($executables.desktop)" -notmatch '^desktop/[^/]+\.exe$') { $problems.Add('win-x64: executables.desktop is missing') }
        if (-not (Text $publish.desktop_native_libraries)) { $problems.Add('win-x64: publish.desktop_native_libraries is missing') }
    }
    'linux-x64' {
        if ($executables.server -ne 'server/SapLens.Api') { $problems.Add('linux-x64: executables.server is not server/SapLens.Api') }
        if ($names -contains 'desktop') { $problems.Add('linux-x64: a Desktop executable is listed; the Desktop is Windows only') }
        if ($publish -and $publish.PSObject.Properties.Name -contains 'desktop_native_libraries') { $problems.Add('linux-x64: publish.desktop_native_libraries is listed') }
    }
    default { $problems.Add("manifest target_platform '$platform' is not win-x64 or linux-x64") }
}
if ($names | Where-Object { $_ -notin 'server', 'desktop' }) { $problems.Add("unknown executables: $(($names | Where-Object { $_ -notin 'server', 'desktop' }) -join ', ')") }
if (-not $publish) { } else {
    foreach ($flag in 'self_contained', 'single_file') { if ($publish.$flag -ne $true) { $problems.Add("publish.$flag is not true") } }
    foreach ($flag in 'trimmed', 'native_aot', 'compressed') { if ($publish.$flag -ne $false) { $problems.Add("publish.$flag is not false") } }
    if (-not (Text $publish.server_native_libraries)) { $problems.Add('publish.server_native_libraries is missing') }
}
$folder = Split-Path -Leaf $root
if ($folder -like 'SAP-Lens-*' -and $platform -and $folder -notlike "*-$platform") { $problems.Add("folder name $folder does not end with the platform $platform") }

# Product version: a valid version, the same in the folder name, and a file version that follows from it.
if ("$($manifest.version)" -notmatch '^(\d+)\.(\d+)\.(\d+)(-(alpha|beta|rc)\.(\d+))?$') { $problems.Add("manifest version '$($manifest.version)' is not MAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N]") }
else {
    $expected = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $(if ($Matches[6]) { [int]$Matches[6] } else { 0 }))
    $channel = if ($Matches[5]) { $Matches[5] } else { 'stable' }
    if ($manifest.PSObject.Properties.Name -contains 'file_version' -and ((@($manifest.file_version) -join '.') -ne ($expected -join '.'))) { $problems.Add("manifest file_version $(@($manifest.file_version) -join '.') does not follow from version $($manifest.version)") }
    if ($manifest.PSObject.Properties.Name -contains 'channel' -and $manifest.channel -ne $channel) { $problems.Add("manifest channel '$($manifest.channel)' does not follow from version $($manifest.version)") }
    $folder = Split-Path -Leaf $root
    if ($folder -like 'SAP-Lens-*' -and $folder -notlike "SAP-Lens-$($manifest.version)-*" -and $folder -notlike "SAP-Lens-2-$($manifest.version)-*") { $problems.Add("folder name $folder does not carry version $($manifest.version)") }
}
$listed = @{}
if (@($manifest.artifacts).Count -eq 0) { $problems.Add('manifest lists no artifacts') }
foreach ($artifact in @($manifest.artifacts)) {
    if (-not (Text $artifact.path) -or $artifact.path -match '(^/|\\|(^|/)\.\.(/|$))' -or $artifact.path -in 'build-manifest.json', 'SHA256SUMS') { $problems.Add("artifact path not allowed: '$($artifact.path)'"); continue }
    if ($listed.ContainsKey($artifact.path)) { $problems.Add("artifact listed twice: $($artifact.path)"); continue }
    if ("$($artifact.sha256)" -cnotmatch '^[0-9a-f]{64}$' -or $artifact.bytes -isnot [ValueType] -or [long]$artifact.bytes -lt 0) { $problems.Add("artifact metadata invalid: $($artifact.path)") }
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
    $summed = @{}
    foreach ($line in Get-Content -LiteralPath $sums | Where-Object { $_ }) {
        if ($line -notmatch '^([0-9a-f]{64})  \./(.+)$') { $problems.Add("SHA256SUMS line not understood: $line"); continue }
        $summed[$Matches[2]] = $true
        $file = Join-Path $root ($Matches[2] -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { $problems.Add("SHA256SUMS lists a missing file: $($Matches[2])") }
        elseif ((Hash $file) -ne $Matches[1]) { $problems.Add("SHA256SUMS checksum differs: $($Matches[2])") }
    }
    foreach ($path in @($listed.Keys) + 'build-manifest.json') { if (-not $summed.ContainsKey($path)) { $problems.Add("SHA256SUMS does not cover $path") } }
}
if ($problems.Count -gt 0) {
    foreach ($problem in $problems) { [Console]::Error.WriteLine("verify-release: $problem") }
    exit 1
}
$built = $manifest.build_timestamp_utc
if ($built -is [datetime]) { $built = $built.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }   # PowerShell 7 parses ISO dates
Write-Host "Release verified: $(@($manifest.artifacts).Count) artifacts, commit $($manifest.source_sha), built $built for $($manifest.target_platform)."
exit 0
