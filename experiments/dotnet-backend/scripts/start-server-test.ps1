<#
.SYNOPSIS
  Starts a published SAP Lens 2 Server in the foreground on an isolated Windows TEST machine (development and acceptance testing only).

.DESCRIPTION
  Not a production deployment mechanism. The script:
  1. Selects the newest complete release under -BuildsRoot (a folder written by build-release.ps1: manifest.json plus server-win-x64\ with the
     Server executable and its runtime files), or the release given with -ReleasePath (a release folder or its server-win-x64 folder).
  2. Validates the configuration before anything starts: the listen address is an IP assigned to this machine (not loopback or all interfaces),
     the port is free, the certificate and password files exist, and the data directory is an absolute local path outside known production
     and Desktop data locations.
  3. Runs SapLens.Api.exe in the foreground with --data-dir, --network, --listen, --port, --allowed-hosts, --cert and --cert-password-file.
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
    [string]$DataDirectory = 'C:\saplens2\runtime-test',
    [string]$CertificatePath = 'C:\ProgramData\SapLens2\tls\server.pfx',
    [string]$CertificatePasswordFile = 'C:\ProgramData\SapLens2\tls\cert-password',
    [switch]$DryRun
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$script:ServerFolder = 'server-win-x64'
$script:ServerExecutable = 'SapLens.Api.exe'
# Files a self-contained win-x64 publish of SapLens.Api cannot start without.
$script:RequiredServerFiles = @(
    'SapLens.Api.exe', 'SapLens.Api.dll', 'SapLens.Api.deps.json', 'SapLens.Api.runtimeconfig.json',
    'SapLens.Application.dll', 'SapLens.Domain.dll', 'SapLens.Persistence.dll',
    'hostfxr.dll', 'hostpolicy.dll', 'coreclr.dll', 'System.Private.CoreLib.dll', 'e_sqlite3.dll'
)

function Get-MissingServerFiles([string]$ServerPath) {
    @($script:RequiredServerFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ServerPath $_) -PathType Leaf) })
}

function Resolve-ServerRelease {
    <# Returns @{ Release; Server; Executable; Manifest } for -ReleasePath, or the newest complete release under -BuildsRoot. #>
    param([string]$BuildsRoot, [string]$ReleasePath)
    if ($ReleasePath) {
        if (-not (Test-Path -LiteralPath $ReleasePath -PathType Container)) { throw "Release path '$ReleasePath' does not exist." }
        $full = (Resolve-Path -LiteralPath $ReleasePath).ProviderPath
        $server = if (Test-Path -LiteralPath (Join-Path $full $script:ServerFolder) -PathType Container) { Join-Path $full $script:ServerFolder } else { $full }
        $missing = @(Get-MissingServerFiles $server)
        if ($missing.Count -gt 0) { throw "Release '$full' is not a complete Server release; missing in ${server}: $($missing -join ', ')." }
        $release = if ($server -eq $full) { Split-Path -Parent $full } else { $full }
        $manifest = Join-Path $release 'manifest.json'
        return @{ Release = $release; Server = $server; Executable = (Join-Path $server $script:ServerExecutable); Manifest = $(if (Test-Path -LiteralPath $manifest) { $manifest } else { $null }) }
    }
    if (-not (Test-Path -LiteralPath $BuildsRoot -PathType Container)) { throw "Builds folder '$BuildsRoot' does not exist. Build a release with build-release.ps1 -Output $BuildsRoot\<name>, or pass -ReleasePath." }
    $candidates = foreach ($folder in Get-ChildItem -LiteralPath $BuildsRoot -Directory) {
        $manifest = Join-Path $folder.FullName 'manifest.json'     # build-release.ps1 writes it last: an interrupted build has none
        $server = Join-Path $folder.FullName $script:ServerFolder
        if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { Write-Verbose "Skipping $($folder.Name): no manifest.json"; continue }
        if (-not (Test-Path -LiteralPath $server -PathType Container)) { Write-Verbose "Skipping $($folder.Name): no $script:ServerFolder"; continue }
        $missing = @(Get-MissingServerFiles $server)
        if ($missing.Count -gt 0) { Write-Verbose "Skipping $($folder.Name): missing $($missing -join ', ')"; continue }
        [pscustomobject]@{ Release = $folder.FullName; Server = $server; Manifest = $manifest; Built = (Get-Item -LiteralPath $manifest).LastWriteTimeUtc; Name = $folder.Name }
    }
    $newest = @($candidates | Sort-Object -Property @{ Expression = 'Built'; Descending = $true }, @{ Expression = 'Name'; Descending = $true }) | Select-Object -First 1
    if (-not $newest) { throw "No complete Server release under '$BuildsRoot' (expected <release>\manifest.json and <release>\$script:ServerFolder\$script:ServerExecutable with its runtime files)." }
    @{ Release = $newest.Release; Server = $newest.Server; Executable = (Join-Path $newest.Server $script:ServerExecutable); Manifest = $newest.Manifest }
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
    param([string]$ListenAddress, [int]$Port, [string[]]$AllowedHosts, [string]$DataDirectory, [string]$CertificatePath, [string]$CertificatePasswordFile, [hashtable]$Release)
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($ListenAddress, [ref]$address)) { throw "-ListenAddress must be an IP address, not '$ListenAddress'." }
    if ($address.Equals([System.Net.IPAddress]::Any) -or $address.Equals([System.Net.IPAddress]::IPv6Any)) { throw '-ListenAddress must be one specific address; all interfaces are never used.' }
    if ([System.Net.IPAddress]::IsLoopback($address)) { throw '-ListenAddress must be a LAN address; for loopback-only tests start SapLens.Api.exe without --network.' }
    if (-not (@(Get-LocalIPAddresses) | Where-Object { $_.Equals($address) })) { throw "$ListenAddress is not assigned to this machine (see Get-NetIPAddress)." }
    if ($Port -lt 1 -or $Port -gt 65535) { throw "-Port must be between 1 and 65535, not $Port." }
    if (-not (Test-PortAvailable $address $Port)) { throw "Port $Port on $ListenAddress is already in use (see Get-NetTCPConnection -LocalPort $Port)." }
    foreach ($h in $AllowedHosts) { if (-not $h -or $h -match '[\s,*/]') { throw "'$h' is not a valid -AllowedHosts entry (one host name or address, no wildcards)." } }

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
    param([string]$ListenAddress, [int]$Port, [string[]]$AllowedHosts, [string]$DataDirectory, [string]$CertificatePath, [string]$CertificatePasswordFile)
    $hosts = if ($AllowedHosts -and $AllowedHosts.Count -gt 0) { $AllowedHosts } else { @($ListenAddress) }
    @('--data-dir', [System.IO.Path]::GetFullPath($DataDirectory), '--network', '--listen', $ListenAddress, '--port', [string]$Port,
      '--allowed-hosts', ($hosts -join ','), '--cert', $CertificatePath, '--cert-password-file', $CertificatePasswordFile)
}

function Format-CommandLine([string]$Executable, [string[]]$Arguments) {
    # Display only: every value is a path, address or number; the password stays in its file.
    (@($Executable) + $Arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_.Replace('"', '\"') + '"' } else { $_ } }) -join ' '
}

function Invoke-ServerTestLauncher {
    param([string]$BuildsRoot, [string]$ReleasePath, [string]$ListenAddress, [int]$Port, [string[]]$AllowedHosts, [string]$DataDirectory,
          [string]$CertificatePath, [string]$CertificatePasswordFile, [switch]$DryRun)
    try {
        $release = Resolve-ServerRelease -BuildsRoot $BuildsRoot -ReleasePath $ReleasePath
        Assert-TestConfiguration -ListenAddress $ListenAddress -Port $Port -AllowedHosts $AllowedHosts -DataDirectory $DataDirectory `
            -CertificatePath $CertificatePath -CertificatePasswordFile $CertificatePasswordFile -Release $release
        $arguments = New-ServerArguments -ListenAddress $ListenAddress -Port $Port -AllowedHosts $AllowedHosts -DataDirectory $DataDirectory `
            -CertificatePath $CertificatePath -CertificatePasswordFile $CertificatePasswordFile
    } catch {
        [Console]::Error.WriteLine("start-server-test: $($_.Exception.Message)")
        return 2
    }
    Write-Host 'SAP Lens 2 Server test launcher (development and acceptance testing only)'
    Write-Host "  Release:  $($release.Release)$(if (-not $release.Manifest) { ' (no manifest.json)' })"
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
    -DataDirectory $DataDirectory -CertificatePath $CertificatePath -CertificatePasswordFile $CertificatePasswordFile -DryRun:$DryRun)
