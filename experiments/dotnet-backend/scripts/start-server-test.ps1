<#
.SYNOPSIS
  Starts a published SAP Lens 2 Server in the foreground on an isolated Windows TEST machine (development and acceptance testing only).

.DESCRIPTION
  Not a production deployment mechanism. The script:
  1. Selects the newest complete release under -BuildsRoot (a folder written by build-release.ps1: build-manifest.json plus server\ with the
     single-file SapLens.Api.exe and e_sqlite3.dll; earlier folder-publish releases with manifest.json and server-win-x64\ are still recognized),
     or the release given with -ReleasePath (a release folder, its server folder, or a plain publish folder).
  2. Validates the configuration before anything starts: the listen address is an IP assigned to this machine (not loopback or all interfaces),
     the port is free, the certificate and password files exist, and the data directory is an absolute local path outside known production
     and Desktop data locations.
  3. Runs SapLens.Api.exe in the foreground with --data-dir, --network, --listen, --port, --allowed-hosts, --cert and --cert-password-file
     (plus --trusted-proxies when -TrustedProxies is given; reverse-proxy tests only).
     Ctrl+C stops it. The script exits with the Server's exit code (3 = the Server refused its configuration); 2 means this script refused.

  It never creates, changes or reads the contents of certificate or password files (the Server reads the password file itself), never puts a
  secret on a command line or in its output, and never installs services or changes firewall rules.

  The defaults are the example values of one isolated test VM (docs/experiments/dotnet-backend/WINDOWS_TEST_VM.md), not product defaults.

.EXAMPLE
  .\start-server-test.ps1 -DryRun
.EXAMPLE
  .\start-server-test.ps1 -ListenAddress 10.0.7.50 -Port 18795 -DataDirectory C:\saplens2\runtime-test
#>
[CmdletBinding()]
param(
    [string]$BuildsRoot = 'C:\saplens2\builds',
    [string]$ReleasePath = '',
    [string]$ListenAddress = '10.0.7.50',
    [int]$Port = 18795,
    [string[]]$AllowedHosts = @(),
    [string[]]$TrustedProxies = @(),
    [string]$DataDirectory = 'C:\saplens2\runtime-test',
    [string]$CertificatePath = 'C:\ProgramData\SapLens2\tls\server.pfx',
    [string]$CertificatePasswordFile = 'C:\ProgramData\SapLens2\tls\cert-password',
    [switch]$DryRun
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$script:ServerExecutable = 'SapLens.Api.exe'
# Release layouts written by build-release.ps1/.sh, newest first. Each lists the files its Server cannot start without.
$script:Layouts = @(
    # Single-file (current): everything managed inside SapLens.Api.exe, SQLite's native library beside it.
    @{ Name = 'single-file'; Folder = 'server'; Manifest = 'build-manifest.json'; Required = @('SapLens.Api.exe', 'e_sqlite3.dll') },
    # Folder publish (earlier builds).
    @{ Name = 'folder'; Folder = 'server-win-x64'; Manifest = 'manifest.json'; Required = @(
        'SapLens.Api.exe', 'SapLens.Api.dll', 'SapLens.Api.deps.json', 'SapLens.Api.runtimeconfig.json',
        'SapLens.Application.dll', 'SapLens.Domain.dll', 'SapLens.Persistence.dll',
        'hostfxr.dll', 'hostpolicy.dll', 'coreclr.dll', 'System.Private.CoreLib.dll', 'e_sqlite3.dll') }
)
# Kept for the tests and callers of the earlier layout: the current layout's required files.
$script:RequiredServerFiles = $script:Layouts[0].Required

function Get-MissingServerFiles([string]$ServerPath, [string[]]$Required = $script:RequiredServerFiles) {
    @($Required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ServerPath $_) -PathType Leaf) })
}

function Get-ReleaseCandidate([string]$Folder) {
    <# The release in $Folder (any layout) with its server folder and manifest, or a reason it is not one. #>
    foreach ($layout in $script:Layouts) {
        $server = Join-Path $Folder $layout.Folder
        if (-not (Test-Path -LiteralPath $server -PathType Container)) { continue }
        $missing = @(Get-MissingServerFiles $server $layout.Required)
        $manifest = Join-Path $Folder $layout.Manifest
        return [pscustomobject]@{ Release = $Folder; Server = $server; Layout = $layout.Name; Missing = $missing
            Manifest = $(if (Test-Path -LiteralPath $manifest -PathType Leaf) { $manifest } else { $null }) }
    }
    $null
}

function Resolve-ServerRelease {
    <# Returns @{ Release; Server; Executable; Manifest; Layout } for -ReleasePath, or the newest complete release under -BuildsRoot. #>
    param([string]$BuildsRoot, [string]$ReleasePath)
    if ($ReleasePath) {
        if (-not (Test-Path -LiteralPath $ReleasePath -PathType Container)) { throw "Release path '$ReleasePath' does not exist." }
        $full = (Resolve-Path -LiteralPath $ReleasePath).ProviderPath.TrimEnd('\', '/')
        $candidate = Get-ReleaseCandidate $full
        if (-not $candidate -and (Split-Path -Leaf $full) -in @($script:Layouts | ForEach-Object { $_.Folder })) { $candidate = Get-ReleaseCandidate (Split-Path -Parent $full) }
        if (-not $candidate) {
            # A bare publish folder (dotnet publish -o): the executable and its runtime files directly inside.
            $layout = @($script:Layouts | Where-Object { @(Get-MissingServerFiles $full $_.Required).Count -eq 0 }) | Select-Object -First 1
            if (-not $layout) { throw "Release '$full' is not a complete Server release; missing in ${full}: $((Get-MissingServerFiles $full) -join ', ')." }
            $candidate = [pscustomobject]@{ Release = (Split-Path -Parent $full); Server = $full; Layout = $layout.Name; Missing = @(); Manifest = $null }
        }
        if ($candidate.Missing.Count -gt 0) { throw "Release '$full' is not a complete Server release; missing in $($candidate.Server): $($candidate.Missing -join ', ')." }
        return @{ Release = $candidate.Release; Server = $candidate.Server; Executable = (Join-Path $candidate.Server $script:ServerExecutable); Manifest = $candidate.Manifest; Layout = $candidate.Layout }
    }
    if (-not (Test-Path -LiteralPath $BuildsRoot -PathType Container)) { throw "Builds folder '$BuildsRoot' does not exist. Build a release with build-release.ps1 -Output $BuildsRoot, or pass -ReleasePath." }
    $candidates = foreach ($folder in Get-ChildItem -LiteralPath $BuildsRoot -Directory) {
        $candidate = Get-ReleaseCandidate $folder.FullName
        if (-not $candidate) { Write-Verbose "Skipping $($folder.Name): no server folder"; continue }
        # The manifest is written last: an interrupted build has none.
        if (-not $candidate.Manifest) { Write-Verbose "Skipping $($folder.Name): no manifest"; continue }
        if ($candidate.Missing.Count -gt 0) { Write-Verbose "Skipping $($folder.Name): missing $($candidate.Missing -join ', ')"; continue }
        $candidate | Add-Member -NotePropertyName Built -NotePropertyValue (Get-Item -LiteralPath $candidate.Manifest).LastWriteTimeUtc -PassThru |
            Add-Member -NotePropertyName Name -NotePropertyValue $folder.Name -PassThru
    }
    $newest = @($candidates | Sort-Object -Property @{ Expression = 'Built'; Descending = $true }, @{ Expression = 'Name'; Descending = $true }) | Select-Object -First 1
    if (-not $newest) { throw "No complete Server release under '$BuildsRoot' (expected <release>\build-manifest.json and <release>\server\SapLens.Api.exe with e_sqlite3.dll)." }
    @{ Release = $newest.Release; Server = $newest.Server; Executable = (Join-Path $newest.Server $script:ServerExecutable); Manifest = $newest.Manifest; Layout = $newest.Layout }
}

function Get-LocalIPAddresses {
    [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
        Where-Object { $_.OperationalStatus -eq [System.Net.NetworkInformation.OperationalStatus]::Up } |
        ForEach-Object { $_.GetIPProperties().UnicastAddresses } | ForEach-Object { $_.Address }
}

function Test-PortAvailable([System.Net.IPAddress]$Address, [int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new($Address, $Port)
    $listener.ExclusiveAddressUse = $true
    try { $listener.Start(); return $true } catch [System.Net.Sockets.SocketException] { return $false } finally { $listener.Stop() }
}

function Get-ProtectedDataPaths {
    <# Production and Desktop data locations that a test run must never use (v1 and SAP Lens 2). #>
    $paths = @()
    if ($env:ProgramData) { $paths += (Join-Path $env:ProgramData 'SapLens2'), (Join-Path $env:ProgramData 'SAP Lens Server') }
    if ($env:LOCALAPPDATA) { $paths += (Join-Path $env:LOCALAPPDATA 'SAP Lens 2 Prototype'), (Join-Path $env:LOCALAPPDATA 'SAP Lens') }
    if ($env:ProgramFiles) { $paths += $env:ProgramFiles }
    if ($env:SystemRoot) { $paths += $env:SystemRoot }
    $paths
}

function Test-PathWithin([string]$Path, [string]$Parent) {
    $p = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $q = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $p.Equals($q, [System.StringComparison]::OrdinalIgnoreCase) -or $p.StartsWith($q + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or
        $p.StartsWith($q + '\', [System.StringComparison]::OrdinalIgnoreCase) -or $p.StartsWith($q + '/', [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-TestConfiguration {
    param([string]$ListenAddress, [int]$Port, [string[]]$AllowedHosts, [string]$DataDirectory, [string]$CertificatePath, [string]$CertificatePasswordFile, [hashtable]$Release,
          [string[]]$TrustedProxies = @())
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($ListenAddress, [ref]$address)) { throw "-ListenAddress must be an IP address, not '$ListenAddress'." }
    if ($address.Equals([System.Net.IPAddress]::Any) -or $address.Equals([System.Net.IPAddress]::IPv6Any)) { throw '-ListenAddress must be one specific address; all interfaces are never used.' }
    if ([System.Net.IPAddress]::IsLoopback($address)) { throw '-ListenAddress must be a LAN address; for loopback-only tests start SapLens.Api.exe without --network.' }
    if (-not (@(Get-LocalIPAddresses) | Where-Object { $_.Equals($address) })) { throw "$ListenAddress is not assigned to this machine (see Get-NetIPAddress)." }
    if ($Port -lt 1 -or $Port -gt 65535) { throw "-Port must be between 1 and 65535, not $Port." }
    if (-not (Test-PortAvailable $address $Port)) { throw "Port $Port on $ListenAddress is already in use (see Get-NetTCPConnection -LocalPort $Port)." }
    foreach ($h in $AllowedHosts) { if (-not $h -or $h -match '[\s,*/]') { throw "'$h' is not a valid -AllowedHosts entry (one host name or address, no wildcards)." } }
    foreach ($p in $TrustedProxies) { if (-not $p -or $p -match '[\s,*]') { throw "'$p' is not a valid -TrustedProxies entry (one IP address or CIDR network); the Server validates the range." } }

    if (-not $DataDirectory) { throw '-DataDirectory is required.' }
    if ($DataDirectory.StartsWith('\\') -or $DataDirectory.StartsWith('//')) { throw "-DataDirectory must be a local path, not a network share ('$DataDirectory')." }
    # Fully qualified: a drive letter with a separator on Windows (C:\x, not C:x or \x); an absolute path elsewhere (test hosts).
    $qualified = if ([System.IO.Path]::DirectorySeparatorChar -eq '\') { $DataDirectory -match '^[A-Za-z]:[\\/]' } else { $DataDirectory.StartsWith('/') }
    if (-not $qualified) { throw "-DataDirectory must be an absolute path, not '$DataDirectory'." }
    $full = [System.IO.Path]::GetFullPath($DataDirectory)
    if ($full.TrimEnd('\', '/') -eq [System.IO.Path]::GetPathRoot($full).TrimEnd('\', '/')) { throw "-DataDirectory must not be a drive root ('$full')." }
    foreach ($protected in Get-ProtectedDataPaths) {
        if (Test-PathWithin $full $protected) { throw "-DataDirectory '$full' is inside '$protected', a production or Desktop location. Use an isolated test folder such as C:\saplens2\runtime-test." }
    }
    if ($Release -and (Test-PathWithin $full $Release.Release)) { throw "-DataDirectory must not be inside the release folder '$($Release.Release)'." }

    if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) { throw "Certificate '$CertificatePath' does not exist. This script never creates certificates; see SERVER_NETWORK_ACCESS.md section 4." }
    if (-not (Test-Path -LiteralPath $CertificatePasswordFile -PathType Leaf)) { throw "Certificate password file '$CertificatePasswordFile' does not exist." }
    if ((Get-Item -LiteralPath $CertificatePasswordFile).Length -eq 0) { throw "Certificate password file '$CertificatePasswordFile' is empty." }
}

function New-ServerArguments {
    param([string]$ListenAddress, [int]$Port, [string[]]$AllowedHosts, [string]$DataDirectory, [string]$CertificatePath, [string]$CertificatePasswordFile,
          [string[]]$TrustedProxies = @())
    $hosts = if ($AllowedHosts -and $AllowedHosts.Count -gt 0) { $AllowedHosts } else { @($ListenAddress) }
    @('--data-dir', [System.IO.Path]::GetFullPath($DataDirectory), '--network', '--listen', $ListenAddress, '--port', [string]$Port,
      '--allowed-hosts', ($hosts -join ','), '--cert', $CertificatePath, '--cert-password-file', $CertificatePasswordFile) +
      $(if ($TrustedProxies -and $TrustedProxies.Count -gt 0) { @('--trusted-proxies', ($TrustedProxies -join ',')) } else { @() })
}

function Format-CommandLine([string]$Executable, [string[]]$Arguments) {
    # Display only: every value is a path, address or number; the password stays in its file.
    (@($Executable) + $Arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_.Replace('"', '\"') + '"' } else { $_ } }) -join ' '
}

function Invoke-ServerTestLauncher {
    param([string]$BuildsRoot, [string]$ReleasePath, [string]$ListenAddress, [int]$Port, [string[]]$AllowedHosts, [string]$DataDirectory,
          [string]$CertificatePath, [string]$CertificatePasswordFile, [switch]$DryRun, [string[]]$TrustedProxies = @())
    try {
        $release = Resolve-ServerRelease -BuildsRoot $BuildsRoot -ReleasePath $ReleasePath
        Assert-TestConfiguration -ListenAddress $ListenAddress -Port $Port -AllowedHosts $AllowedHosts -DataDirectory $DataDirectory `
            -CertificatePath $CertificatePath -CertificatePasswordFile $CertificatePasswordFile -Release $release -TrustedProxies $TrustedProxies
        $arguments = New-ServerArguments -ListenAddress $ListenAddress -Port $Port -AllowedHosts $AllowedHosts -DataDirectory $DataDirectory `
            -CertificatePath $CertificatePath -CertificatePasswordFile $CertificatePasswordFile -TrustedProxies $TrustedProxies
    } catch {
        [Console]::Error.WriteLine("start-server-test: $($_.Exception.Message)")
        return 2
    }
    Write-Host 'SAP Lens 2 Server test launcher (development and acceptance testing only)'
    Write-Host "  Release:  $($release.Release)$(if (-not $release.Manifest) { ' (no build manifest)' })"
    if ($release.Manifest) {
        $manifest = Get-Content -LiteralPath $release.Manifest -Raw | ConvertFrom-Json
        Write-Host "  Source:   $($manifest.source_sha)$(if ($manifest.source_dirty) { ' (dirty working tree)' })"
    }
    Write-Host "  URL:      https://$($ListenAddress):$Port/"
    $inherited = @(Get-ChildItem Env: | Where-Object Name -like 'SAP_LENS_V2_*' | ForEach-Object Name)
    if ($inherited.Count -gt 0) { Write-Host "  Inherited environment (names only; options above take precedence): $($inherited -join ', ')" }
    Write-Host "  Command:  $(Format-CommandLine $release.Executable $arguments)"
    if ($DryRun) { Write-Host 'Dry run: configuration valid; nothing was started.'; return 0 }
    Write-Host 'Starting in the foreground; press Ctrl+C to stop.'
    & $release.Executable @arguments | Out-Host     # the Server's output goes to the console, never into this function's return value
    $code = $LASTEXITCODE
    if ($code -ne 0) { [Console]::Error.WriteLine("start-server-test: the Server exited with code $code$(if ($code -eq 3) { ' (configuration refused; reason above)' }).") }
    return $code
}

# Dot-sourced (tests): define the functions only.
if ($MyInvocation.InvocationName -eq '.') { return }
exit (Invoke-ServerTestLauncher -BuildsRoot $BuildsRoot -ReleasePath $ReleasePath -ListenAddress $ListenAddress -Port $Port -AllowedHosts $AllowedHosts `
    -DataDirectory $DataDirectory -CertificatePath $CertificatePath -CertificatePasswordFile $CertificatePasswordFile -DryRun:$DryRun -TrustedProxies $TrustedProxies)
