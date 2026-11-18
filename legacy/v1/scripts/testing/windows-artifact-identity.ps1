# Artifact-bound build identity for the Desktop smoke test. Dot-sourced by scripts/test-windows-exe.ps1; pure functions, no side effects.
#
# The identity of an executable is looked up by the SHA-256 of that executable, in a record written by package verification
# (backend/build/artifact-identity/<sha256>.json) or in an explicitly supplied record or Desktop build manifest. The mutable
# backend/build/build-version.json is never consulted: a later Server or Installer build may have rewritten it.

$ErrorActionPreference = 'Stop'

function Resolve-ArtifactIdentity {
    param([Parameter(Mandatory)][string]$ExecutablePath, [string]$IdentityDirectory = '', [string]$IdentityPath = '')
    $hash = (Get-FileHash -LiteralPath $ExecutablePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $sidecar = $ExecutablePath + '.sha256'
    if (Test-Path -LiteralPath $sidecar -PathType Leaf) {
        $expected = $hash + '  ' + (Split-Path $ExecutablePath -Leaf)
        if ((Get-Content -LiteralPath $sidecar -Raw).Trim() -cne $expected) { throw "The executable differs from its checksum file (SHA-256 $hash). The package was changed after verification." }
    }
    $path = if ($IdentityPath) { $IdentityPath } elseif ($IdentityDirectory) { Join-Path $IdentityDirectory ($hash + '.json') } else { '' }
    if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "No build identity is bound to this executable (SHA-256 $hash). Run the Verify stage for this executable (scripts/packaging/verify-windows-package.py) or pass -IdentityPath with its artifact-identity record or manifests/desktop-build-manifest.json. The shared backend/build/build-version.json is not used because another build can overwrite it."
    }
    try { $record = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { throw "The build identity record is not valid JSON: $path" }
    # Two accepted shapes: the artifact-identity record, or the Desktop build manifest of the unified release directory.
    $body = if ($record.PSObject.Properties['build_manifest']) { $record.build_manifest } else { $record }
    if ($null -eq $body -or -not $body.PSObject.Properties['exe_sha256'] -or -not $body.PSObject.Properties['identity']) { throw "The build identity record has no executable checksum or identity: $path" }
    if ([string]$body.exe_sha256 -cne $hash) { throw "The build identity record describes another executable (record $($body.exe_sha256), executable $hash). Nothing was tested." }
    $identity = $body.identity
    $parts = @($identity.file_version)
    if ([string]::IsNullOrWhiteSpace([string]$identity.version) -or $parts.Count -ne 4 -or @($parts | Where-Object { "$_" -notmatch '^\d{1,5}$' }).Count) { throw "The build identity record has no valid product or file version: $path" }
    if ([string]$identity.source_sha -cnotmatch '^[0-9a-f]{40}$') { throw "The build identity record has no valid source commit: $path" }
    return [pscustomobject]@{ Sha256 = $hash; Version = [string]$identity.version; FileVersion = ($parts -join '.'); SourceSha = [string]$identity.source_sha; Path = $path }
}

function Assert-ArtifactVersionResource {
    param([Parameter(Mandatory)]$Identity, [string]$ProductName, [string]$FileVersion, [string]$ProductVersion)
    $differences = @()
    if ($ProductName -cne 'SAP Lens') { $differences += "ProductName '$ProductName' (expected 'SAP Lens')" }
    if ($FileVersion -cne $Identity.FileVersion) { $differences += "FileVersion '$FileVersion' (expected '$($Identity.FileVersion)')" }
    if ($ProductVersion -cne $Identity.Version) { $differences += "ProductVersion '$ProductVersion' (expected '$($Identity.Version)')" }
    if ($differences.Count) { throw ('Windows version metadata differs from the identity bound to this executable: ' + ($differences -join '; ') + '.') }
}
