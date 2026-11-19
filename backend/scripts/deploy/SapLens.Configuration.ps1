# Canonical production target policy. Legacy source configurations are read unchanged.
function Get-SL2CanonicalPaths {
    [pscustomobject]@{ WorkRoot = 'C:\sap-lens\deploy'; ReleasesRoot = 'C:\sap-lens\releases'
        DataDirectory = 'C:\ProgramData\sap-lens\data'; BackupRoot = 'C:\ProgramData\sap-lens\predeploy-backups'
        TlsRoot = 'C:\ProgramData\sap-lens\tls' }
}

function Assert-SL2CanonicalTargetLayout($Target) {
    if ($Target.ServiceName -cmatch '^SapLens\.Acceptance-[a-f0-9]{32}-new$') { return }
    if ($Target.ServiceName -cne 'sap-lens') { Stop-SL2 'The production target ServiceName must be sap-lens; use PlanCanonicalTarget to review the conversion.' }
    $paths = Get-SL2CanonicalPaths
    foreach ($name in 'WorkRoot', 'ReleasesRoot', 'DataDirectory', 'BackupRoot') {
        if (-not [string]::Equals($Target.$name.TrimEnd('\', '/').Replace('/', '\'), $paths.$name, [StringComparison]::OrdinalIgnoreCase)) {
            Stop-SL2 "Canonical target $name must be $($paths.$name); existing roots are never adopted."
        }
    }
    foreach ($name in 'CertificatePath', 'CertificatePasswordFile') {
        if (-not [string]::Equals((Split-Path $Target.$name).Replace('/', '\'), $paths.TlsRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Stop-SL2 "Canonical target $name must be inside $($paths.TlsRoot)."
        }
    }
}

function Get-SL2MigrationProvisioningRoots($Target) {
    Assert-SL2CanonicalTargetLayout $Target
    if ($Target.ServiceName -ceq 'sap-lens') { return @('C:\sap-lens', 'C:\ProgramData\sap-lens') }
    # Only the explicit unique acceptance pair permits a synthetic layout.
    @((Split-Path $Target.WorkRoot), (Split-Path $Target.DataDirectory), (Split-Path $Target.BackupRoot),
        (Split-Path (Split-Path $Target.CertificatePath)), (Split-Path $Target.ReleasesRoot)) | Sort-Object -Unique
}

function Get-SL2CanonicalTargetPlan($Source, $Target) {
    if ($Source.ServiceName -cne 'SapLens2' -or $Target.ServiceName -notin @('SapLens', 'sap-lens')) {
        Stop-SL2 'Canonical configuration planning requires the explicit SapLens2 source and SapLens/sap-lens target.'
    }
    $proposed = $Target | Select-Object * -ExcludeProperty ConfigFile, ServiceNameConfigured
    $paths = Get-SL2CanonicalPaths
    foreach ($name in 'WorkRoot', 'ReleasesRoot', 'DataDirectory', 'BackupRoot') { $proposed.$name = $paths.$name }
    $proposed.ServiceName = 'sap-lens'
    $proposed.ServiceAccount = switch ($Source.ServiceAccount) {
        { $_ -in @('LocalSystem', 'NT AUTHORITY\SYSTEM') } { 'LocalSystem'; break }
        'NT SERVICE\SapLens2' { 'NT SERVICE\sap-lens'; break }
        default { Stop-SL2 'Custom service identities require separately reviewed credential migration.' }
    }
    foreach ($name in 'CertificatePath', 'CertificatePasswordFile') { $proposed.$name = Join-SL2 $paths.TlsRoot (Split-Path $Source.$name -Leaf) }
    foreach ($name in 'ListenAddress', 'Port', 'AllowedHosts', 'TrustedProxies') { $proposed.$name = $Source.$name }
    Assert-SL2CanonicalTargetLayout $proposed
    $changes = foreach ($property in $proposed.PSObject.Properties) {
        if (($property.Value | ConvertTo-Json -Compress) -cne ($Target.($property.Name) | ConvertTo-Json -Compress)) {
            [pscustomobject]@{ setting = $property.Name; before = $Target.($property.Name); after = $property.Value }
        }
    }
    [pscustomobject]@{ configuration_written = $false; proposed_config = $proposed; changes = @($changes)
        source_config = $Source.ConfigFile; target_config = $Target.ConfigFile
        source_sha256 = (Get-FileHash -LiteralPath $Source.ConfigFile -Algorithm SHA256).Hash
        target_sha256 = (Get-FileHash -LiteralPath $Target.ConfigFile -Algorithm SHA256).Hash
        warnings = @('Review and save as a new protected configuration outside every target root. Original files are unchanged.',
            'Existing canonical roots still block preflight. Retain historical evidence; cleanup requires separate approval.') }
}
