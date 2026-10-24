<# Windows SCM hosting using the pinned, externally supplied official WinSW wrapper. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Install','Uninstall','Start','Stop','Restart','Status')][string]$Action,
    [string]$InstallDirectory = "$env:ProgramFiles\SAP Lens Server",
    [string]$DataDirectory = "$env:ProgramData\SAP Lens Server",
    [string]$SourceDirectory = "$env:ProgramData\SAP Lens Server\sources",
    [string]$LogDirectory = "$env:ProgramData\SAP Lens Server\logs",
    [string]$ListenHost = '127.0.0.1',
    [ValidateRange(1,65535)][int]$Port = 18743,
    [string]$PublicOrigin = '',
    [string]$AllowedHosts = '127.0.0.1',
    [ValidateSet('local','basic','proxy')][string]$Authentication = 'local',
    [string]$SecretFile = '',
    [string]$TrustedProxies = ''
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Service management requires Windows.' }
$wrapper = Join-Path $InstallDirectory 'SAPLensService.exe'
function Assert-Wrapper {
    $expected = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'
    if (-not (Test-Path $wrapper) -or (Get-FileHash $wrapper -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'Provide the official WinSW v2.12.0 x64 wrapper from the verified server bundle.'
    }
}
Assert-Wrapper
if ($Action -eq 'Status') { & $wrapper status; exit $LASTEXITCODE }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Open an elevated PowerShell for SCM management.' }
function Invoke-ServiceCommand([string]$Command) {
    & $wrapper $Command
    if ($LASTEXITCODE -ne 0) { throw "Windows service $Command failed. Inspect the service logs and Event Viewer." }
}
if ($Action -eq 'Install') {
    if (Get-Service SAPLens -ErrorAction SilentlyContinue) { throw 'SAPLens already exists. Stop and upgrade it rather than overwriting its configuration.' }
    $report = Get-Content (Join-Path $InstallDirectory 'verification-report.json') -Raw | ConvertFrom-Json
    if ($report.verification -ne 'passed' -or $report.signing -ne 'disabled') { throw 'Missing approved server verification report.' }
    foreach ($file in $report.files.PSObject.Properties) {
        if ($file.Name -match '(^/|\\|:|(^|/)\.\.(/|$))') { throw 'Unsafe bundle manifest path.' }
        if ((Get-FileHash (Join-Path $InstallDirectory $file.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value) { throw 'Bundle integrity mismatch. Do not install.' }
    }
    if (-not (Test-Path (Join-Path $InstallDirectory 'app\SAP-Lens.exe'))) { throw 'Use the headless server bundle; the desktop EXE is not a service host.' }
    if ($Authentication -eq 'local' -and $ListenHost -notin @('127.0.0.1','::1')) { throw 'Network binding requires basic or proxy authentication.' }
    if ($Authentication -ne 'local' -and -not (Test-Path $SecretFile -PathType Leaf)) { throw 'Create an access secret file first; never supply domain credentials here.' }
    if (-not $PublicOrigin) { $PublicOrigin = "http://127.0.0.1:$Port" }
    foreach ($directory in @($DataDirectory,$SourceDirectory,$LogDirectory)) {
        if (-not [IO.Path]::IsPathRooted($directory)) { throw 'Use absolute directories; UNC source directories are supported.' }
        if (-not (Test-Path $directory -PathType Container)) { New-Item -ItemType Directory -Force $directory | Out-Null }
    }
    $settings = @{
        SAP_LENS_DEPLOYMENT_MODE='server'; SAP_LENS_HOST=$ListenHost; SAP_LENS_PORT="$Port";
        SAP_LENS_DATA_DIR=$DataDirectory; SAP_LENS_SOURCE_DIR=$SourceDirectory;
        SAP_LENS_PUBLIC_ORIGIN=$PublicOrigin; SAP_LENS_ALLOWED_HOSTS=$AllowedHosts;
        SAP_LENS_AUTH=$Authentication; SAP_LENS_AUTH_SECRET_FILE=$SecretFile;
        SAP_LENS_TRUSTED_PROXIES=$TrustedProxies; SAP_LENS_LOG_LEVEL='info'
    }
    $escape = { param([string]$Text) [Security.SecurityElement]::Escape($Text) }
    $environment = ($settings.GetEnumerator() | Sort-Object Name | ForEach-Object {
        '<env name="' + (& $escape $_.Name) + '" value="' + (& $escape $_.Value) + '"/>'
    }) -join "`r`n"
    $xml = @"
<service>
  <id>SAPLens</id><name>SAP Lens Server</name>
  <description>SAP Lens shared headless backend and browser frontend.</description>
  <executable>%BASE%\app\SAP-Lens.exe</executable>
  <workingdirectory>%BASE%\app</workingdirectory>
  <startmode>Automatic</startmode>
  <serviceaccount><username>NT AUTHORITY\LocalService</username></serviceaccount>
  <stoptimeout>25 sec</stoptimeout><stopparentprocessfirst>true</stopparentprocessfirst>
  <onfailure action="restart" delay="10 sec"/><onfailure action="restart" delay="30 sec"/>
  <resetfailure>1 hour</resetfailure>
  <logpath>$(& $escape $LogDirectory)</logpath><log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>5</keepFiles></log>
  $environment
</service>
"@
    $configuration = Join-Path $InstallDirectory 'SAPLensService.xml'
    [IO.File]::WriteAllText($configuration,$xml,[Text.UTF8Encoding]::new($false))
    # Restrict private state to SYSTEM, Administrators and the dedicated service SID.
    Invoke-ServiceCommand 'install'
    & sc.exe sidtype SAPLens unrestricted | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enable the dedicated service SID.' }
    foreach ($directory in @($DataDirectory,$LogDirectory)) {
        & icacls.exe $directory /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' 'NT SERVICE\SAPLens:(OI)(CI)M' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict service data/log permissions.' }
    }
    # Source access is read-only. Existing domain share/NTFS policy remains administrator-owned.
    if ($SourceDirectory.StartsWith('\\')) {
        Write-Host 'UNC source: configure the domain service identity and both share/NTFS read permissions before Start. Remote ACLs are not modified.'
    } else {
        & icacls.exe $SourceDirectory /grant 'NT SERVICE\SAPLens:(OI)(CI)RX' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Grant the service identity read access to the configured source directory.' }
    }
    if ($SecretFile) {
        & icacls.exe $SecretFile /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' 'NT SERVICE\SAPLens:R' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict access-secret permissions.' }
    }
    Write-Host 'Installed, automatic startup configured. Review configuration, then run -Action Start. Data is preserved on uninstall.'
} elseif ($Action -eq 'Uninstall') {
    $service = Get-Service SAPLens -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne 'Stopped') { Invoke-ServiceCommand 'stop' }
    Invoke-ServiceCommand 'uninstall'
    Write-Host 'Service removed. Application data, logs, source files and bundle are preserved.'
} else { Invoke-ServiceCommand $Action.ToLowerInvariant() }
