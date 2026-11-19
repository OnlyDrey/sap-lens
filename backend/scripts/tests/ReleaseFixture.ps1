. (Join-Path $PSScriptRoot 'TestHelpers.ps1')
# Shared release fixtures for the verifier and publication tests: synthetic schema-1 release folders, manifest editing that keeps SHA256SUMS
# consistent, and a verifier runner that keeps the exit code and raw output (Windows PowerShell turns redirected native stderr into ErrorRecords).
$script:Verify = (Resolve-Path (Join-Path $PSScriptRoot '..\verify-release.ps1')).Path

# A complete schema-1 release as build-release.ps1 (win-x64) or build-release.sh (linux-x64) writes it; -Historical is a release built before
# the rename to AuthLens (product "SAP Lens 2", desktop/SapLens2Prototype.exe, a SAP Lens 1 ui_source_version).
function New-VerifiableRelease([string]$Path, [string]$Platform = 'win-x64', [switch]$Historical) {
    $desktopExe = if ($Historical) { 'desktop/SapLens2Prototype.exe' } else { 'desktop/AuthLens.exe' }
    $files = if ($Platform -eq 'win-x64') { @('README.txt', $desktopExe, 'server/AuthLens.Api.exe', 'server/e_sqlite3.dll', 'symbols/server/AuthLens.Api.pdb') } else { @('server/AuthLens.Api', 'server/libe_sqlite3.so') }
    foreach ($relative in $files) { $file = Join-Path $Path $relative; New-Item -ItemType Directory -Force (Split-Path $file) | Out-Null; Set-Content $file $relative }
    $artifacts = foreach ($relative in $files | Sort-Object) {
        $file = Get-Item (Join-Path $Path $relative)
        [ordered]@{ path = $relative; bytes = $file.Length; sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $publish = [ordered]@{ self_contained = $true; single_file = $true; trimmed = $false; native_aot = $false; compressed = $false; server_native_libraries = 'beside the executable' }
    $executables = [ordered]@{ server = $(if ($Platform -eq 'win-x64') { 'server/AuthLens.Api.exe' } else { 'server/AuthLens.Api' }) }
    if ($Platform -eq 'win-x64') { $publish.desktop_native_libraries = 'bundled, extracted to a temporary folder at start'; $executables.desktop = $desktopExe }
    $manifest = [ordered]@{ schema = 1; product = $(if ($Historical) { 'SAP Lens 2' } else { 'AuthLens' }); version = '2.0.0-alpha.1'; channel = 'alpha'; file_version = @(2, 0, 0, 1)
        ui_source_version = $(if ($Historical) { '1.4.0' } else { '2.0.0-alpha.1' }); source_sha = ('a' * 40); source_dirty = $false; source_committed_at = '2026-11-16T09:00:00+00:00'
        branch = 'experiment/dotnet-backend'; build_timestamp_utc = '2026-11-16T10:00:00Z'; target_platform = $Platform; dotnet_sdk = '10.0.100'; node = 'v24.0.0'
        publish = $publish; executables = $executables; artifacts = @($artifacts) }
    Save-Manifest $Path $manifest
}
# Writes the manifest and a SHA256SUMS that covers it and every listed artifact, so a test can change the contract without breaking checksums.
function Save-Manifest([string]$Path, $Manifest) {
    [System.IO.File]::WriteAllText((Join-Path $Path 'build-manifest.json'), ($Manifest | ConvertTo-Json -Depth 5))
    $sums = foreach ($relative in @('build-manifest.json') + @($Manifest.artifacts | ForEach-Object { $_.path } | Where-Object { Test-Path (Join-Path $Path $_) })) {
        '{0}  ./{1}' -f (Get-FileHash (Join-Path $Path $relative) -Algorithm SHA256).Hash.ToLowerInvariant(), $relative }
    [System.IO.File]::WriteAllText((Join-Path $Path 'SHA256SUMS'), (($sums -join "`n") + "`n"))
}
function Edit-Manifest([string]$Path, [scriptblock]$Change) {
    $manifest = Get-Content (Join-Path $Path 'build-manifest.json') -Raw | ConvertFrom-Json
    & $Change $manifest
    Save-Manifest $Path $manifest
}

function Invoke-Verify([string]$Path, [string]$Scope = 'Full') {
    Invoke-TestPowerShell @('-File', $script:Verify, '-ReleasePath', $Path, '-Scope', $Scope)
}

# The folder Publish-ALRelease wrote before deployment-package.json existed: server/, README.txt and the unchanged full-build manifest and sums.
function New-HistoricalPackage([string]$Path) {
    New-VerifiableRelease $Path
    foreach ($tree in 'desktop', 'symbols') { Remove-Item -LiteralPath (Join-Path $Path $tree) -Recurse -Force }
}
