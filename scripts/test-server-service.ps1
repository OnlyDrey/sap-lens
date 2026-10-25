<# Native CI acceptance subset. No reboot, recovery or UNC claims. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Bundle)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows SCM smoke tests require Windows.' }
$bundlePath=(Resolve-Path $Bundle).Path
$manage=Join-Path $bundlePath 'manage-server-service.ps1'
$data=Join-Path $env:RUNNER_TEMP ('sap-lens-service-'+[guid]::NewGuid().ToString('N'))
$listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
$listener.Start();$port=$listener.LocalEndpoint.Port;$listener.Stop()
$installed=$false
$backups=$data+'-backups'
$recovered=$data+'-restored'
$recoveredConfiguration=$data+'-restored-config'
$replacement=$data+'-replacement'
if (Get-Service SAPLens -ErrorAction SilentlyContinue) { throw 'An existing SAPLens service must not be changed by the smoke test.' }
try {
    & $manage -Action Install -InstallDirectory $bundlePath -DataDirectory $data -SourceDirectory (Join-Path $data 'sources') -LogDirectory (Join-Path $data 'logs') -Port $port
    $installed=$true
    & $manage -Action Start -InstallDirectory $bundlePath
    $deadline=(Get-Date).AddSeconds(40)
    $ready=$false
    while ((Get-Date) -lt $deadline) {
        try { $health=Invoke-RestMethod "http://127.0.0.1:$port/health/ready"; if ($health.status -eq 'ready') { $ready=$true;break } } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready -or (Get-Service SAPLens).Status -ne 'Running') { throw 'Service did not become ready in SCM.' }
    $version=Invoke-RestMethod "http://127.0.0.1:$port/api/version"
    $expected=Get-Content backend/build/build-version.json -Raw | ConvertFrom-Json
    if ($version.version -ne $expected.version) { throw 'Service version differs from the package identity.' }
    & $manage -Action Stop -InstallDirectory $bundlePath
    if ((Get-Service SAPLens).Status -ne 'Stopped') { throw 'SCM did not stop the service.' }
    & $manage -Action Backup -InstallDirectory $bundlePath -BackupDirectory $backups
    $archive=@(Get-ChildItem $backups -Filter '*.tar.gz')
    if ($archive.Count -ne 1) { throw 'Expected one stopped-state private backup.' }
    & $manage -Action Restore -InstallDirectory $bundlePath -Archive $archive[0].FullName -RestoreDataDirectory $recovered -RestoreConfigurationDirectory $recoveredConfiguration -ConfirmRestore
    if (-not (Test-Path (Join-Path $recovered 'deployment.json')) -or -not (Test-Path (Join-Path $recoveredConfiguration 'SAPLensService.xml'))) { throw 'Empty-target restore lost deployment ownership or configuration.' }
    # Reinstall the same verified version to exercise staging/activation/restart
    # without fabricating a versioned executable or compiling a second package.
    New-Item -ItemType Directory $replacement | Out-Null
    Get-ChildItem $bundlePath | Where-Object { $_.Name -ne 'SAPLensService.xml' } | ForEach-Object { Copy-Item $_.FullName $replacement -Recurse }
    & $manage -Action Upgrade -InstallDirectory $bundlePath -NewBundleDirectory $replacement -BackupDirectory $backups
    if ((Get-Service SAPLens).Status -ne 'Running') { throw 'Staged upgrade did not restart the service.' }
    if ((Invoke-RestMethod "http://127.0.0.1:$port/api/version").version -ne $expected.version) { throw 'Upgrade changed embedded version identity unexpectedly.' }
    & $manage -Action Uninstall -InstallDirectory $bundlePath
    $installed=$false
    $deadline=(Get-Date).AddSeconds(10)
    while ((Get-Service SAPLens -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if (Get-Service SAPLens -ErrorAction SilentlyContinue) { throw 'Service registration remains.' }
    if (-not (Test-Path $data)) { throw 'Uninstall removed persistent data.' }
    $reportPath=Join-Path $bundlePath 'verification-report.json'
    $report=Get-Content $reportPath -Raw | ConvertFrom-Json
    $report.native_service_smoke='passed: install/start/health/version/stop/backup/empty-target-restore/same-version-upgrade/uninstall'
    [IO.File]::WriteAllText($reportPath,($report | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
    Write-Host 'SCM install/start/health/version/stop/uninstall passed. Reboot, recovery and UNC were not tested.'
} finally {
    if ($installed -or (Get-Service SAPLens -ErrorAction SilentlyContinue)) { & $manage -Action Uninstall -InstallDirectory $bundlePath }
    # Generated target-machine configuration is not a distribution input.
    Remove-Item (Join-Path $bundlePath 'SAPLensService.xml') -ErrorAction SilentlyContinue
    if (Test-Path $data) { Remove-Item $data -Recurse -Force }
    foreach ($path in @($backups,$recovered,$recoveredConfiguration,$replacement)) { if (Test-Path $path) { Remove-Item $path -Recurse -Force } }
    # Only isolated test-created previous/pending application copies are removed.
    Get-ChildItem $bundlePath -Directory | Where-Object { $_.Name -match '^app\.(previous|pending)\.[a-f0-9]{32}$' } | Remove-Item -Recurse -Force
}
