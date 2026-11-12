<# Windows SCM hosting using the pinned, externally supplied official WinSW wrapper. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Install','Uninstall','Start','Stop','Restart','Status','Upgrade','Backup','Restore','RepairSecret')][string]$Action,
    [string]$InstallDirectory = "$env:ProgramFiles\SAP Lens Server",
    [string]$DataDirectory = "$env:ProgramData\SAP Lens Server",
    [string]$SourceDirectory = "$env:ProgramData\SAP Lens Server\sources",
    [string]$LogDirectory = "$env:ProgramData\SAP Lens Server\logs",
    [string]$ListenHost = '127.0.0.1',
    [ValidateRange(1,65535)][int]$Port = 18743,
    [string]$PublicOrigin = '',
    [string]$AllowedHosts = '127.0.0.1',
    [ValidateSet('sessions','local','basic','proxy')][string]$Authentication = 'sessions',
    [string]$SecretFile = '',
    [string]$TrustedProxies = '',
    [string]$TlsCertificate = '',
    [string]$TlsKey = '',
    [string]$NewBundleDirectory = '',
    [string]$BackupDirectory = "$env:ProgramData\SAP Lens Server Backups",
    [string]$Archive = '',
    [string]$RestoreDataDirectory = '',
    [string]$RestoreConfigurationDirectory = '',
    [switch]$ConfirmRestore,
    [switch]$ConfirmAccountRollback,
    [switch]$AllowLegacyArchive,
    [switch]$ConfirmSecretRepair,
    [switch]$PurgeData,
    [switch]$ConfirmPurge
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Service management requires Windows.' }
if (-not [IO.Path]::IsPathRooted($InstallDirectory)) { throw 'Use an absolute installation directory.' }
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
$wrapper = Join-Path $InstallDirectory 'SAPLensService.exe'
function Assert-Wrapper {
    $expected = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'
    if (-not (Test-Path $wrapper) -or (Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'Provide the official WinSW v2.12.0 x64 wrapper from the verified server bundle.'
    }
}
Assert-Wrapper
if ($PurgeData -and ($Action -ne 'Uninstall' -or -not $ConfirmPurge)) { throw 'Private-data removal requires Uninstall -PurgeData -ConfirmPurge.' }
if ($Action -eq 'Status') { & $wrapper status; exit $LASTEXITCODE }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Open an elevated PowerShell for SCM management.' }
function Wait-ServiceState([string]$State, [int]$TimeoutSeconds = 40) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $observed = 'absent'
    do {
        $service = Get-Service SAPLens -ErrorAction SilentlyContinue
        try {
            if ($service) {
                $service.Refresh()
                $observed = [string]$service.Status
                if ($State -ne 'Absent' -and $observed -eq $State) { return }
            } else {
                $observed = 'absent'
                if ($State -eq 'Absent') { return }
            }
        } finally {
            # Open ServiceController handles can delay SCM deletion themselves.
            if ($service) { $service.Dispose() }
        }
        if ($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) { break }
        Start-Sleep -Milliseconds 250
    } while ($true)
    throw "SCM did not reach $State within $TimeoutSeconds seconds (last state: $observed). Inspect service logs and Event Viewer."
}
function Invoke-ServiceCommand([string]$Command) {
    & $wrapper $Command
    if ($LASTEXITCODE -ne 0) { throw "Windows service $Command failed. Inspect the service logs and Event Viewer." }
    # WinSW returning is not sufficient evidence that SCM finished transitioning.
    # Backup, upgrade and uninstall must never race an outstanding stop.
    switch ($Command.ToLowerInvariant()) {
        'install' { Wait-ServiceState 'Stopped' }
        'start' { Wait-ServiceState 'Running' }
        'stop' { Wait-ServiceState 'Stopped' }
        'restart' { Wait-ServiceState 'Running' }
        'uninstall' { Wait-ServiceState 'Absent' }
    }
}
function Read-ServiceConfiguration {
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $reader = [System.Xml.XmlReader]::Create((Join-Path $InstallDirectory 'SAPLensService.xml'),$settings)
    try { $document = New-Object System.Xml.XmlDocument; $document.XmlResolver = $null; $document.Load($reader) } finally { $reader.Dispose() }
    $values = @{}
    foreach ($entry in $document.service.env) { $values[[string]$entry.name] = [string]$entry.value }
    if ($values.SAP_LENS_DEPLOYMENT_MODE -ne 'server' -or -not [IO.Path]::IsPathRooted($values.SAP_LENS_DATA_DIR)) { throw 'Unrecognized installed service configuration.' }
    $registered = Get-CimInstance Win32_Service -Filter "Name='SAPLens'"
    if (-not $registered -or $registered.PathName -notmatch ('^\s*"?' + [regex]::Escape($wrapper) + '"?(?:\s|$)')) { throw 'The registered service belongs to another installation. No service was changed.' }
    return $values
}
# Runs the application's own configuration validation (including the secret-file permission policy) with the installed service environment.
# Prints and returns only the validation message, never a configuration value or secret.
function Test-InstalledConfiguration([string]$Executable, $Values) {
    $saved = @{}
    foreach ($name in $Values.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process'); [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], 'Process') }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'    # Windows PowerShell 5.1 turns native stderr into a terminating error under 'Stop'
    try {
        $message = (& $Executable --check-server-config 2>&1 | Out-String).Trim()
        return New-Object psobject -Property @{ Ok = ($LASTEXITCODE -eq 0); Message = $message }
    } finally {
        $ErrorActionPreference = $previousPreference
        foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    }
}
function Assert-RepairableSecretFile([string]$Path) {
    if (-not $Path -or -not [IO.Path]::IsPathRooted($Path)) { throw 'The installed configuration has no absolute access-secret path; nothing to repair.' }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer) { throw 'The configured access-secret path is a directory; nothing was changed.' }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'The configured access-secret path is a link; permissions are never changed through links. Nothing was changed.' }
}
function Assert-NewBundle([string]$Directory) {
    $report = Get-Content (Join-Path $Directory 'verification-report.json') -Raw | ConvertFrom-Json
    if ($report.verification -ne 'passed' -or $report.signing -ne 'disabled' -or $report.format -ne 'onedir-console-service') { throw 'Use a verified unsigned headless service package.' }
    $expected = @('verification-report.json') + @($report.files.PSObject.Properties.Name)
    $actual = @(Get-ChildItem $Directory -Recurse -Force | Where-Object { -not $_.PSIsContainer } | ForEach-Object { $_.FullName.Substring($Directory.TrimEnd('\').Length+1).Replace('\','/') })
    $differences=@(Compare-Object $expected $actual)
    $links=@(Get-ChildItem $Directory -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    if ($differences.Count -or $links.Count) {
        $details=@($differences | ForEach-Object { "$($_.InputObject) [$(if ($_.SideIndicator -eq '=>') { 'unexpected file' } else { 'missing file' })]" })
        $details+=@($links | ForEach-Object { $_.FullName.Substring($Directory.TrimEnd('\').Length+1)+" [reparse point: $($_.GetType().Name)]" })
        throw ('Unexpected files or links in replacement bundle: '+($details -join '; '))
    }
    foreach ($file in $report.files.PSObject.Properties) {
        if ($file.Name -match '(^/|\\|:|(^|/)\.\.(/|$))' -or $file.Value -notmatch '^[a-f0-9]{64}$') { throw 'Invalid replacement manifest.' }
        if ((Get-FileHash -LiteralPath (Join-Path $Directory $file.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value) { throw 'Replacement package checksum mismatch.' }
    }
    if ((Get-FileHash -LiteralPath (Join-Path $Directory 'SAPLensService.exe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da') { throw 'Replacement WinSW is not the pinned wrapper.' }
    return $report
}
function Invoke-InstalledMaintenance([string]$Executable, [string[]]$Arguments, $Values) {
    $saved=@{}
    foreach ($name in $Values.Keys) { $saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process'); [Environment]::SetEnvironmentVariable($name,[string]$Values[$name],'Process') }
    try {
        & $Executable --maintenance @Arguments
        if ($LASTEXITCODE -ne 0) { throw 'Stopped maintenance failed. Existing state and host configuration were preserved; inspect the diagnostic message.' }
    } finally { foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name,$saved[$name],'Process') } }
}
function Invoke-PrivateBackup([string]$Executable,[string]$Data,$Values) {
    if (-not [IO.Path]::IsPathRooted($BackupDirectory)) { throw 'Use an absolute dedicated backup directory.' }
    $BackupDirectory=[IO.Path]::GetFullPath($BackupDirectory).TrimEnd('\')
    $Data=[IO.Path]::GetFullPath($Data).TrimEnd('\')
    foreach ($root in @($Data,$InstallDirectory.TrimEnd('\'))) {
        if ($BackupDirectory -eq $root -or $BackupDirectory.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Choose a backup directory outside application data and binaries.' }
    }
    New-Item -ItemType Directory -Force $BackupDirectory | Out-Null
    $destination=Join-Path $BackupDirectory ('SAP-Lens-Service-'+[guid]::NewGuid().ToString('N')+'.slbak')
    Invoke-InstalledMaintenance $Executable @('backup','--data',$Data,'--output',$destination,'--mode','server') $Values
    Write-Host 'Encrypted logical backup verified. Preserve the host recovery key, service XML and TLS configuration separately.'
}
function Assert-ServiceReady($Values) {
    $deadline = (Get-Date).AddSeconds(45)
    $origin = [Uri]$Values.SAP_LENS_PUBLIC_ORIGIN
    $localHost = if ($Values.SAP_LENS_HOST -eq '::') { '[::1]' } elseif ($Values.SAP_LENS_HOST.Contains(':')) { '['+$Values.SAP_LENS_HOST+']' } elseif ($Values.SAP_LENS_HOST -eq '0.0.0.0') { '127.0.0.1' } else { $Values.SAP_LENS_HOST }
    while ((Get-Date) -lt $deadline) {
        $registered = Get-CimInstance Win32_Service -Filter "Name='SAPLens'"
        foreach ($connection in @(Get-NetTCPConnection -State Listen -LocalPort ([int]$Values.SAP_LENS_PORT) -ErrorAction SilentlyContinue)) {
            $owner = [int]$connection.OwningProcess
            for ($depth=0; $depth -lt 16 -and $owner -gt 0; $depth++) {
                if ($registered.State -eq 'Running' -and $owner -eq [int]$registered.ProcessId) {
                    try { if ((Invoke-RestMethod ("http://"+$localHost+":"+$Values.SAP_LENS_PORT+"/health/ready") -Headers @{Host=$origin.Authority} -TimeoutSec 2).status -eq 'ready') { return } } catch { }
                    break
                }
                $process = Get-CimInstance Win32_Process -Filter ("ProcessId="+$owner) -ErrorAction SilentlyContinue
                if (-not $process) { break }; $owner = [int]$process.ParentProcessId
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'The registered service did not own a ready listener. Inspect SCM and private logs.'
}
if ($Action -eq 'RepairSecret') {
    # Explicit, elevated, one purpose: restore the private ACL of the access secret THIS service is configured with. The path comes from the installed
    # service configuration, never from a parameter; the file content is never read or printed; other files and the service stay untouched.
    $values = Read-ServiceConfiguration
    if ($values.SAP_LENS_AUTH -notin @('basic','proxy')) { throw 'This service does not use a shared access-secret file. Session accounts are managed inside SAP Lens.' }
    $secretPath = $values.SAP_LENS_AUTH_SECRET_FILE
    Assert-RepairableSecretFile $secretPath
    $check = Test-InstalledConfiguration (Join-Path $InstallDirectory 'app\SAP-Lens.exe') $values
    if ($check.Ok) { Write-Host 'The access-secret permissions already satisfy the policy. Nothing was changed.'; return }
    Write-Host ('Current policy result: ' + $check.Message)
    if (-not $ConfirmSecretRepair) { Write-Host ('Review the message above. To restrict "' + $secretPath + '" to SYSTEM, Administrators and the service identity (read), rerun with -ConfirmSecretRepair. Nothing was changed.'); exit 3 }
    & icacls.exe $secretPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' 'NT SERVICE\SAPLens:R' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict access-secret permissions. The file content was not touched.' }
    $after = Test-InstalledConfiguration (Join-Path $InstallDirectory 'app\SAP-Lens.exe') $values
    if (-not $after.Ok) { throw ('Permissions were restricted but the policy still rejects the file: ' + $after.Message + ' Review other explicit entries (for example a named user group) with icacls.') }
    Write-Host 'Access-secret permissions repaired. Start or restart the service when ready.'
    return
}
if ($Action -in @('Upgrade','Backup','Restore')) {
    $values = Read-ServiceConfiguration
    if ($Action -eq 'Upgrade' -and $values.SAP_LENS_AUTH -in @('basic','proxy')) {
        # An installation whose secret kept a permissive inherited ACL would fail to start after the swap; say so before anything is changed.
        Assert-RepairableSecretFile $values.SAP_LENS_AUTH_SECRET_FILE
        $preflight = Test-InstalledConfiguration (Join-Path $InstallDirectory 'app\SAP-Lens.exe') $values
        if (-not $preflight.Ok) { throw ('The installed configuration is rejected by the current policy: ' + $preflight.Message + ' Run -Action RepairSecret (review first, then -ConfirmSecretRepair). No installed files were changed.') }
    }
    $current = Get-Content (Join-Path $InstallDirectory 'verification-report.json') -Raw | ConvertFrom-Json
    $executable = Join-Path $InstallDirectory 'app\SAP-Lens.exe'
    if ($Action -eq 'Upgrade') {
        if (-not $NewBundleDirectory) { throw 'Upgrade requires -NewBundleDirectory from a freshly extracted, verified package.' }
        $newRoot = (Resolve-Path $NewBundleDirectory).Path.TrimEnd('\')
        if ($newRoot -eq $InstallDirectory.TrimEnd('\') -or $newRoot.StartsWith($InstallDirectory.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Extract the replacement outside the installed application.' }
        $replacement = Assert-NewBundle $newRoot
        $newExecutable = Join-Path $newRoot 'app\SAP-Lens.exe'
        & $newExecutable --maintenance version-check --application-version $current.identity.version --target-version $replacement.identity.version
        if ($LASTEXITCODE -ne 0) { throw 'Version compatibility check failed. No installed files were changed.' }
    }
    if ((Get-Service SAPLens).Status -ne 'Stopped') { Invoke-ServiceCommand 'stop' }
    if ($Action -eq 'Backup') { Invoke-PrivateBackup $executable $values.SAP_LENS_DATA_DIR $values; return }
    if ($Action -eq 'Restore') {
        if (-not $Archive -or -not $RestoreDataDirectory -or -not $ConfirmRestore) { throw 'Restore needs -Archive, an empty -RestoreDataDirectory and -ConfirmRestore. Account rollback needs -ConfirmAccountRollback.' }
        if ($RestoreConfigurationDirectory) { throw 'Host/service configuration is not transferred by a portable archive. Preserve the installed XML separately; omit -RestoreConfigurationDirectory.' }
        $restoreArguments=@('restore','--archive',$Archive,'--data',$RestoreDataDirectory,'--mode','server','--confirm-restore')
        if ($ConfirmAccountRollback) { $restoreArguments+='--confirm-accounts' }
        if ($AllowLegacyArchive) { $restoreArguments+='--allow-legacy' }
        Invoke-InstalledMaintenance $executable $restoreArguments $values
        Write-Host 'Restored to the empty data destination. Host configuration was not changed. Review data, recovery key and service ACLs before explicitly switching directories. Service remains stopped.'
        return
    }
    Invoke-PrivateBackup $executable $values.SAP_LENS_DATA_DIR $values
    $suffix = [guid]::NewGuid().ToString('N')
    $staged = Join-Path $InstallDirectory ('app.pending.'+$suffix)
    Copy-Item (Join-Path $newRoot 'app') $staged -Recurse
    foreach ($file in $replacement.files.PSObject.Properties | Where-Object { $_.Name.StartsWith('app/') }) {
        if ((Get-FileHash -LiteralPath (Join-Path $staged $file.Name.Substring(4)) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value) { throw 'Staged application hash mismatch. Existing application remains selected.' }
    }
    $previous = Join-Path $InstallDirectory ('app.previous.'+$suffix)
    Move-Item (Join-Path $InstallDirectory 'app') $previous
    Move-Item $staged (Join-Path $InstallDirectory 'app')
    foreach ($name in @('SAP-Lens-Service-Manager.exe','manage-server-service.ps1','README.md','LICENSE-WinSW.txt','LICENSE.md','verification-report.json')) { Copy-Item (Join-Path $newRoot $name) (Join-Path $InstallDirectory $name) -Force }
    try { Invoke-ServiceCommand 'start'; Assert-ServiceReady $values }
    catch {
        if ((Get-Service SAPLens).Status -ne 'Stopped') { Invoke-ServiceCommand 'stop' }
        throw 'Upgrade health failed. Service stopped; previous binaries, administrator XML and private backup retained. Review compatible data recovery before switching binaries back.'
    }
    Write-Host 'Upgrade ready. Administrator XML, data and service identity preserved; previous binaries and private backup retained.'
    return
}
if ($Action -in @('Start','Stop','Restart','Uninstall')) { $installedValues = Read-ServiceConfiguration }
if ($Action -eq 'Install') {
    # Preflight: everything below only reads. Nothing is created, registered or copied until all of it passes.
    if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Major -lt 10) { throw 'The SAP Lens service requires 64-bit Windows 10, Windows Server 2016 or newer. Nothing was installed.' }
    if (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count) { throw "Port $Port is already in use by another program. Stop it or choose another -Port; nothing was installed." }
    if (Get-Service SAPLens -ErrorAction SilentlyContinue) { throw 'SAPLens already exists. Stop and upgrade it rather than overwriting its configuration.' }
    $report = Get-Content (Join-Path $InstallDirectory 'verification-report.json') -Raw | ConvertFrom-Json
    if ($report.verification -ne 'passed' -or $report.signing -ne 'disabled') { throw 'Missing approved server verification report.' }
    foreach ($file in $report.files.PSObject.Properties) {
        if ($file.Name -match '(^/|\\|:|(^|/)\.\.(/|$))') { throw 'Unsafe bundle manifest path.' }
        if ((Get-FileHash -LiteralPath (Join-Path $InstallDirectory $file.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value) { throw 'Bundle integrity mismatch. Do not install.' }
    }
    if (-not (Test-Path (Join-Path $InstallDirectory 'app\SAP-Lens.exe'))) { throw 'Use the headless server bundle; the desktop EXE is not a service host.' }
    if ($Authentication -notin @('sessions','local')) { throw 'New installations use sessions. Migrate existing legacy accounts locally; shared Basic/proxy identities are not application accounts.' }
    $Authentication='sessions'
    if ($TrustedProxies) { Assert-RepairableSecretFile $SecretFile }
    if (-not $PublicOrigin) { $PublicOrigin = "http://127.0.0.1:$Port" }
    if (-not [IO.Path]::IsPathRooted($DataDirectory)) { throw 'Use an absolute private data directory.' }
    if (-not (Test-Path (Join-Path $DataDirectory 'security\accounts.sqlite3'))) {
        if ((Test-Path $DataDirectory) -and @(Get-ChildItem -LiteralPath $DataDirectory -Force).Count) { throw 'Existing data without session accounts requires stopped local identity migration; it will not be treated as a fresh installation.' }
        New-Item -ItemType Directory -Force $DataDirectory | Out-Null
        & icacls.exe $DataDirectory /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot protect new identity storage before initialization.' }
        & (Join-Path $InstallDirectory 'app\SAP-Lens.exe') --initialize-identity $DataDirectory
        if ($LASTEXITCODE -ne 0) { throw 'First-run identity initialization refused; preserve the diagnostics and data directory.' }
    }
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
    $address=$null
    if (-not [Net.IPAddress]::TryParse($ListenHost,[ref]$address)) { throw 'ListenHost must be a numeric IP address.' }
    $origin=[Uri]$PublicOrigin
    if ($origin.Scheme -notin @('http','https') -or $origin.AbsolutePath -ne '/' -or $origin.Query -or $origin.Fragment -or $origin.UserInfo) { throw 'Use an HTTP(S) origin without a path, credentials, query or fragment.' }
    if ($AllowedHosts.Split(',').Trim() -notcontains $origin.Host -or $AllowedHosts.Contains('*')) { throw 'AllowedHosts must explicitly include the public hostname, without wildcards.' }
    if ($origin.Scheme -eq 'http' -and ($ListenHost -notin @('127.0.0.1','::1') -or $origin.Host -notin @('127.0.0.1','localhost','::1'))) { throw 'HTTP password sign-in requires a loopback listener and hostname. Use HTTPS for remote access.' }
    if ($origin.Host -notin @('127.0.0.1','localhost','::1') -and $origin.Scheme -ne 'https') { throw 'Network public origins require HTTPS.' }
    if ($Authentication -eq 'proxy' -and -not $TrustedProxies) { throw 'Proxy authentication requires explicit trusted peer CIDRs.' }
    if ($TrustedProxies) {
        $secret=([IO.File]::ReadAllText($SecretFile)).Trim()
        if ($secret.Length -lt 32 -or $secret.Length -gt 256 -or $secret -match '[^!-~]') { throw 'Access secret must contain 32-256 non-whitespace ASCII characters.' }
    }
    $backupKey=Join-Path (Split-Path $DataDirectory -Parent) ('SAP-Lens-service-backup-'+[guid]::NewGuid().ToString('N')+'.key')
    & (Join-Path $InstallDirectory 'app\SAP-Lens.exe') --maintenance init-backup-key --data $DataDirectory --output $backupKey
    if ($LASTEXITCODE -ne 0) { throw 'Could not provision the protected external backup key. No service was installed.' }
    $settings.SAP_LENS_BACKUP_KEY_FILE=$backupKey
    if ($TlsCertificate -or $TlsKey) { $settings.SAP_LENS_TLS_CERT_FILE=$TlsCertificate; $settings.SAP_LENS_TLS_KEY_FILE=$TlsKey }
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
    if (Test-Path $configuration) { throw 'Existing administrator service configuration is preserved. Review it explicitly before reinstalling.' }
    [IO.File]::WriteAllText($configuration,$xml,[Text.UTF8Encoding]::new($false))
    $configurationCheck=Test-InstalledConfiguration (Join-Path $InstallDirectory 'app\SAP-Lens.exe') $settings
    if (-not $configurationCheck.Ok) { throw ('Configuration rejected before SCM registration: '+$configurationCheck.Message) }
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
    & icacls.exe $backupKey /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' 'NT SERVICE\SAPLens:R' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict backup-key permissions; service remains stopped.' }
    if ($SecretFile) {
        & icacls.exe $SecretFile /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' 'NT SERVICE\SAPLens:R' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict access-secret permissions.' }
    }
    Write-Host 'Installed, automatic startup configured. Review configuration, then run -Action Start. Data is preserved on uninstall.'
} elseif ($Action -eq 'Uninstall') {
    $service = Get-Service SAPLens -ErrorAction SilentlyContinue
    if ($service -and $service.Status -ne 'Stopped') { Invoke-ServiceCommand 'stop' }
    if ($service) { $service.Dispose() }
    if ($PurgeData) {
        & (Join-Path $InstallDirectory 'app\SAP-Lens.exe') --maintenance purge --data $installedValues.SAP_LENS_DATA_DIR --mode server --confirm-purge
        if ($LASTEXITCODE -ne 0) { throw 'Private-data removal failed; service remains stopped. Review ownership and locks before retrying.' }
    }
    Invoke-ServiceCommand 'uninstall'
    if ($PurgeData) { Write-Host 'Service and confirmed private data removed. Nonprivate lock stub, backups, external sources/secrets, XML and application bundle retained for an administrator retention decision.' }
    else { Write-Host 'Service removed. Application data, logs, source files and bundle are preserved.' }
} else { Invoke-ServiceCommand $Action.ToLowerInvariant() }
