# Installer wrapping only; never replaces canonical EXE compilation or verification.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build the desktop installer on Windows.' }
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
& $python (Join-Path $root 'scripts/deployment-package.py') require-inputs
if ($LASTEXITCODE -ne 0) { throw 'Validated deployment inputs are required.' }
$toolRoot = Join-Path $root 'backend/build/inno-setup-7.1.0'
$compiler = Join-Path $toolRoot 'ISCC.exe'
$receipt = Join-Path $toolRoot 'compiler-sha256.txt'
if (-not (Test-Path $compiler)) {
    $download = Join-Path $root 'backend/build/innosetup-7.1.0-x64.exe'
    Invoke-WebRequest 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe' -OutFile $download
    if ((Get-FileHash $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne '0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f') { throw 'Inno Setup download SHA-256 mismatch.' }
    $setup = Start-Process -FilePath $download -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',('/DIR="'+$toolRoot+'"')) -Wait -PassThru
    if ($setup.ExitCode -ne 0 -or -not (Test-Path $compiler)) { throw 'Pinned per-user Inno Setup provisioning failed. Review prerequisites and tool installer logs.' }
    [IO.File]::WriteAllText($receipt,(Get-FileHash $compiler -Algorithm SHA256).Hash.ToLowerInvariant())
}
if (-not (Test-Path $receipt) -or (Get-FileHash $compiler -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([IO.File]::ReadAllText($receipt)).Trim()) { throw 'Build compiler changed after verified provisioning. Review the dedicated tool directory.' }
$info = Get-Content (Join-Path $root 'backend/build/build-version.json') -Raw | ConvertFrom-Json
$version = [string]$info.version
$exe = Join-Path $root 'backend/dist/SAP-Lens.exe'
$approved = Get-Content (Join-Path $root 'backend/build/package-verification.json') -Raw | ConvertFrom-Json
if ((Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $approved.exe_sha256) { throw 'Portable executable changed after canonical verification.' }
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$arguments = @('/Qp',('/O'+$OutputDirectory),('/DSourceExe='+$exe),('/DProductLicense='+(Join-Path $root 'LICENSE.md')),('/DProductIcon='+(Join-Path $root 'assets/sap-lens.ico')),('/DFullVersion='+$version),('/DNumericVersion='+($info.file_version -join '.')),(Join-Path $root 'deploy/windows/desktop-installer.iss'))
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
$installer = Join-Path $OutputDirectory 'SAP-Lens-Setup.exe'
$named = Join-Path $OutputDirectory ("SAP-Lens-Windows-Desktop-x64-$version-Setup.exe")
Move-Item $installer $named
$hash = (Get-FileHash $named -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($named+'.sha256'),($hash+'  '+[IO.Path]::GetFileName($named)+"`n"),[Text.Encoding]::ASCII)
Copy-Item (Join-Path $toolRoot 'license.txt') (Join-Path $OutputDirectory 'LICENSE-Inno-Setup.txt')
& $python (Join-Path $root 'scripts/verify-desktop-installer.py') --installer $named
if ($LASTEXITCODE -ne 0) { throw 'Installer verification failed.' }
Write-Host 'Unsigned per-user installer compiled and metadata verified. Native installation/lifecycle acceptance is separate.'
