# Native Windows only. Refuses to touch an existing registered SAP Lens installation.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Installer,[Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Native installer acceptance requires Windows.' }
$root=Split-Path $PSScriptRoot -Parent
$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{5DB5BC51-A860-44CA-93CA-09AE85812DF0}_is1'
if (Test-Path $key) { throw 'Existing registered SAP Lens installation must not be changed by the smoke test.' }
$tempRoot=if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$temporary=Join-Path $tempRoot ('SAP Lens installer ø '+[guid]::NewGuid().ToString('N'))
$application=Join-Path $temporary 'application'
$data=Join-Path $temporary 'data'; $backups=Join-Path $temporary 'backups'
New-Item -ItemType Directory -Force $data | Out-Null
$settings=Join-Path $data 'settings.json'
[IO.File]::WriteAllText($settings,'{"schema_version":3,"data_csv_path":""}',[Text.UTF8Encoding]::new($false))
$before=[IO.File]::ReadAllText($settings)
$previousConfig=$env:SAP_LENS_CONFIG_DIR; $previousBackup=$env:SAP_LENS_BACKUP_DIR
$env:SAP_LENS_CONFIG_DIR=$data; $env:SAP_LENS_BACKUP_DIR=$backups
$completed=$false
$stage='first installation'
function Install-TestPackage {
    $process=Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$application+'"'),('/LOG="'+(Join-Path $temporary 'setup.log')+'"')) -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer returned exit code $($process.ExitCode). Inspect the isolated setup log; do not publish." }
}
try {
    Install-TestPackage
    $stage='installed payload and registration'
    $approved=Get-Content (Join-Path $root 'backend/build/package-verification.json') -Raw | ConvertFrom-Json
    $installed=Join-Path $application 'SAP-Lens.exe'
    if ((Get-FileHash $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $approved.exe_sha256) { throw 'Installed payload differs from the canonically verified EXE.' }
    if (-not (Test-Path $key)) { throw 'Per-user Installed Apps registration is missing.' }
    $stage='reinstallation and private backups'
    Install-TestPackage
    if ([IO.File]::ReadAllText($settings) -ne $before -or @(Get-ChildItem $backups -Filter '*.tar.gz').Count -lt 2) { throw 'Reinstallation changed settings or failed to preserve private backups.' }
    $stage='installed executable lifecycle'
    & (Join-Path $root 'scripts/test-windows-exe.ps1') -ExecutablePath $installed
    if ($LASTEXITCODE -ne 0) { throw 'Installed EXE lifecycle smoke failed.' }
    $stage='uninstallation and data preservation'
    $uninstall=Start-Process -FilePath (Join-Path $application 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -Wait -PassThru
    if ($uninstall.ExitCode -ne 0 -or (Test-Path $key) -or (Test-Path $installed)) { throw 'Native uninstall did not remove the managed application/registration.' }
    if ([IO.File]::ReadAllText($settings) -ne $before -or -not (Test-Path $backups)) { throw 'Uninstall removed private data or backups.' }
    $stage='native acceptance receipt'
    $identity=Get-Content (Join-Path $root 'backend/build/build-version.json') -Raw | ConvertFrom-Json
    $result=@{schema=1;identity=$identity;installer_sha256=(Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant();payload_sha256=$approved.exe_sha256;signing='disabled';native_installer_smoke='passed: install/reinstall/installed-EXE-lifecycle/uninstall/data-preservation'}
    [IO.File]::WriteAllText($Report,($result | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
    $completed=$true
    Write-Host 'Per-user native install/reinstall/payload/EXE lifecycle/uninstall/data preservation passed. Clean-PC, previous-version, reboot and enterprise policy acceptance remain separate.'
} catch {
    Write-Warning "Native installer acceptance failed during '$stage'. Isolated setup log retained at: $temporary"
    throw
} finally {
    $env:SAP_LENS_CONFIG_DIR=$previousConfig; $env:SAP_LENS_BACKUP_DIR=$previousBackup
    if (Test-Path (Join-Path $application 'unins000.exe')) {
        $cleanup=Start-Process -FilePath (Join-Path $application 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -Wait -PassThru
        if ($cleanup.ExitCode -ne 0) { Write-Warning 'Isolated installer cleanup failed; preserve its directory for manual review.' }
    }
    if ($completed -and -not (Test-Path $key) -and (Test-Path $temporary)) { Remove-Item $temporary -Recurse -Force }
}
