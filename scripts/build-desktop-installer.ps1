# Installer wrapping only; never replaces canonical EXE compilation or verification.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory,[switch]$CompileCheck)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build the desktop installer on Windows.' }
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
if (-not $CompileCheck) {
    & $python (Join-Path $root 'scripts/deployment-package.py') require-inputs
    if ($LASTEXITCODE -ne 0) { throw 'Validated deployment inputs are required.' }
}
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
function Invoke-InstallerCompiler([string]$SourceExe,[string]$FullVersion,[string]$NumericVersion,[string]$Destination) {
    $arguments = @('/Qp',('/O'+$Destination),('/DSourceExe='+$SourceExe),('/DProductLicense='+(Join-Path $root 'LICENSE.md')),('/DProductIcon='+(Join-Path $root 'assets/sap-lens.ico')),('/DFullVersion='+$FullVersion),('/DNumericVersion='+$NumericVersion),(Join-Path $root 'deploy/windows/desktop-installer.iss'))
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
}
if ($CompileCheck) {
    # Compile the complete production recipe, including Pascal code, before any
    # Python dependencies or application packaging. This compiler-as-payload
    # fixture is never executed, packaged for distribution or marked accepted.
    $temporary = Join-Path $OutputDirectory ('recipe-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force $temporary | Out-Null
    try {
        $payload = Join-Path $temporary 'SAP-Lens.exe'
        Copy-Item -LiteralPath $compiler -Destination $payload
        foreach ($channel in @('alpha','beta','rc','stable')) {
            $full = if ($channel -eq 'stable') { '0.1.0' } else { '0.1.0-'+$channel+'.1' }
            $numeric = if ($channel -eq 'stable') { '0.1.0.0' } else { '0.1.0.1' }
            $destination = Join-Path $temporary $channel
            New-Item -ItemType Directory $destination | Out-Null
            Invoke-InstallerCompiler $payload $full $numeric $destination
            if (-not (Test-Path -LiteralPath (Join-Path $destination 'SAP-Lens-Setup.exe') -PathType Leaf)) { throw 'Inno Setup did not produce the compiler-check fixture.' }
            Write-Host "Installer recipe compiled: $channel. Application installation was not tested."
        }
    } finally { Remove-Item -LiteralPath $temporary -Recurse -Force }
    return
}
$info = Get-Content (Join-Path $root 'backend/build/build-version.json') -Raw | ConvertFrom-Json
$version = [string]$info.version
$exe = Join-Path $root 'backend/dist/SAP-Lens.exe'
$approved = Get-Content (Join-Path $root 'backend/build/package-verification.json') -Raw | ConvertFrom-Json
if ((Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $approved.exe_sha256) { throw 'Portable executable changed after canonical verification.' }
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
Invoke-InstallerCompiler $exe $version ($info.file_version -join '.') $OutputDirectory
$installer = Join-Path $OutputDirectory 'SAP-Lens-Setup.exe'
$named = Join-Path $OutputDirectory ("SAP-Lens-Windows-Desktop-x64-$version-Setup.exe")
Move-Item $installer $named
$hash = (Get-FileHash $named -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($named+'.sha256'),($hash+'  '+[IO.Path]::GetFileName($named)+"`n"),[Text.Encoding]::ASCII)
Copy-Item (Join-Path $toolRoot 'license.txt') (Join-Path $OutputDirectory 'LICENSE-Inno-Setup.txt')
& $python (Join-Path $root 'scripts/verify-desktop-installer.py') --installer $named
if ($LASTEXITCODE -ne 0) { throw 'Installer verification failed.' }
Write-Host 'Unsigned per-user installer compiled and metadata verified. Native installation/lifecycle acceptance is separate.'
