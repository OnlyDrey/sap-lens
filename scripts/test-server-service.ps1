<# Native SCM acceptance. All mutable test state is isolated; no reboot/recovery/UNC claims. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Bundle)
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE=1  # Preflight/parameter-body exceptions must not leave a stale success code.
if ($env:OS -ne 'Windows_NT') { throw 'Windows SCM smoke tests require Windows.' }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    [Console]::Error.WriteLine('ACCEPTANCE PREREQUISITE: native service (SCM) acceptance needs an elevated PowerShell (Run as administrator). No service was installed or changed.')
    exit 3
}
Set-Location (Split-Path $PSScriptRoot -Parent)
. (Join-Path $PSScriptRoot 'testing/windows-scm-test-helpers.ps1')
function Test-ScmRegistered {
    $service=Get-Service SAPLens -ErrorAction SilentlyContinue
    if (-not $service) { return $false }
    try { return $true } finally { $service.Dispose() }
}
function Get-ScmStatus {
    $service=Get-Service SAPLens -ErrorAction Stop
    try { return $service.Status } finally { $service.Dispose() }
}
if (Test-ScmRegistered) { throw 'An existing SAPLens service must not be changed by the smoke test.' }
$inputBundle=(Get-Item -LiteralPath $Bundle -Force).FullName
$inputIsDirectory=Test-Path -LiteralPath $inputBundle -PathType Container
$packageFingerprint=if ($inputIsDirectory) { (Get-FileHash -LiteralPath (Join-Path $inputBundle 'verification-report.json') -Algorithm SHA256).Hash.ToLowerInvariant() } else { (Get-FileHash -LiteralPath $inputBundle -Algorithm SHA256).Hash.ToLowerInvariant() }
$managementHost=(Get-Process -Id $PID).Path
$reportPath=$inputBundle+'.scm-verification.json'
if (Test-Path -LiteralPath $reportPath) { throw 'SCM evidence already exists. Inspect and preserve the earlier report before an authorized rerun; no service was changed.' }
$tempBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$workspace=New-ScmWorkspace $tempBase
$bundlePath=$null; $manage=$null; $primary=$null; $report=$null
$cleanupErrors=New-Object 'System.Collections.Generic.List[string]'
function Assert-OwnedScmService {
    $service=Get-CimInstance Win32_Service -Filter "Name='SAPLens'" -ErrorAction Stop
    if (-not $service) { return }
    try {
        $expected=Join-Path $bundlePath 'SAPLensService.exe'
        if ($service.PathName.Trim().Trim('"') -ne $expected) { throw 'Refusing to change an unrelated SAPLens service.' }
    } finally { $service.Dispose() }
}
function Invoke-ScmManage {
    if (Test-ScmRegistered) { Assert-OwnedScmService }
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $stage='Service management '+($args -join ' ')
    Write-Host "[SCM] START | $stage"
    $child=$null; $passed=$false
    try {
        # Encode quoted tokens; neither spaces/Unicode nor PowerShell metacharacters
        # can turn an argument into executable code. This child alone is owned.
        $bindings=New-Object 'System.Collections.Generic.List[string]'
        for ($index=0; $index -lt $args.Count; $index++) {
            $name=[string]$args[$index]
            if ($name -notmatch '^-[A-Za-z]+$') { throw 'Invalid management parameter name.' }
            $key=$name.Substring(1)
            if ($key -eq 'ConfirmRestore') { $value='$true' }
            else {
                $index++
                if ($index -ge $args.Count) { throw 'Missing management parameter value.' }
                $value="'"+([string]$args[$index]).Replace("'","''")+"'"
            }
            $bindings.Add("'"+$key+"'="+$value)
        }
        $quotedManage="'"+$manage.Replace("'","''")+"'"
        $code='$ErrorActionPreference=''Stop''; $global:LASTEXITCODE=0; $parameters=@{'+($bindings -join ';')+'}; & '+$quotedManage+' @parameters; if (-not $?) { exit 1 }; exit $global:LASTEXITCODE'
        $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
        $child=Start-Process -FilePath $managementHost -ArgumentList @('-NoProfile','-EncodedCommand',$encoded) -NoNewWindow -PassThru
        while (-not $child.WaitForExit(3000) -and $timer.Elapsed.TotalSeconds -lt 180) {
            Write-Host ('[SCM] RUNNING | '+$stage+' | elapsed '+[int]$timer.Elapsed.TotalSeconds+'s')
        }
        if (-not $child.HasExited) {
            $child.Kill()
            $null=$child.WaitForExit(10000)
            throw 'Owned management host exceeded 180 seconds; inspect service state and retained workspace.'
        }
        if ($child.ExitCode -ne 0) { throw "Service management failed (exit $($child.ExitCode))." }
        $passed=$true
    } finally {
        if ($child) { $child.Dispose() }
        $timer.Stop()
        $status=if ($passed) { 'PASS' } else { 'FAIL' }
        Write-Host ("[SCM] $status | $stage | elapsed {0:N1}s" -f $timer.Elapsed.TotalSeconds)
    }
}
try {
    $bundlePath=Copy-ScmBundle $inputBundle $workspace
    $manage=Join-Path $bundlePath 'manage-server-service.ps1'
    $report=Get-Content -LiteralPath (Join-Path $bundlePath 'verification-report.json') -Raw | ConvertFrom-Json
    if ($report.schema -ne 1 -or $report.verification -ne 'passed' -or -not $report.identity.version -or -not $report.files) { throw 'Invalid verified service-bundle report.' }
    foreach ($required in @('manage-server-service.ps1','SAPLensService.exe','app/SAP-Lens.exe')) {
        if (-not $report.files.PSObject.Properties[$required]) { throw 'Service report omits a required executable/management file.' }
    }
    foreach ($file in $report.files.PSObject.Properties) {
        $relative=Get-SafeScmZipPath $file.Name
        $path=Join-Path $bundlePath $relative
        if ($file.Value -notmatch '^[a-f0-9]{64}$' -or -not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.Value) { throw 'Service bundle differs from its verified file inventory.' }
    }
    $expected=$report.identity
    $data=Join-Path $workspace.Root 'data'
    $backups=Join-Path $workspace.Root 'backups'
    $recovered=Join-Path $workspace.Root 'restored'
    $recoveredConfiguration=Join-Path $workspace.Root 'restored-config'
    # Capture a pristine, manifest-defined replacement before WinSW can write runtime files.
    $replacement=Copy-ScmReplacementBundle $bundlePath $workspace $report
    $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
    try { $listener.Start();$port=$listener.LocalEndpoint.Port } finally { $listener.Stop() }
    Invoke-ScmManage -Action Install -InstallDirectory $bundlePath -DataDirectory $data -SourceDirectory (Join-Path $data 'sources') -LogDirectory (Join-Path $data 'logs') -Port $port
    Invoke-ScmManage -Action Start -InstallDirectory $bundlePath
    $deadline=(Get-Date).AddSeconds(40)
    $ready=$false
    while ((Get-Date) -lt $deadline) {
        try { $health=Invoke-RestMethod "http://127.0.0.1:$port/health/ready" -TimeoutSec 3; if ($health.status -eq 'ready') { $ready=$true;break } } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready -or (Get-ScmStatus) -ne 'Running') { throw 'Service did not become ready in SCM.' }
    $version=Invoke-RestMethod "http://127.0.0.1:$port/api/version" -TimeoutSec 3
    if ($version.version -ne $expected.version) { throw 'Service version differs from the package identity.' }
    Invoke-ScmManage -Action Stop -InstallDirectory $bundlePath
    if ((Get-ScmStatus) -ne 'Stopped') { throw 'SCM did not stop the service.' }
    Invoke-ScmManage -Action Backup -InstallDirectory $bundlePath -BackupDirectory $backups
    $archive=@(Get-ChildItem $backups -Filter '*.tar.gz')
    if ($archive.Count -ne 1) { throw 'Expected one stopped-state private backup.' }
    Invoke-ScmManage -Action Restore -InstallDirectory $bundlePath -Archive $archive[0].FullName -RestoreDataDirectory $recovered -RestoreConfigurationDirectory $recoveredConfiguration -ConfirmRestore
    if (-not (Test-Path (Join-Path $recovered 'deployment.json')) -or -not (Test-Path (Join-Path $recoveredConfiguration 'SAPLensService.xml'))) { throw 'Empty-target restore lost deployment ownership or configuration.' }
    # Reinstall the same verified version to exercise staging/activation/restart
    # without fabricating a versioned executable or compiling a second package.
    Invoke-ScmManage -Action Upgrade -InstallDirectory $bundlePath -NewBundleDirectory $replacement -BackupDirectory $backups
    if ((Get-ScmStatus) -ne 'Running') { throw 'Staged upgrade did not restart the service.' }
    if ((Invoke-RestMethod "http://127.0.0.1:$port/api/version" -TimeoutSec 3).version -ne $expected.version) { throw 'Upgrade changed embedded version identity unexpectedly.' }
    Invoke-ScmManage -Action Uninstall -InstallDirectory $bundlePath
    $deadline=(Get-Date).AddSeconds(10)
    while ((Test-ScmRegistered) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if (Test-ScmRegistered) { throw 'Service registration remains.' }
    if (-not (Test-Path $data)) { throw 'Uninstall removed persistent data.' }
} catch { $primary=$_.Exception } finally {
    $safeToRemove=$true
    try {
        if (Test-ScmRegistered) {
            if (-not $bundlePath) { throw 'An unexpected service exists; no owned bundle was installed.' }
            Assert-OwnedScmService
            Invoke-ScmManage -Action Uninstall -InstallDirectory $bundlePath
        }
        $deadline=(Get-Date).AddSeconds(10)
        while ((Test-ScmRegistered) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
        if (Test-ScmRegistered) { throw 'Service registration remains; test workspace retained.' }
    } catch { $safeToRemove=$false; $cleanupErrors.Add($_.Exception.Message) }
    if ($safeToRemove) {
        try {
            $cleanupTimer=[Diagnostics.Stopwatch]::StartNew()
            Write-Host '[SCM] START | owned workspace cleanup'
            Wait-ScmWorkspaceProcesses $workspace; Remove-ScmWorkspace $workspace
            Write-Host ('[SCM] PASS | owned workspace cleanup | elapsed {0:N1}s' -f $cleanupTimer.Elapsed.TotalSeconds)
        }
        catch { Write-Host '[SCM] FAIL | owned workspace cleanup; evidence not published'; $cleanupErrors.Add($_.Exception.Message) }
    }
}
if ($primary -or $cleanupErrors.Count) {
    $global:LASTEXITCODE=1
    $detail=if ($primary) { 'Primary acceptance failure: '+$primary.Message } else { 'SCM lifecycle completed but cleanup failed.' }
    if ($cleanupErrors.Count) { $detail += "`nCleanup failure(s): " + ($cleanupErrors -join '; ') + "`nRetained workspace: " + $workspace.Root }
    if ($primary) { throw (New-Object System.Exception($detail,$primary)) }
    throw $detail
}
# Separate evidence: never rewrite the original package verification or build manifest.
$receipt=@{schema=1;kind='windows-scm';status='passed';identity=$expected;package_sha256=$packageFingerprint;
    package_kind=$(if ($inputIsDirectory) { 'directory-report' } else { 'zip' });cleanup_complete=$true;
    completed_at=[DateTime]::UtcNow.ToString('o');
    checks=@('install','start','health','version','stop','backup','restore','upgrade','uninstall','cleanup');
    not_verified=@('reboot','recovery','unc')}
$global:LASTEXITCODE=1
try {
    $currentFingerprint=if ($inputIsDirectory) { (Get-FileHash -LiteralPath (Join-Path $inputBundle 'verification-report.json') -Algorithm SHA256).Hash.ToLowerInvariant() } else { (Get-FileHash -LiteralPath $inputBundle -Algorithm SHA256).Hash.ToLowerInvariant() }
    if ($currentFingerprint -ne $packageFingerprint) { throw 'Input package changed during acceptance; evidence refused.' }
    Write-ScmEvidence $reportPath $receipt
} catch { throw "SCM lifecycle completed but acceptance evidence publication failed: $($_.Exception.Message). No successful report is claimed." }
Write-Host "SCM lifecycle, service removal and isolated-data cleanup passed. Evidence: $reportPath. Reboot, recovery and UNC were not tested."
$global:LASTEXITCODE=0
exit 0
