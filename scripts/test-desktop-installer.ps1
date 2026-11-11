# Native Windows acceptance: compile a test-only identity, never execute production Setup.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Installer,[Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE=1
if ($env:OS -ne 'Windows_NT') { throw 'Native installer acceptance requires Windows.' }
$root=Split-Path $PSScriptRoot -Parent
$python=Join-Path $root 'backend/build/python-env/Scripts/python.exe'
$helper=Join-Path $root 'scripts/build_system/installer_acceptance.py'
$productionKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{5DB5BC51-A860-44CA-93CA-09AE85812DF0}_is1'
if (Test-Path -LiteralPath $productionKey) {
    Write-Host 'Existing registered SAP Lens remains protected; production Setup will not be executed.'
}
# Installation is supported alongside a registered copy, not alongside a running writer.
# Never stop another instance or bypass the application's production mutex.
$mutex=$null
if ([Threading.Mutex]::TryOpenExisting('Local\SAPLensDesktop',[ref]$mutex)) {
    $mutex.Dispose()
    throw 'Close the running SAP Lens window and background/tray process before acceptance. The existing installation will not be modified.'
}
$names=@('SAP_LENS_CONFIG_DIR','SAP_LENS_BACKUP_DIR','SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE','SAP_LENS_INSTALLER_ACCEPTANCE_ROOT','RUNNER_TEMP','DATA_CSV_PATH','USER_CSV_PATH','EMPLOYEE_CSV_PATH','SOD_CSV_PATH')
$previous=@{}
foreach ($name in $names) { $previous[$name]=[Environment]::GetEnvironmentVariable($name,'Process') }
$plan=$null; $testInstaller=$null; $primary=$null; $primaryStage=$null; $completed=$false; $proof=$null
$cleanupErrors=New-Object 'System.Collections.Generic.List[string]'
$stage='source installer verification'
function Invoke-Plan([string]$Operation) {
    $json=& $python $helper $Operation --plan $plan.plan_path
    if ($LASTEXITCODE -ne 0) { throw "Acceptance plan operation '$Operation' failed." }
    return ($json | ConvertFrom-Json)
}
function Invoke-OwnedExecutable([string]$Path,[string[]]$Arguments) {
    $process=$null
    try {
        $process=Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Native process failed during '$stage' (exit $($process.ExitCode))." }
    } finally { if ($process) { $process.Dispose() } }
}
function Install-TestPackage([string]$LogName) {
    $null=Invoke-Plan 'state'
    if ($plan.test_id -eq $plan.production_id -or $testInstaller -eq $Installer -or
        (Get-FileHash -LiteralPath $testInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne $proof.installer_sha256) {
        throw 'Refusing production or changed installer execution; existing registered SAP Lens must not be changed.'
    }
    Invoke-OwnedExecutable $testInstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',('/DIR="'+$plan.application+'"'),('/LOG="'+(Join-Path $plan.root $LogName)+'"'))
    $null=Invoke-Plan 'registered'
    $null=Invoke-Plan 'verify-production'
}
function Uninstall-TestPackage {
    $null=Invoke-Plan 'registered'
    $uninstaller=Join-Path $plan.application 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf) -or
        ((Get-Item -LiteralPath $uninstaller -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Owned test uninstaller missing or linked; workspace retained.' }
    Invoke-OwnedExecutable $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
    $null=Invoke-Plan 'unregistered'
}
try {
    & $python (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') --installer $Installer
    if ($LASTEXITCODE -ne 0) { throw 'Source production installer resource verification failed.' }
    $stage='prepare isolated identity and production snapshot'
    $testParent=if ($previous['RUNNER_TEMP']) { $previous['RUNNER_TEMP'] } else { [IO.Path]::GetTempPath() }
    $json=& $python $helper prepare --installer $Installer --report $Report --parent $testParent
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare an isolated acceptance workspace.' }
    $plan=$json | ConvertFrom-Json
    $Report=$plan.report
    foreach ($name in @('DATA_CSV_PATH','USER_CSV_PATH','EMPLOYEE_CSV_PATH','SOD_CSV_PATH')) { [Environment]::SetEnvironmentVariable($name,'','Process') }
    $env:SAP_LENS_CONFIG_DIR=$plan.data; $env:SAP_LENS_BACKUP_DIR=$plan.backups
    $env:SAP_LENS_INSTALLER_ACCEPTANCE_ROOT=$plan.root; $env:RUNNER_TEMP=$plan.root
    foreach ($name in @('SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE')) { [Environment]::SetEnvironmentVariable($name,$null,'Process') }
    New-Item -ItemType Directory -Path $plan.data | Out-Null
    $settings=Join-Path $plan.data 'settings.json'
    [IO.File]::WriteAllText($settings,'{"schema_version":3,"data_csv_path":""}',[Text.UTF8Encoding]::new($false))
    $before=[IO.File]::ReadAllText($settings)
    $stage='compile test-only installer'
    & (Join-Path $root 'scripts/build-desktop-installer.ps1') -OutputDirectory $plan.root -AcceptancePlan $plan.plan_path
    if ($LASTEXITCODE -ne 0) { throw 'Test-only installer compilation failed.' }
    $testInstaller=Join-Path $plan.root ('SAP-Lens-Acceptance-'+$plan.test_id+'-Setup.exe')
    $proof=Get-Content -LiteralPath (Join-Path $plan.root 'compiled-acceptance.json') -Raw | ConvertFrom-Json
    if ($proof.test_id -ne $plan.test_id -or $proof.production_installer_sha256 -ne $plan.installer_sha256 -or
        $proof.payload_sha256 -ne $plan.payload_sha256 -or $proof.recipe_sha256 -ne $plan.recipe_sha256) { throw 'Isolated compiler proof differs from the acceptance plan.' }
    & $python (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') --installer $testInstaller --acceptance-id $plan.test_id
    if ($LASTEXITCODE -ne 0) { throw 'Test-only installer identity resource differs; execution refused.' }
    $null=Invoke-Plan 'verify-production'
    $stage='first isolated installation'
    Install-TestPackage 'setup.log'
    $stage='installed payload hash'
    $installed=Join-Path $plan.application 'SAP-Lens.exe'
    if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.payload_sha256) { throw 'Installed payload differs from the canonically verified EXE.' }
    $stage='isolated reinstallation and backups'
    Install-TestPackage 'reinstall.log'
    if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $plan.payload_sha256 -or
        [IO.File]::ReadAllText($settings) -ne $before -or @(Get-ChildItem -LiteralPath $plan.backups -Filter '*.tar.gz').Count -lt 2) { throw 'Reinstallation changed payload/settings or failed to preserve private backups.' }
    $stage='installed executable lifecycle'
    & (Join-Path $root 'scripts/test-windows-exe.ps1') -ExecutablePath $installed
    if ($LASTEXITCODE -ne 0) { throw 'Installed EXE lifecycle smoke failed.' }
    $stage='isolated uninstall and data preservation'
    Uninstall-TestPackage
    if ((Test-Path -LiteralPath $installed) -or [IO.File]::ReadAllText($settings) -ne $before -or -not (Test-Path -LiteralPath $plan.backups)) { throw 'Uninstall changed private data or left the application installed.' }
    $null=Invoke-Plan 'verify-production'
    $completed=$true
} catch { $primary=$_.Exception; $primaryStage=$stage } finally {
    if ($plan) {
        try {
            $stageBeforeCleanup=$stage
            $stage='owned installation cleanup'
            $state=Invoke-Plan 'state'
            if ($state.test_registered) { Uninstall-TestPackage }
            else { $null=Invoke-Plan 'unregistered' }
            $null=Invoke-Plan 'verify-production'
            if ($completed -and -not $primary) { $null=Invoke-Plan 'cleanup' }
            $stage=$stageBeforeCleanup
        } catch { $cleanupErrors.Add($_.Exception.Message) }
    }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
}
if ($primary -or $cleanupErrors.Count -or -not $completed) {
    $global:LASTEXITCODE=1
    $failedStage=if ($primaryStage) { $primaryStage } else { $stage }
    $message="Installer acceptance failed during '$failedStage'. "
    if ($primary) { $message+='Primary: '+$primary.Message+'. ' }
    if ($cleanupErrors.Count) { $message+='Cleanup: '+($cleanupErrors -join '; ')+'. ' }
    if ($plan) { $message+='Retained workspace: '+$plan.root+'; test AppId: '+$plan.test_id }
    throw $message
}
$identity=$plan.identity
$result=@{schema=1;identity=$identity;installer_sha256=$plan.installer_sha256;payload_sha256=$plan.payload_sha256;signing='disabled';
    acceptance_mode='isolated-app-id';test_app_id=$plan.test_id;production_app_id=$plan.production_id;executed_installer_sha256=$proof.installer_sha256;
    recipe_sha256=$plan.recipe_sha256;production_unchanged=$true;cleanup_complete=$true;
    native_installer_smoke='passed: isolated-AppId install/reinstall/installed-EXE-lifecycle/uninstall/data-preservation/production-invariance/cleanup'}
$stage='acceptance receipt'
$stream=$null; $writer=$null
try {
    [IO.Directory]::CreateDirectory((Split-Path $Report -Parent)) | Out-Null
    $stream=[IO.File]::Open($Report,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($false))
    $writer.Write(($result | ConvertTo-Json -Depth 8))
    $writer.Flush()
} catch {
    $global:LASTEXITCODE=1
    throw "Installer acceptance failed during '$stage': could not write the new receipt at $Report. The test installation was cleaned up."
} finally {
    if ($writer) { $writer.Dispose() } elseif ($stream) { $stream.Dispose() }
}
Write-Host 'Isolated native installer acceptance passed; production installation/data unchanged. Production upgrade, clean-PC and enterprise-policy acceptance remain separate.'
$global:LASTEXITCODE=0
