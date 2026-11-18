# SAP Lens controlled deployment to a Windows host (build, validate, install service, deploy, verify, roll back, recover).
# Windows PowerShell 5.1 and PowerShell 7. Entry point: Deploy-SapLens.ps1. Operator guide: docs/experiments/dotnet-backend/WINDOWS_DEPLOYMENT.md.
#
# Every operating-system action goes through a small function below (git, service control, the release link, HTTP, the server's own maintenance
# commands), so the deployment state machine is tested with mocks (scripts/tests/SapLens.Deploy.Tests.ps1). Nothing here reads, prints or passes a
# secret: the certificate password stays in its file, which only the service reads.
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$script:Exe = 'SapLens.Api.exe'
$script:Lock = $null; $script:RunFolder = $null; $script:RunLog = $null; $script:RunId = ''
# Service names: SapLens for new installations; SapLens2 is the name of earlier installations, detected and kept until MigrateService renames it.
$script:ServiceName = 'SapLens'; $script:LegacyServiceName = 'SapLens2'
# Configuration lookup when -ConfigFile is not given: the environment variable (current, then earlier name), then the default files in this order.
$script:ConfigVariables = @('SAPLENS_DEPLOY_CONFIG', 'SAPLENS2_DEPLOY_CONFIG')
$script:ConfigDefaults = @('C:\saplens\deploy.local.json', 'C:\saplens2\deploy.local.json')
$script:FocusedTests = @('StartupTests', 'ApiTests', 'NetworkTests', 'ReverseProxyTests', 'SessionTests', 'AccountsTests', 'AccountCompatibilityTests',
    'PersistenceTests', 'ApplicationBackupTests', 'MaintenanceCommandsTests', 'V1CompatibilityTests', 'VersioningTests', 'V1DataMigrationTests')
# Phases after which the running service may already be stopped or switched; an interrupted run in one of them needs recovery.
$script:CriticalPhases = @('stopping', 'switched', 'starting', 'verifying')
$script:FinalPhases = @('complete', 'rolled_back', 'aborted', 'manual_recovery_required')

class DeployException : System.Exception {
    [int]$ExitCode
    DeployException([string]$message, [int]$code) : base($message) { $this.ExitCode = $code }
}

# Path joining without drive resolution (Join-Path needs the drive to exist), identical on Windows.
function Join-SL2([string]$Path, [string]$Child) { [System.IO.Path]::Combine($Path, $Child) }

function Stop-SL2([string]$Message, [int]$Code = 2) { throw [DeployException]::new($Message, $Code) }

function Write-SL2Log([string]$Message) {
    $line = '{0:yyyy-MM-ddTHH:mm:ssZ} {1}' -f [DateTime]::UtcNow, $Message
    Write-Host $line
    if ($script:RunLog -and (Test-Path -LiteralPath (Split-Path $script:RunLog))) { Add-Content -LiteralPath $script:RunLog -Value $line -Encoding UTF8 }
}

# ---- configuration

function Find-SL2ConfigFile {
    foreach ($name in $script:ConfigVariables) { $value = [Environment]::GetEnvironmentVariable($name); if ($value) { return $value } }
    foreach ($file in $script:ConfigDefaults) { if (Test-Path -LiteralPath $file) { return $file } }
    $script:ConfigDefaults[0]
}

# The service this host runs: the configured name, otherwise SapLens, otherwise an existing earlier SapLens2 installation (kept as it is).
function Resolve-SL2ServiceName {
    if ((Get-SL2Service $script:ServiceName).Exists) { return $script:ServiceName }
    if ((Get-SL2Service $script:LegacyServiceName).Exists) { return $script:LegacyServiceName }
    $script:ServiceName
}

function Read-SapLensSettings([string]$Path) {
    if (-not $Path) { $Path = Find-SL2ConfigFile }
    if (-not (Test-Path -LiteralPath $Path)) { Stop-SL2 "Deployment configuration not found: $Path (copy scripts\deploy\deploy.example.json; looked for `$env:$($script:ConfigVariables -join ', `$env:') and $($script:ConfigDefaults -join ', '))." }
    $raw = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    # Work, release and backup folders default to the configuration file's folder (C:\saplens2\deploy.local.json keeps C:\saplens2\releases and so on).
    $home_ = [System.IO.Path]::GetDirectoryName($Path)
    $config = [ordered]@{
        RepositoryPath = ''; Remote = 'origin'; Branch = 'experiment/dotnet-backend'; WorkRoot = (Join-SL2 $home_ 'deploy'); ReleasesRoot = (Join-SL2 $home_ 'releases')
        BackupRoot = (Join-SL2 $home_ 'predeploy-backups'); ServiceName = ''; ServiceAccount = ''; ListenAddress = ''; Port = 0
        AllowedHosts = @(); TrustedProxies = @(); DataDirectory = ''; CertificatePath = ''; CertificatePasswordFile = ''; ReadyTimeoutSeconds = 120; StopTimeoutSeconds = 90
    }
    foreach ($p in $raw.PSObject.Properties) {
        if (-not $config.Contains($p.Name)) { Stop-SL2 "Unknown deployment setting '$($p.Name)' in $Path." }
        $config[$p.Name] = $p.Value
    }
    foreach ($required in 'RepositoryPath', 'ListenAddress', 'DataDirectory', 'CertificatePath', 'CertificatePasswordFile') {
        if (-not $config[$required]) { Stop-SL2 "Deployment setting '$required' is required ($Path)." }
    }
    if ([int]$config.Port -lt 1 -or [int]$config.Port -gt 65535) { Stop-SL2 "Deployment setting 'Port' must be 1..65535." }
    foreach ($pathSetting in 'RepositoryPath', 'WorkRoot', 'ReleasesRoot', 'BackupRoot', 'DataDirectory', 'CertificatePath', 'CertificatePasswordFile') {
        if ([string]$config[$pathSetting] -notmatch '^([A-Za-z]:[\\/]|\\\\|/)') { Stop-SL2 "Deployment setting '$pathSetting' must be an absolute path." }
    }
    $config.AllowedHosts = @($config.AllowedHosts); $config.TrustedProxies = @($config.TrustedProxies)
    $config['ConfigFile'] = $Path
    $config['ServiceNameConfigured'] = [bool]$config.ServiceName
    if (-not $config.ServiceName) { $config.ServiceName = Resolve-SL2ServiceName }
    if ($config.ServiceName -notmatch '^[A-Za-z0-9_.-]{1,80}$') { Stop-SL2 "Deployment setting 'ServiceName' may contain letters, digits, '.', '_' and '-' only." }
    if (-not $config.ServiceAccount) { $config.ServiceAccount = "NT SERVICE\$($config.ServiceName)" }      # the service's own virtual account
    [pscustomobject]$config
}

# The service command line, rebuilt from the configuration. No secret is on it: the server reads the password file itself.
function Get-SL2ServiceArguments($Config) {
    $arguments = @('--data-dir', $Config.DataDirectory, '--network', '--listen', $Config.ListenAddress, '--port', [string]$Config.Port,
        '--allowed-hosts', ($Config.AllowedHosts -join ','), '--cert', $Config.CertificatePath, '--cert-password-file', $Config.CertificatePasswordFile)
    if (@($Config.TrustedProxies).Count -gt 0) { $arguments += @('--trusted-proxies', ($Config.TrustedProxies -join ',')) }
    $arguments
}

# The executable and the arguments of a service command line ("C:\path\SapLens.Api.exe" --a b "--c" "d e"), quotes removed.
function Split-SL2CommandLine([string]$CommandLine) {
    $tokens = [System.Collections.Generic.List[string]]::new()
    foreach ($m in [regex]::Matches($CommandLine, '"([^"]*)"|(\S+)')) { $tokens.Add($(if ($m.Groups[1].Success) { $m.Groups[1].Value } else { $m.Groups[2].Value })) }
    $tokens.ToArray()          # a plain sequence: callers wrap it in @(...) before indexing (one token would otherwise arrive as a string)
}

# The server options a managed service command line may carry (SapLens.Api ServerConfiguration): value options and the one flag. Names are
# case-sensitive, as the server parses them.
$script:ServiceValueOptions = @('--data-dir', '--listen', '--port', '--allowed-hosts', '--trusted-proxies', '--cert', '--cert-password-file')
$script:ServiceFlagOptions = @('--network')

# Parses service arguments (without the executable) into option -> value ('' for the flag). Throws on an unknown option, a stray value, a value
# option without its value, or an option given twice (the server would silently take the last one, so a repeat is a conflict, not a duplicate).
function ConvertTo-SL2ArgumentMap([string[]]$Arguments) {
    $map = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        $name = $Arguments[$i]
        if ($map.ContainsKey($name)) { throw "option $name is given more than once" }
        if ($script:ServiceFlagOptions -ccontains $name) { $map[$name] = ''; continue }
        if ($script:ServiceValueOptions -cnotcontains $name) { throw "unsupported argument '$name'" }
        if ($i + 1 -ge $Arguments.Count -or $Arguments[$i + 1].StartsWith('--', [StringComparison]::Ordinal)) { throw "option $name has no value" }
        $i++
        $map[$name] = $Arguments[$i]
    }
    $map
}

# A comma-separated list as the server reads it (entries trimmed, empty ones dropped), sorted and de-duplicated for an order-independent comparison.
function Get-SL2ListSet([string]$Value, [switch]$Address) {
    $items = foreach ($entry in $Value.Split(',')) {
        $item = $entry.Trim()
        if (-not $item) { continue }
        $parsed = $null
        if ($Address -and [System.Net.IPAddress]::TryParse($item, [ref]$parsed)) { $parsed.ToString() } else { $item.ToLowerInvariant() }
    }
    @($items | Sort-Object -Unique)
}

# Semantic comparison of an existing service's arguments with the configured ones. Returns the differences (nothing when equivalent). Order of the
# options and of the entries in --allowed-hosts/--trusted-proxies does not matter; every security-sensitive value must be present and equal:
# paths compare case-insensitively (Windows file system), the listen and proxy addresses as IP addresses, the port as a number, host names
# case-insensitively (DNS). Nothing is ignored: a missing, extra, repeated or unknown option is a difference.
function Compare-SL2ServiceArguments([string[]]$Existing, [string[]]$Wanted) {
    $differences = New-Object System.Collections.Generic.List[string]
    try { $have = ConvertTo-SL2ArgumentMap $Existing } catch { return "service: $($_.Exception.Message)" }
    try { $want = ConvertTo-SL2ArgumentMap $Wanted } catch { return "configuration: $($_.Exception.Message)" }
    foreach ($name in $script:ServiceFlagOptions + $script:ServiceValueOptions) {
        $inHave = $have.ContainsKey($name); $inWant = $want.ContainsKey($name)
        if (-not $inHave -and -not $inWant) { continue }
        if (-not $inHave) { $differences.Add("$name is missing on the service"); continue }
        if (-not $inWant) { $differences.Add("$name is on the service but not in the configuration"); continue }
        $a = $have[$name]; $b = $want[$name]
        $equal = switch ($name) {
            '--network' { $true }
            '--port' { ($a -match '^\d{1,5}$') -and ($b -match '^\d{1,5}$') -and ([int]$a -eq [int]$b) }
            '--listen' {
                $x = $null; $y = $null
                [System.Net.IPAddress]::TryParse($a, [ref]$x) -and [System.Net.IPAddress]::TryParse($b, [ref]$y) -and $x.Equals($y)
            }
            '--allowed-hosts' { ((Get-SL2ListSet $a) -join ',') -ceq ((Get-SL2ListSet $b) -join ',') }
            '--trusted-proxies' { ((Get-SL2ListSet $a -Address) -join ',') -ceq ((Get-SL2ListSet $b -Address) -join ',') }
            default { [string]::Equals($a, $b, [StringComparison]::OrdinalIgnoreCase) }      # --data-dir, --cert, --cert-password-file
        }
        if (-not $equal) { $differences.Add("$name differs: service '$a', configuration '$b'") }
    }
    $differences.ToArray()          # a plain sequence: callers wrap it in @(...)
}

function Get-SL2CurrentLink($Config) { Join-SL2 $Config.ReleasesRoot 'current' }
function Get-SL2ServiceExe($Config) { Join-SL2 (Join-SL2 (Get-SL2CurrentLink $Config) 'server') $script:Exe }

function Get-SL2BinaryPath($Config) {
    $quoted = (Get-SL2ServiceArguments $Config) | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } }
    '"' + (Get-SL2ServiceExe $Config) + '" ' + ($quoted -join ' ')
}

# ---- platform layer (mocked in tests)

# PowerShell unrolls a one-element array returned from a function into that element; indexing it then yields a [char] (the Windows PowerShell 5.1
# failure "[System.Char] does not contain a method named 'Trim'"). Callers therefore wrap results in @(...), and single values use Get-SL2GitValue.
function Get-SL2GitValue([string]$Repository, [string[]]$Arguments) {
    $lines = @(Invoke-SL2Git $Repository $Arguments | Where-Object { "$_".Trim() })
    if ($lines.Count -ne 1) { Stop-SL2 ("git {0} returned {1} lines, expected one." -f ($Arguments -join ' '), $lines.Count) }
    ([string]$lines[0]).Trim()
}

# Native commands: Windows PowerShell 5.1 turns every stderr line of a native command redirected with 2>&1 into a terminating error when
# $ErrorActionPreference is 'Stop' (git and the build tools write progress there). These wrappers run with 'Continue' and judge by the exit code.
function Invoke-SL2Git([string]$Repository, [string[]]$Arguments) {
    $ErrorActionPreference = 'Continue'
    $output = & git -C $Repository @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { Stop-SL2 ("git {0} failed: {1}" -f ($Arguments -join ' '), (($output | Out-String).Trim())) }
    @($output | ForEach-Object { "$_" })
}

function Get-SL2Shell { if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' } }

function Invoke-SL2Process([string]$File, [string[]]$Arguments, [string]$LogFile) {
    $ErrorActionPreference = 'Continue'
    $output = & $File @Arguments 2>&1
    $code = $LASTEXITCODE
    if ($LogFile) { $output | ForEach-Object { "$_" } | Add-Content -LiteralPath $LogFile -Encoding UTF8 }
    [pscustomobject]@{ ExitCode = $code; Output = @($output | ForEach-Object { "$_" }) }
}

# The server's local maintenance commands (--schema-info, --backup-local, --backup-verify): JSON on success, $null when the release does not know
# the command (an older build), otherwise a refusal.
function Invoke-SL2Maintenance([string]$ExePath, [string[]]$Arguments, [switch]$AllowUnsupported) {
    $result = Invoke-SL2Process $ExePath $Arguments ''
    if ($result.ExitCode -eq 0) {
        $text = ($result.Output | Where-Object { $_ -notmatch '^maintenance refused' }) -join "`n"
        try { return ($text | ConvertFrom-Json) } catch { if ($AllowUnsupported) { return $null } }
    }
    if ($AllowUnsupported) { return $null }
    Stop-SL2 ("{0} {1} failed: {2}" -f $ExePath, ($Arguments -join ' '), (($result.Output | Select-Object -Last 3) -join ' '))
}

function Get-SL2Service([string]$Name) {
    # Windows always has CIM; elsewhere (the Linux test harness) there is no service manager, so the service reads as missing.
    if (-not (Get-Command Get-CimInstance -ErrorAction SilentlyContinue)) { return [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 } }
    $service = Get-CimInstance Win32_Service -Filter "Name='$Name'" -ErrorAction SilentlyContinue
    if (-not $service) { return [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 } }
    [pscustomobject]@{ Exists = $true; State = $service.State; StartMode = $service.StartMode; Account = $service.StartName; PathName = $service.PathName; ProcessId = [int]$service.ProcessId }
}

function Get-SL2Listener([string]$Address, [int]$Port) {
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) { return @() }
    @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @($Address, '0.0.0.0', '::') } |
        ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
}

function Test-SL2ProcessAlive([int]$ProcessId) { [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) }

# Stops only this service, through the Service Control Manager (a graceful stop: running imports are handed back). Never kills any process.
function Stop-SL2Service([string]$Name, [int]$TimeoutSeconds) {
    $before = Get-SL2Service $Name
    if ($before.State -eq 'Stopped') { return }
    Stop-Service -Name $Name -ErrorAction Stop
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $now = Get-SL2Service $Name
        if ($now.State -eq 'Stopped' -and ($before.ProcessId -eq 0 -or -not (Test-SL2ProcessAlive $before.ProcessId))) { return }
        Start-Sleep -Seconds 1
    }
    Stop-SL2 "Service $Name did not stop within $TimeoutSeconds s (process $($before.ProcessId)). It was not killed; investigate before retrying." 4
}

function Start-SL2Service([string]$Name) { Start-Service -Name $Name -ErrorAction Stop }

# Changes only the command line of an existing service (sc.exe config binPath=); account, start mode and recovery settings stay as they are.
function Set-SL2ServiceBinary([string]$Name, [string]$BinaryPath) {
    $result = Invoke-SL2Process 'sc.exe' @('config', $Name, 'binPath=', $BinaryPath) ''
    if ($result.ExitCode -ne 0) { Stop-SL2 "sc.exe could not update the command line of $Name ($(($result.Output | Select-Object -Last 1)))." 4 }
}

function Get-SL2Link([string]$Link) {
    if (-not (Test-Path -LiteralPath $Link)) { return '' }
    $item = Get-Item -LiteralPath $Link -Force
    if ($item.LinkType -ne 'Junction' -and $item.LinkType -ne 'SymbolicLink') { Stop-SL2 "$Link exists but is not a link; move it aside first." }
    [string]@($item.Target)[0]
}

# Points the 'current' junction at a release folder: a new junction is created beside it and swapped in (remove + rename).
function Set-SL2Link([string]$Link, [string]$Target) {
    $staging = "$Link.next"
    if (Test-Path -LiteralPath $staging) { (Get-Item -LiteralPath $staging -Force).Delete() }
    New-Item -ItemType Junction -Path $staging -Target $Target | Out-Null
    if (Test-Path -LiteralPath $Link) { (Get-Item -LiteralPath $Link -Force).Delete() }   # removes the link only, never the release behind it
    Rename-Item -LiteralPath $staging -NewName (Split-Path $Link -Leaf)
}

# A readiness and identity probe of the local listener. TLS verification is skipped for this local probe only (it sends no credentials and reads
# two public documents); clients and the reverse proxy validate the certificate as before.
function Invoke-SL2Http([string]$Url) {
    $ErrorActionPreference = 'Continue'
    $body = & curl.exe --silent --show-error --insecure --max-time 10 --write-out "`n%{http_code}" $Url 2>&1
    $lines = @($body | ForEach-Object { "$_" })
    [pscustomobject]@{ Status = [int]($lines[-1]); Body = (($lines | Select-Object -SkipLast 1) -join "`n") }
}

# ---- journal and lock

function Get-SL2JournalPath($Config) { Join-SL2 $Config.WorkRoot 'deployment-journal.json' }

function Read-SL2Journal($Config) {
    $path = Get-SL2JournalPath $Config
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}

function Write-SL2Journal($Config, $Journal) {
    $Journal.updated = [DateTime]::UtcNow.ToString('o')
    $path = Get-SL2JournalPath $Config
    New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
    $temporary = "$path.tmp"
    [System.IO.File]::WriteAllText($temporary, ($Journal | ConvertTo-Json -Depth 8))
    Move-Item -LiteralPath $temporary -Destination $path -Force
    if ($script:RunFolder -and (Test-Path -LiteralPath $script:RunFolder)) { Copy-Item -LiteralPath $path -Destination (Join-SL2 $script:RunFolder 'journal.json') -Force }
}

function Set-SL2Phase($Config, $Journal, [string]$Phase) {
    $Journal.phase = $Phase
    # A journal read back from JSON may hold history as a single object or not at all: rebuild it as an array.
    # (A typed list: an if-expression or a function would unroll a one-entry history into a bare hashtable again.)
    $history = [System.Collections.Generic.List[object]]::new()
    if ($Journal.PSObject.Properties['history'] -and $null -ne $Journal.history) { foreach ($entry in @($Journal.history)) { $history.Add($entry) } }
    $history.Add(@{ phase = $Phase; at = [DateTime]::UtcNow.ToString('o') })
    $Journal | Add-Member -NotePropertyName history -NotePropertyValue $history.ToArray() -Force
    Write-SL2Journal $Config $Journal
    Write-SL2Log "phase: $Phase"
}

# One deployment operation at a time per host: an exclusive handle, released by Windows when the process ends (also after Ctrl+C or a dropped SSH session).
function Enter-SL2Lock($Config) {
    New-Item -ItemType Directory -Force $Config.WorkRoot | Out-Null
    $path = Join-SL2 $Config.WorkRoot 'deployment.lock'
    try { $script:Lock = [System.IO.File]::Open($path, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { Stop-SL2 'Another deployment operation is running on this host (deployment.lock is held).' }
}

function Exit-SL2Lock { if ($script:Lock) { $script:Lock.Dispose(); $script:Lock = $null } }

function New-SL2Run($Config, [string]$Action) {
    $id = '{0:yyyyMMdd-HHmmss}-{1}' -f [DateTime]::UtcNow, $Action
    $script:RunId = $id
    $script:RunFolder = Join-SL2 (Join-SL2 $Config.WorkRoot 'runs') $id
    New-Item -ItemType Directory -Force $script:RunFolder | Out-Null
    $script:RunLog = Join-SL2 $script:RunFolder 'deploy.log'
    Write-SL2Log "run $id, logs in $script:RunFolder"
    $id
}

# ---- source, build, validation

# The .NET project inside a checkout: experiments\dotnet-backend today, backend\ after the promotion (BACKEND_PROMOTION.md). The Python backend has
# no SapLens.slnx, so the choice is unambiguous.
function Get-SL2ProjectRoot([string]$Worktree) {
    foreach ($relative in 'experiments/dotnet-backend', 'backend') {
        $candidate = Join-SL2 $Worktree $relative
        if (Test-Path -LiteralPath (Join-SL2 $candidate 'SapLens.slnx')) { return $candidate }
    }
    Stop-SL2 "No .NET project (SapLens.slnx) in $Worktree under experiments\dotnet-backend or backend." 1
}

function Resolve-SL2Commit($Config, [string]$Branch, [string]$Commit) {
    if (-not $Branch) { $Branch = $Config.Branch }
    if ($Branch -in @('main', 'work')) { Stop-SL2 "Deployments are built from the development branch, not '$Branch'." }
    Invoke-SL2Git $Config.RepositoryPath @('fetch', '--quiet', $Config.Remote, "refs/heads/${Branch}:refs/remotes/$($Config.Remote)/$Branch") | Out-Null
    $tip = Get-SL2GitValue $Config.RepositoryPath @('rev-parse', "$($Config.Remote)/$Branch^{commit}")
    if (-not $Commit) { return $tip }
    if ($Commit -notmatch '^[0-9a-f]{7,40}$') { Stop-SL2 "Commit '$Commit' is not a hexadecimal SHA." }
    $full = Get-SL2GitValue $Config.RepositoryPath @('rev-parse', "$Commit^{commit}")
    $contained = Invoke-SL2Process 'git' @('-C', $Config.RepositoryPath, 'merge-base', '--is-ancestor', $full, $tip) ''
    if ($contained.ExitCode -ne 0) { Stop-SL2 "Commit $full is not on $($Config.Remote)/$Branch; only pushed commits of the branch are deployed." }
    $full
}

# An isolated worktree per commit under WorkRoot: the developer's checkout and its working tree are never touched.
function New-SL2Worktree($Config, [string]$Commit) {
    $path = Join-SL2 (Join-SL2 $Config.WorkRoot 'worktrees') $Commit.Substring(0, 12)
    if (Test-Path -LiteralPath $path) {
        $head = Get-SL2GitValue $path @('rev-parse', 'HEAD')
        $dirty = @(Invoke-SL2Git $path @('status', '--porcelain'))
        if ($head -ne $Commit -or @($dirty | Where-Object { $_ }).Count -gt 0) {
            Stop-SL2 "Build worktree $path is not a clean checkout of $Commit. Remove it with: git -C `"$($Config.RepositoryPath)`" worktree remove --force `"$path`""
        }
        return $path
    }
    Invoke-SL2Git $Config.RepositoryPath @('worktree', 'add', '--detach', $path, $Commit) | Out-Null
    $path
}

function Get-SL2TestFilter([string]$Tests) {
    switch ($Tests) {
        'full' { return '' }
        'focused' { return (($script:FocusedTests | ForEach-Object { "FullyQualifiedName~SapLens.Tests.$_" }) -join '|') }
        'none' { return $null }
        default { Stop-SL2 "Unknown test selection '$Tests' (focused, full or none)." }
    }
}

function Invoke-SL2Build($Config, [string]$Worktree, [string]$Commit, [string]$Tests) {
    $builder = Join-SL2 (Get-SL2ProjectRoot $Worktree) 'scripts\build-release.ps1'
    $output = Join-SL2 (Join-SL2 $Config.WorkRoot 'builds') $Commit.Substring(0, 12)
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $builder, '-Output', $output)
    $filter = Get-SL2TestFilter $Tests
    if ($null -eq $filter) { $arguments += '-SkipTests' } elseif ($filter) { $arguments += @('-TestFilter', $filter) }
    $log = Join-SL2 $script:RunFolder 'build.log'
    Write-SL2Log "building $Commit with $Tests tests (log: $log)"
    $shell = Get-SL2Shell
    $result = Invoke-SL2Process $shell $arguments $log
    if ($result.ExitCode -ne 0) { Stop-SL2 "Build or tests failed (exit $($result.ExitCode)); see $log. Nothing was deployed." 1 }
    $line = $result.Output | Where-Object { $_ -match '^Release build complete: (.+)$' } | Select-Object -Last 1
    if (-not $line) { Stop-SL2 "The builder did not report a release folder; see $log." 1 }
    ($line -replace '^Release build complete: ', '').Trim()
}

# The release must be the requested commit and version, with every artifact matching its manifest and SHA256SUMS.
function Test-SL2Release([string]$Release, [string]$Commit, [string]$Worktree) {
    $verifier = Join-SL2 (Get-SL2ProjectRoot $Worktree) 'scripts\verify-release.ps1'
    $shell = Get-SL2Shell
    $result = Invoke-SL2Process $shell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $verifier, '-ReleasePath', $Release) (Join-SL2 $script:RunFolder 'verify.log')
    if ($result.ExitCode -ne 0) { Stop-SL2 "Release verification failed for $Release." 1 }
    $manifest = Get-Content -LiteralPath (Join-SL2 $Release 'build-manifest.json') -Raw | ConvertFrom-Json
    $expected = (Get-Content -LiteralPath (Join-SL2 (Get-SL2ProjectRoot $Worktree) 'product-version.json') -Raw | ConvertFrom-Json).version
    if ($manifest.source_sha -ne $Commit) { Stop-SL2 "Release commit $($manifest.source_sha) is not the locked commit $Commit." 1 }
    if ($manifest.source_dirty) { Stop-SL2 'The release was built from a modified working tree.' 1 }
    if ($manifest.version -ne $expected) { Stop-SL2 "Release version $($manifest.version) is not product-version.json $expected." 1 }
    $manifest
}

# The versioned deployment folder: <ReleasesRoot>\<release name> with server\, build-manifest.json and SHA256SUMS. An existing folder is reused only
# when its manifest names the same commit; it is never overwritten.
function Publish-SL2Release($Config, [string]$Release, $Manifest) {
    $target = Join-SL2 $Config.ReleasesRoot (Split-Path $Release -Leaf)
    if (Test-Path -LiteralPath $target) {
        $existing = Get-Content -LiteralPath (Join-SL2 $target 'build-manifest.json') -Raw | ConvertFrom-Json
        if ($existing.source_sha -ne $Manifest.source_sha) { Stop-SL2 "$target exists for another commit." 1 }
        return $target
    }
    New-Item -ItemType Directory -Force $target | Out-Null
    Copy-Item -LiteralPath (Join-SL2 $Release 'server') -Destination $target -Recurse
    foreach ($file in 'build-manifest.json', 'SHA256SUMS', 'README.txt') { Copy-Item -LiteralPath (Join-SL2 $Release $file) -Destination $target }
    $target
}

# ---- service installation

# The other SAP Lens service name on this host (SapLens beside SapLens2, or the reverse), when it exists: never create a second service.
function Get-SL2OtherService($Config) {
    foreach ($name in $script:ServiceName, $script:LegacyServiceName) { if ($name -ne $Config.ServiceName -and (Get-SL2Service $name).Exists) { return $name } }
    $null
}

# Creates the service (automatic start, its virtual account, restart on failure) or, for an existing one, sets its command line and account.
function Set-SL2ServiceEntry($Config, [string]$Binary, [bool]$Exists, [string]$StartMode = 'auto') {
    if (-not $Exists) {
        New-Service -Name $Config.ServiceName -DisplayName 'SAP Lens Server' -BinaryPathName $Binary -StartupType Manual -Description 'SAP Lens (.NET) server' | Out-Null
    }
    foreach ($arguments in @(@('config', $Config.ServiceName, 'binPath=', $Binary, 'start=', $StartMode), @('config', $Config.ServiceName, 'obj=', $Config.ServiceAccount),
            @('failure', $Config.ServiceName, 'reset=', '86400', 'actions=', 'restart/60000/restart/60000//'))) {
        $result = Invoke-SL2Process 'sc.exe' $arguments ''     # virtual account: no password
        if ($result.ExitCode -ne 0) { Stop-SL2 "sc.exe $($arguments[0]) $($Config.ServiceName) failed ($(($result.Output | Select-Object -Last 1)))." 1 }
    }
}

function Install-SL2Service($Config, [switch]$Reconfigure) {
    $service = Get-SL2Service $Config.ServiceName
    if ($service.Exists -and -not $Reconfigure) { Stop-SL2 "Service $($Config.ServiceName) exists; use -Reconfigure to update its command line and permissions." }
    $other = Get-SL2OtherService $Config
    if (-not $service.Exists -and $other) { Stop-SL2 "Service $other already runs SAP Lens on this host; a second service is never created. Remove 'ServiceName' from $($Config.ConfigFile) to use $other, or rename it with -Action MigrateService." }
    if (-not (Get-SL2Link (Get-SL2CurrentLink $Config))) { Stop-SL2 'No release is linked yet: run the build action and then deploy with -FirstInstall, which installs the service.' }
    $listeners = @(Get-SL2Listener $Config.ListenAddress ([int]$Config.Port))
    $owned = $service.Exists -and $service.ProcessId -gt 0 -and ($listeners -contains $service.ProcessId)
    if ($listeners.Count -gt 0 -and -not $owned) {
        Stop-SL2 ("Port {0} on {1} is used by process {2}, not by the service. Stop that server yourself (for example start-server-test.ps1 -Stop); it is never terminated by this script." -f $Config.Port, $Config.ListenAddress, ($listeners -join ','))
    }
    foreach ($file in $Config.CertificatePath, $Config.CertificatePasswordFile) { if (-not (Test-Path -LiteralPath $file)) { Stop-SL2 "Missing file $file." } }
    $binary = Get-SL2BinaryPath $Config
    Set-SL2ServiceEntry $Config $binary $service.Exists
    Grant-SL2Access $Config
    Write-SL2Log "service $($Config.ServiceName) configured: $binary, account $($Config.ServiceAccount)"
}

# Renames an earlier SapLens2 installation to the SapLens service, keeping its release, data, TLS, hosts and trusted proxies. The new service gets
# its own virtual account (NT SERVICE\SapLens) with the same grants. Order: create SapLens (manual start), grant, stop SapLens2 and disable it,
# start SapLens and verify readiness and identity; only then SapLens gets automatic start and SapLens2 is deleted (its settings are recorded in the
# run folder). Any failure before that removes the new service and starts SapLens2 again, so there is never a second running or enabled service.
function Invoke-SL2MigrateService($Config) {
    if ($Config.ServiceNameConfigured) { Stop-SL2 "$($Config.ConfigFile) names the service ('ServiceName'/'ServiceAccount'). Remove both settings, then repeat: the service is detected automatically before and after the migration." }
    $legacy = Get-SL2Service $script:LegacyServiceName
    $target = Get-SL2Service $script:ServiceName
    if ($target.Exists -and $legacy.Exists) { Stop-SL2 "Both $($script:ServiceName) and $($script:LegacyServiceName) exist. Nothing was changed; keep the one that runs the managed release and remove the other by hand (sc.exe delete) after checking -Action Status." }
    if ($target.Exists) { Stop-SL2 "The service is already named $($script:ServiceName); nothing to migrate." }
    if (-not $legacy.Exists) { Stop-SL2 "No $($script:LegacyServiceName) service exists on this host; nothing to migrate." }
    $legacyConfig = $Config.PSObject.Copy(); $legacyConfig.ServiceName = $script:LegacyServiceName
    $binary = Get-SL2BinaryPath $Config
    if ($legacy.PathName -ne $binary) { Stop-SL2 "$($script:LegacyServiceName) runs $($legacy.PathName), not the managed release link. Deploy once with -AdoptService first, then migrate." }
    $journal = Read-SL2Journal $Config
    if ($journal -and $journal.phase -in $script:CriticalPhases) { Stop-SL2 "An earlier deployment ($($journal.run)) was interrupted in phase '$($journal.phase)'. Run -Action Recover first." }
    $wasRunning = $legacy.State -eq 'Running'
    $legacyStart = if ($legacy.StartMode -match '^Auto') { 'auto' } elseif ($legacy.StartMode -match '^Disabled') { 'disabled' } else { 'demand' }
    $record = [pscustomobject]@{ service = $script:LegacyServiceName; binary_path = $legacy.PathName; account = $legacy.Account; start_mode = $legacy.StartMode; state = $legacy.State }
    [System.IO.File]::WriteAllText((Join-SL2 $script:RunFolder 'legacy-service.json'), ($record | ConvertTo-Json))
    $current = Get-SL2Link (Get-SL2CurrentLink $Config)
    $manifest = Get-Content -LiteralPath (Join-SL2 $current 'build-manifest.json') -Raw | ConvertFrom-Json
    $migrated = $Config.PSObject.Copy(); $migrated.ServiceName = $script:ServiceName; $migrated.ServiceAccount = "NT SERVICE\$($script:ServiceName)"
    Write-SL2Log "migrating service $($script:LegacyServiceName) ($($legacy.State), $($legacy.StartMode)) to $($script:ServiceName); release $current"
    $created = $false; $legacyTouched = $false
    try {
        Set-SL2ServiceEntry $migrated $binary $false 'demand'; $created = $true
        Grant-SL2Access $migrated
        $legacyTouched = $true
        Stop-SL2Service $script:LegacyServiceName ([int]$Config.StopTimeoutSeconds)
        $null = Invoke-SL2Process 'sc.exe' @('config', $script:LegacyServiceName, 'start=', 'disabled') ''
        Start-SL2Service $script:ServiceName
        $ready = Wait-SL2Ready $migrated $manifest.source_sha $manifest.version
    } catch {
        $reason = $_.Exception.Message
        Write-SL2Log "service migration failed: $reason; returning to $($script:LegacyServiceName)"
        try {
            if ($created) {
                if ((Get-SL2Service $script:ServiceName).State -ne 'Stopped') { Stop-SL2Service $script:ServiceName ([int]$Config.StopTimeoutSeconds) }
                $null = Invoke-SL2Process 'sc.exe' @('delete', $script:ServiceName) ''
            }
            if ($legacyTouched) {
                $null = Invoke-SL2Process 'sc.exe' @('config', $script:LegacyServiceName, 'start=', $legacyStart) ''
                if ($wasRunning) { Start-SL2Service $script:LegacyServiceName; $null = Wait-SL2Ready $legacyConfig $manifest.source_sha $manifest.version }
            }
        } catch {
            $text = "SAP Lens service migration needs a manual decision. Migration error: $reason`r`nRestore error: $($_.Exception.Message)`r`n" +
                "Original service settings: $(Join-SL2 $script:RunFolder 'legacy-service.json')`r`nTo return: sc.exe delete $($script:ServiceName) (if present); " +
                "sc.exe config $($script:LegacyServiceName) start= $legacyStart; Start-Service $($script:LegacyServiceName)`r`n"
            [System.IO.File]::WriteAllText((Join-SL2 $script:RunFolder 'RECOVERY-REQUIRED.txt'), $text)
            Stop-SL2 "Service migration failed and $($script:LegacyServiceName) could not be restored automatically; see RECOVERY-REQUIRED.txt in $script:RunFolder." 4
        }
        Stop-SL2 "Service migration failed; $($script:LegacyServiceName) is unchanged and $(if ($wasRunning) { 'running again' } else { 'as it was' }): $reason" 1
    }
    $null = Invoke-SL2Process 'sc.exe' @('config', $script:ServiceName, 'start=', $legacyStart) ''
    $deleted = Invoke-SL2Process 'sc.exe' @('delete', $script:LegacyServiceName) ''
    if ($deleted.ExitCode -ne 0) { Write-SL2Log "warning: $($script:LegacyServiceName) is disabled but could not be deleted ($(($deleted.Output | Select-Object -Last 1))); remove it with sc.exe delete" }
    Write-SL2Log "service migrated: $($script:ServiceName) runs $($manifest.version) $($manifest.source_sha), account $($migrated.ServiceAccount); $($script:LegacyServiceName) removed"
    [pscustomobject]@{ service = $script:ServiceName; previous_service = $script:LegacyServiceName; account = $migrated.ServiceAccount; release = $current
        commit = $manifest.source_sha; version = $manifest.version; process_id = $ready.process_id; legacy_service_deleted = ($deleted.ExitCode -eq 0); data_directory = $Config.DataDirectory }
}

# Least privilege for the virtual service account: modify the data directory, read the releases, the certificate, its password file and the backup
# key. Grants are added; existing permissions (administrators, the owner) are not removed.
function Grant-SL2Access($Config) {
    $account = $Config.ServiceAccount
    $grants = @(
        @($Config.DataDirectory, "${account}:(OI)(CI)M"), @($Config.ReleasesRoot, "${account}:(OI)(CI)RX"),
        @($Config.CertificatePath, "${account}:R"), @($Config.CertificatePasswordFile, "${account}:R")
    )
    $pointer = Join-SL2 $Config.DataDirectory 'backup-key-location.json'
    if (Test-Path -LiteralPath $pointer) { $grants += , @(((Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json).path), "${account}:R") }
    foreach ($grant in $grants) {
        $result = Invoke-SL2Process 'icacls' @($grant[0], '/grant', $grant[1]) ''
        if ($result.ExitCode -ne 0) { Stop-SL2 "icacls could not grant $($grant[1]) on $($grant[0])." }
    }
}

# ---- status

function Get-SL2Status($Config) {
    $service = Get-SL2Service $Config.ServiceName
    $current = Get-SL2Link (Get-SL2CurrentLink $Config)
    $manifest = $null
    if ($current -and (Test-Path -LiteralPath (Join-SL2 $current 'build-manifest.json'))) { $manifest = Get-Content -LiteralPath (Join-SL2 $current 'build-manifest.json') -Raw | ConvertFrom-Json }
    $listeners = @(Get-SL2Listener $Config.ListenAddress ([int]$Config.Port))
    $model = if ($service.Exists) { 'windows-service' } elseif ($listeners.Count -gt 0) { 'unmanaged-process' } else { 'none' }
    $identity = $null; $ready = $null
    if ($listeners.Count -gt 0) {
        $base = "https://$($Config.ListenAddress):$($Config.Port)"
        $readyResponse = Invoke-SL2Http "$base/health/ready"; $ready = $readyResponse.Status -eq 200
        $identityResponse = Invoke-SL2Http "$base/product-version.json"
        if ($identityResponse.Status -eq 200) { $identity = $identityResponse.Body | ConvertFrom-Json }
    }
    $journal = Read-SL2Journal $Config
    [pscustomobject]@{
        service_model = $model; service_name = $Config.ServiceName; service = $service; expected_binary_path = Get-SL2BinaryPath $Config
        legacy_service_name = ($Config.ServiceName -eq $script:LegacyServiceName); other_service = Get-SL2OtherService $Config
        binary_path_matches = ($service.Exists -and $service.PathName -eq (Get-SL2BinaryPath $Config))
        current_release = $current; current_commit = $(if ($manifest) { $manifest.source_sha } else { $null }); current_version = $(if ($manifest) { $manifest.version } else { $null })
        listeners = $listeners; ready = $ready; running_identity = $identity
        journal_phase = $(if ($journal) { $journal.phase } else { $null }); recovery_needed = ($journal -and $journal.phase -in $script:CriticalPhases)
    }
}

# ---- deployment state machine

function Wait-SL2Ready($Config, [string]$Commit, [string]$Version) {
    $deadline = [DateTime]::UtcNow.AddSeconds([int]$Config.ReadyTimeoutSeconds)
    $base = "https://$($Config.ListenAddress):$($Config.Port)"
    $last = 'not started'
    while ([DateTime]::UtcNow -lt $deadline) {
        $service = Get-SL2Service $Config.ServiceName
        if ($service.State -eq 'Stopped') { Stop-SL2 'The service stopped during startup (see <data-dir>\logs\server-*.log).' 1 }
        $listeners = @(Get-SL2Listener $Config.ListenAddress ([int]$Config.Port))
        if ($service.State -eq 'Running' -and $service.ProcessId -gt 0 -and $listeners -contains $service.ProcessId) {
            $ready = Invoke-SL2Http "$base/health/ready"
            if ($ready.Status -eq 200) {
                $identity = (Invoke-SL2Http "$base/product-version.json").Body | ConvertFrom-Json
                if ($Commit -and ($identity.source_sha -ne $Commit -or $identity.version -ne $Version)) {
                    Stop-SL2 "The service answers as $($identity.version) $($identity.source_sha), expected $Version $Commit." 1
                }
                return [pscustomobject]@{ process_id = $service.ProcessId; identity = $identity }
            }
            $last = "health/ready answered $($ready.Status)"
        } elseif ($listeners.Count -gt 0 -and -not ($listeners -contains $service.ProcessId)) {
            Stop-SL2 "Port $($Config.Port) is held by process $($listeners -join ','), not by the service." 1
        } else { $last = "service $($service.State), not listening yet" }
        Start-Sleep -Seconds 2
    }
    Stop-SL2 "The service did not become ready within $($Config.ReadyTimeoutSeconds) s ($last)." 1
}

# Whether the release in $ReleaseFolder can open the data as it is now. A release that knows --schema-info answers itself; for an older build the
# proof is that no migration was applied since the deployment started.
function Test-SL2RollbackSafe($Config, [string]$ReleaseFolder, $AppliedBefore, [string]$Executable = '') {
    $exe = if ($Executable) { $Executable } else { Join-SL2 (Join-SL2 $ReleaseFolder 'server') $script:Exe }
    $info = Invoke-SL2Maintenance $exe @('--schema-info', '--data-dir', $Config.DataDirectory) -AllowUnsupported
    if ($info) { return [pscustomobject]@{ Safe = [bool]$info.compatible; Reason = $(if ($info.compatible) { 'the previous release knows every applied migration' } else { 'the database has migrations the previous release does not know: ' + (@($info.unknown_applied) -join ', ') }) } }
    $newExe = Join-SL2 (Join-SL2 (Get-SL2Link (Get-SL2CurrentLink $Config)) 'server') $script:Exe
    $now = Invoke-SL2Maintenance $newExe @('--schema-info', '--data-dir', $Config.DataDirectory)
    $added = @($now.applied | Where-Object { @($AppliedBefore) -notcontains $_ })
    if ($added.Count -eq 0) { return [pscustomobject]@{ Safe = $true; Reason = 'no migration was applied during the deployment' } }
    [pscustomobject]@{ Safe = $false; Reason = 'migrations applied during the deployment: ' + ($added -join ', ') }
}

function Write-SL2RecoveryInstructions($Config, $Journal, [string]$Reason) {
    $backup = if ($Journal.PSObject.Properties['backup'] -and $Journal.backup) { "$($Journal.backup.file) (SHA-256 $($Journal.backup.sha256))" } else { 'none was taken in this run (no database existed, or this is a manual rollback); use the newest verified backup' }
    $text = @"
SAP Lens deployment $($Journal.run) needs a manual decision. Nothing further was changed automatically.

Reason: $Reason
Service: $($Config.ServiceName) is stopped. Linked release: $(Get-SL2Link (Get-SL2CurrentLink $Config))
Previous release: $($Journal.from_release)
Pre-deployment backup (encrypted, verified): $backup

Choose one:
1. Fix forward: correct the cause (see $script:RunFolder and $($Config.DataDirectory)\logs), then start the service on the new release:
     Start-Service $($Config.ServiceName)
2. Return to the previous release with the data as it was before the deployment (this discards changes made since the backup):
     a. Keep the current data aside: move $($Config.DataDirectory) to a new name (do not delete it).
     b. Restore the backup into a new data directory with the previous release (Settings, Backup and restore, or a support procedure),
        then relink: Deploy-SapLens.ps1 -Action Rollback -ToRelease "$($Journal.from_release)" -Yes
"@
    $path = Join-SL2 $script:RunFolder 'RECOVERY-REQUIRED.txt'
    [System.IO.File]::WriteAllText($path, $text)
    Write-SL2Log "manual recovery required: $path"
}

function Invoke-SL2RollbackCore($Config, $Journal, [string]$Target) {
    Write-SL2Log "rolling back to $Target"
    Stop-SL2Service $Config.ServiceName ([int]$Config.StopTimeoutSeconds)
    $before = if ($Journal.PSObject.Properties['service_binary_before']) { [string]$Journal.service_binary_before } else { '' }
    $adopted = $before -and -not $Target
    $safety = if ($adopted) { Test-SL2RollbackSafe $Config '' $Journal.applied_before @(Split-SL2CommandLine $before)[0] } else { Test-SL2RollbackSafe $Config $Target $Journal.applied_before }
    if (-not $safety.Safe) {
        Set-SL2Phase $Config $Journal 'manual_recovery_required'
        Write-SL2RecoveryInstructions $Config $Journal $safety.Reason
        Stop-SL2 "Rollback is not safe: $($safety.Reason). The service is stopped; see RECOVERY-REQUIRED.txt in $script:RunFolder." 4
    }
    if ($adopted) {
        # The service was adopted in this run: its original command line (and release) comes back unchanged.
        Set-SL2ServiceBinary $Config.ServiceName $before
        $identity = if ($Journal.PSObject.Properties['identity_before'] -and $Journal.identity_before) { $Journal.identity_before } else { $null }
        $manifest = [pscustomobject]@{ source_sha = $(if ($identity) { $identity.source_sha } else { '' }); version = $(if ($identity) { $identity.version } else { '' }) }
        $Target = @(Split-SL2CommandLine $before)[0]
    } else {
        if ($before) { Set-SL2ServiceBinary $Config.ServiceName (Get-SL2BinaryPath $Config) }
        Set-SL2Link (Get-SL2CurrentLink $Config) $Target
        $manifest = Get-Content -LiteralPath (Join-SL2 $Target 'build-manifest.json') -Raw | ConvertFrom-Json
    }
    Start-SL2Service $Config.ServiceName
    try { Wait-SL2Ready $Config $manifest.source_sha $manifest.version | Out-Null }
    catch {
        Set-SL2Phase $Config $Journal 'manual_recovery_required'
        Write-SL2RecoveryInstructions $Config $Journal "the previous release did not become ready after the rollback: $($_.Exception.Message)"
        Stop-SL2 'The previous release did not become ready after the rollback; see RECOVERY-REQUIRED.txt.' 4
    }
    Set-SL2Phase $Config $Journal 'rolled_back'
    Write-SL2Log "rolled back to $Target ($($manifest.version) $($manifest.source_sha)); the service is ready"
}

function Invoke-SL2Deploy($Config, [string]$ReleaseFolder, [string]$Commit, [switch]$DryRun, [switch]$FirstInstall, [switch]$AdoptService) {
    $previousJournal = Read-SL2Journal $Config
    if ($previousJournal -and $previousJournal.phase -in $script:CriticalPhases) {
        Stop-SL2 "An earlier deployment ($($previousJournal.run)) was interrupted in phase '$($previousJournal.phase)'. Run -Action Recover first."
    }
    $manifest = Get-Content -LiteralPath (Join-SL2 $ReleaseFolder 'build-manifest.json') -Raw | ConvertFrom-Json
    $service = Get-SL2Service $Config.ServiceName
    $link = Get-SL2CurrentLink $Config
    $previous = Get-SL2Link $link
    if (-not $service.Exists -and -not $FirstInstall) { Stop-SL2 "Service $($Config.ServiceName) is not installed. Run the first deployment with -FirstInstall (see WINDOWS_DEPLOYMENT.md)." }
    $adopt = $false
    if ($service.Exists -and $service.PathName -ne (Get-SL2BinaryPath $Config)) {
        # A service installed by hand (or by an earlier procedure) runs another executable path. It is adopted only on request, and only when its
        # arguments are equivalent to the configured ones (data directory, network, TLS, hosts, proxies), so nothing about its runtime changes silently.
        # The comparison is semantic (option order and list order do not matter; every value must match), see Compare-SL2ServiceArguments.
        $existing = @(Split-SL2CommandLine $service.PathName)
        $wanted = @(Get-SL2ServiceArguments $Config)
        $differences = @(Compare-SL2ServiceArguments @($existing | Select-Object -Skip 1) $wanted)
        if ($differences.Count -gt 0) {
            Stop-SL2 ("The service arguments differ from the deployment configuration:`n  - {0}`n  service: {1}`n  config:  {2}`nAlign deploy.local.json with the running service (or apply the configuration with -Action InstallService -Reconfigure -Yes)." -f ($differences -join "`n  - "), (($existing | Select-Object -Skip 1) -join ' '), ($wanted -join ' '))
        }
        if (-not $AdoptService) { Stop-SL2 "Service $($Config.ServiceName) runs $($existing[0]), not the managed release link. Review -Action Status and deploy once with -AdoptService to bring it under managed releases (its account and arguments are kept)." }
        $adopt = $true
    }
    $newExe = Join-SL2 (Join-SL2 $ReleaseFolder 'server') $script:Exe
    $schema = Invoke-SL2Maintenance $newExe @('--schema-info', '--data-dir', $Config.DataDirectory)
    if (-not $schema.compatible) { Stop-SL2 ('The data directory was written by a newer SAP Lens build (unknown migrations: {0}); this release would refuse it.' -f (@($schema.unknown_applied) -join ', ')) }
    $journal = [pscustomobject]@{
        run = $script:RunId; commit = $Commit; version = $manifest.version; to_release = $ReleaseFolder; from_release = $previous
        service_state_before = $service.State; applied_before = @($schema.applied); backup = $null; phase = 'prepared'; history = @(); updated = ''
        service_binary_before = $(if ($adopt) { $service.PathName } else { '' }); identity_before = $null
    }
    if ($service.State -eq 'Running') {
        $identity = Invoke-SL2Http "https://$($Config.ListenAddress):$($Config.Port)/product-version.json"
        if ($identity.Status -eq 200) { $journal.identity_before = $identity.Body | ConvertFrom-Json }
    }
    Write-SL2Log ("deploying {0} {1} from {2}; service {3} ({4}); {5} pending migration(s)" -f $manifest.version, $Commit, $(if ($previous) { $previous } else { '(none)' }), $service.State, $service.Account, @($schema.pending).Count)
    if ($DryRun) {
        Write-SL2Log 'dry run: no backup, no service change'
        return [pscustomobject]@{ dry_run = $true; plan = $journal }
    }
    Set-SL2Phase $Config $journal 'backup'
    if ($schema.database_exists) {
        $backup = Invoke-SL2Maintenance $newExe @('--backup-local', $Config.BackupRoot, '--data-dir', $Config.DataDirectory)
        $verified = Invoke-SL2Maintenance $newExe @('--backup-verify', $backup.file, '--data-dir', $Config.DataDirectory)
        if (-not $verified.verified -or $verified.sha256 -ne $backup.sha256) { Stop-SL2 'The pre-deployment backup could not be verified; nothing was changed.' 1 }
        $journal.backup = [pscustomobject]@{ file = $backup.file; sha256 = $backup.sha256; size = $backup.size }
        Write-SL2Log "pre-deployment backup verified: $($backup.file)"
    }
    $completed = $false
    try {
        if ($service.Exists) {
            Set-SL2Phase $Config $journal 'stopping'
            Stop-SL2Service $Config.ServiceName ([int]$Config.StopTimeoutSeconds)
        }
        Set-SL2Phase $Config $journal 'switched'
        Set-SL2Link $link $ReleaseFolder
        if ($adopt) { Set-SL2ServiceBinary $Config.ServiceName (Get-SL2BinaryPath $Config) }
        if ($FirstInstall -and -not $service.Exists) { Install-SL2Service $Config }
        Set-SL2Phase $Config $journal 'starting'
        Start-SL2Service $Config.ServiceName
        Set-SL2Phase $Config $journal 'verifying'
        $ready = Wait-SL2Ready $Config $Commit $manifest.version
        Set-SL2Phase $Config $journal 'complete'
        $completed = $true
        Write-SL2Log "deployed $($manifest.version) $Commit; service process $($ready.process_id) is ready"
        return [pscustomobject]@{ deployed = $true; release = $ReleaseFolder; identity = $ready.identity; backup = $journal.backup }
    }
    catch [DeployException] {
        Write-SL2Log "deployment failed: $($_.Exception.Message)"
        if ($previous -or $adopt) { Invoke-SL2RollbackCore $Config $journal $previous; $completed = $true; Stop-SL2 "Deployment failed and was rolled back: $($_.Exception.Message)" 1 }
        Set-SL2Phase $Config $journal 'manual_recovery_required'
        Write-SL2RecoveryInstructions $Config $journal "first deployment failed: $($_.Exception.Message)"
        $completed = $true
        throw
    }
    finally {
        # Ctrl+C or a terminating error outside the handled path: return to the previous release if one exists, otherwise leave a recovery note.
        if (-not $completed -and $journal.phase -in $script:CriticalPhases) {
            try { if ($previous -or $adopt) { Invoke-SL2RollbackCore $Config $journal $previous } } catch { Write-SL2Log "automatic rollback after interruption failed: $($_.Exception.Message)" }
        }
    }
}

function Invoke-SL2Recover($Config) {
    $journal = Read-SL2Journal $Config
    if (-not $journal) { Write-SL2Log 'no deployment journal: nothing to recover'; return [pscustomobject]@{ recovered = $false; reason = 'no journal' } }
    if ($journal.phase -in $script:FinalPhases) { Write-SL2Log "last deployment $($journal.run) ended in '$($journal.phase)': nothing to recover"; return [pscustomobject]@{ recovered = $false; phase = $journal.phase } }
    if ($journal.phase -in @('prepared', 'backup')) {
        Set-SL2Phase $Config $journal 'aborted'
        $service = Get-SL2Service $Config.ServiceName
        if ($service.Exists -and $service.State -eq 'Stopped' -and $journal.service_state_before -eq 'Running') { Start-SL2Service $Config.ServiceName }
        return [pscustomobject]@{ recovered = $true; phase = 'aborted' }
    }
    $adopted = $journal.PSObject.Properties['service_binary_before'] -and $journal.service_binary_before
    if (-not $journal.from_release -and -not $adopted) {
        Set-SL2Phase $Config $journal 'manual_recovery_required'
        Write-SL2RecoveryInstructions $Config $journal 'an interrupted first deployment has no previous release to return to'
        Stop-SL2 'Interrupted first deployment: see RECOVERY-REQUIRED.txt.' 4
    }
    Invoke-SL2RollbackCore $Config $journal $journal.from_release
    [pscustomobject]@{ recovered = $true; phase = 'rolled_back'; release = $journal.from_release }
}

function Invoke-SL2Rollback($Config, [string]$ToRelease) {
    $journal = Read-SL2Journal $Config
    if ($journal -and $journal.phase -in $script:CriticalPhases) { Stop-SL2 'A deployment is in progress or interrupted; run -Action Recover.' }
    $target = if ($ToRelease) { $ToRelease } elseif ($journal -and $journal.from_release) { $journal.from_release } else { '' }
    if (-not $target -or -not (Test-Path -LiteralPath (Join-SL2 $target 'build-manifest.json'))) { Stop-SL2 'No previous release to roll back to; pass -ToRelease <release folder>.' }
    $current = Get-SL2Link (Get-SL2CurrentLink $Config)
    $schema = Invoke-SL2Maintenance (Join-SL2 (Join-SL2 $current 'server') $script:Exe) @('--schema-info', '--data-dir', $Config.DataDirectory)
    $rollback = [pscustomobject]@{ run = $script:RunId; commit = ''; version = ''; to_release = $target; from_release = $target; service_state_before = (Get-SL2Service $Config.ServiceName).State
        applied_before = @($schema.applied); backup = $null; phase = 'stopping'; history = @(); updated = '' }
    Write-SL2Journal $Config $rollback
    Invoke-SL2RollbackCore $Config $rollback $target
    [pscustomobject]@{ rolled_back = $true; release = $target }
}

Export-ModuleMember -Function * -Variable FocusedTests
