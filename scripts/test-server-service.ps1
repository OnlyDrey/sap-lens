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
    & $manage -Action Uninstall -InstallDirectory $bundlePath
    $installed=$false
    $deadline=(Get-Date).AddSeconds(10)
    while ((Get-Service SAPLens -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if (Get-Service SAPLens -ErrorAction SilentlyContinue) { throw 'Service registration remains.' }
    if (-not (Test-Path $data)) { throw 'Uninstall removed persistent data.' }
    $reportPath=Join-Path $bundlePath 'verification-report.json'
    $report=Get-Content $reportPath -Raw | ConvertFrom-Json
    $report.native_service_smoke='passed: install/start/health/version/stop/uninstall'
    [IO.File]::WriteAllText($reportPath,($report | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
    Write-Host 'SCM install/start/health/version/stop/uninstall passed. Reboot, recovery and UNC were not tested.'
} finally {
    if ($installed -or (Get-Service SAPLens -ErrorAction SilentlyContinue)) { & $manage -Action Uninstall -InstallDirectory $bundlePath }
    # Generated target-machine configuration is not a distribution input.
    Remove-Item (Join-Path $bundlePath 'SAPLensService.xml') -ErrorAction SilentlyContinue
    if (Test-Path $data) { Remove-Item $data -Recurse -Force }
}
