# Installer wrapping only; never replaces canonical EXE compilation or verification.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory,[switch]$CompileCheck,[string]$AcceptancePlan='')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build the desktop installer on Windows.' }
# Inno resolves relative /DSourceExe paths against the recipe directory, not CWD.
# Keep ordinary absolute Win32 paths at the native compiler boundary.
function Resolve-InstallerPath([string]$Path,[string]$Base) {
    if ($Path.StartsWith('\\?\UNC\',[StringComparison]::OrdinalIgnoreCase)) { $Path='\\'+$Path.Substring(8) }
    elseif ($Path.StartsWith('\\?\')) { $Path=$Path.Substring(4) }
    if ($Path -match '^[A-Za-z]:([^\\/]|$)') { throw 'Drive-relative installer paths are ambiguous; use a full path.' }
    if (-not [IO.Path]::IsPathRooted($Path)) { $Path=Join-Path $Base $Path }
    return [IO.Path]::GetFullPath($Path)
}
$root = Resolve-InstallerPath (Split-Path $PSScriptRoot -Parent) $PSScriptRoot
$OutputDirectory = Resolve-InstallerPath $OutputDirectory $root
if ($AcceptancePlan) { $AcceptancePlan=Resolve-InstallerPath $AcceptancePlan $root }
$python = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
if ($CompileCheck -and $AcceptancePlan) { throw 'CompileCheck cannot use an acceptance plan.' }
if (-not $CompileCheck -and -not $AcceptancePlan) {
    & $python (Join-Path $root 'scripts/deployment-package.py') require-inputs
    if ($LASTEXITCODE -ne 0) { throw 'Validated deployment inputs are required.' }
}
$acceptance=$null
if ($AcceptancePlan) {
    $json = & $python (Join-Path $root 'scripts/build_system/installer_acceptance.py') validate --plan $AcceptancePlan
    if ($LASTEXITCODE -ne 0) { throw 'Invalid isolated acceptance plan.' }
    $acceptance = $json | ConvertFrom-Json
    if ([IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\') -ne $acceptance.root.TrimEnd('\')) { throw 'Test-only installer must stay in its private acceptance workspace.' }
}
$toolRoot = Join-Path $root 'backend/build/inno-setup-7.1.0'
$compiler = Join-Path $toolRoot 'ISCC.exe'
$receipt = Join-Path $toolRoot 'compiler-sha256.txt'
if ($AcceptancePlan -and -not (Test-Path $compiler)) { throw 'The pinned Inno compiler must be provisioned before isolated acceptance.' }
if (-not (Test-Path $compiler)) {
    $download = Join-Path $root 'backend/build/innosetup-7.1.0-x64.exe'
    # CompileCheck can precede creation of the packaging environment; its host Python is already a prerequisite.
    $toolPython = $python
    if (-not (Test-Path $toolPython)) { $toolPython = (Get-Command python -ErrorAction Stop).Source }
    & $toolPython (Join-Path $root 'scripts/testing/ci.py') inno $download
    if ($LASTEXITCODE -ne 0) { throw 'Pinned Inno Setup acquisition failed; inspect prerequisite diagnostics.' }
    if ((Get-FileHash $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne '0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f') { throw 'Inno Setup download SHA-256 mismatch.' }
    $setup = Start-Process -FilePath $download -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',('/DIR="'+$toolRoot+'"')) -Wait -PassThru
    if ($setup.ExitCode -ne 0 -or -not (Test-Path $compiler)) { throw 'Pinned per-user Inno Setup provisioning failed. Review prerequisites and tool installer logs.' }
    [IO.File]::WriteAllText($receipt,(Get-FileHash $compiler -Algorithm SHA256).Hash.ToLowerInvariant())
}
if (-not (Test-Path $receipt) -or (Get-FileHash $compiler -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([IO.File]::ReadAllText($receipt)).Trim()) { throw 'Build compiler changed after verified provisioning. Review the dedicated tool directory.' }
function Invoke-InstallerCompiler([string]$SourceExe,[string]$FullVersion,[string]$NumericVersion,[string]$Destination,[string]$TestIdentity='') {
    $SourceExe=Resolve-InstallerPath $SourceExe $root
    $Destination=Resolve-InstallerPath $Destination $root
    foreach ($source in @($SourceExe,(Join-Path $root 'LICENSE.md'),(Join-Path $root 'assets/sap-lens.ico'),(Join-Path $root 'deploy/windows/desktop-installer.iss'))) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Installer compiler source is missing: $source" }
    }
    $arguments = @('/Qp',('/O'+$Destination),('/DSourceExe='+$SourceExe),('/DProductLicense='+(Join-Path $root 'LICENSE.md')),('/DProductIcon='+(Join-Path $root 'assets/sap-lens.ico')),('/DFullVersion='+$FullVersion),('/DNumericVersion='+$NumericVersion),(Join-Path $root 'deploy/windows/desktop-installer.iss'))
    if ($TestIdentity) {
        $rootHex=([Text.Encoding]::BigEndianUnicode.GetBytes([IO.Path]::GetFullPath($Destination)) | ForEach-Object { $_.ToString('x2') }) -join ''
        $arguments = @($arguments[0..($arguments.Count-2)]) + @(('/DAcceptanceId='+$TestIdentity), ('/DAcceptanceRootHex='+$rootHex), $arguments[-1])
    }
    & $compiler @arguments 2>&1 | Tee-Object -FilePath (Join-Path $Destination 'compiler.log')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
}
if ($CompileCheck) {
    # Compile the complete production recipe, including Pascal code, before any
    # Python dependencies or application packaging. This compiler-as-payload
    # fixture is never executed, packaged for distribution or marked accepted.
    # pefile is the existing Windows package verifier dependency. Provision the
    # same pinned tool in a separate disposable check environment, never in the
    # application environment. Compilation alone cannot test the PE reader.
    $checkEnvironment = Join-Path $root 'backend/build/installer-check-env'
    $checkHost = 'python'
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    $isBaseline = (& python -c 'import sys; print(sys.version_info[:2]==(3,12))' 2>$null) -eq 'True'
    if ($launcher -and -not $isBaseline) { $checkHost = (& py -3.12 -c 'import sys; print(sys.executable)') }
    & $checkHost -m venv $checkEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Installer check environment creation failed.' }
    $checkPython = Join-Path $checkEnvironment 'Scripts/python.exe'
    $pefilePin = @(Get-Content (Join-Path $root 'backend/requirements-build.txt') | Where-Object { $_ -match '^pefile==[0-9.]+$' })
    if ($pefilePin.Count -ne 1) { throw 'The existing PE verifier requires one canonical dependency pin.' }
    & $checkPython -m pip install --disable-pip-version-check $pefilePin[0]
    if ($LASTEXITCODE -ne 0) { throw 'Installer verifier dependency provisioning failed.' }
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
            & $checkPython (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') --installer (Join-Path $destination 'SAP-Lens-Setup.exe') --compiler-fixture-channel $channel
            if ($LASTEXITCODE -ne 0) { throw 'Compiled installer fixture resource verification failed.' }
            Write-Host "Installer recipe compiled and PE resources verified: $channel. Application installation was not tested."
        }
        $destination=Join-Path $temporary 'acceptance'
        New-Item -ItemType Directory $destination | Out-Null
        Invoke-InstallerCompiler $payload '0.1.0-beta.1' '0.1.0.1' $destination '36C8FD0F-14CE-49D9-BA04-52E94C118C31'
        & $checkPython (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') --installer (Join-Path $destination 'SAP-Lens-Setup.exe') --compiler-fixture-channel beta --acceptance-id '36C8FD0F-14CE-49D9-BA04-52E94C118C31'
        if ($LASTEXITCODE -ne 0) { throw 'Isolated acceptance recipe compilation/resource check failed.' }
    } catch {
        Write-Warning "CompileCheck failed; synthetic fixture and compiler diagnostics retained at $temporary"
        throw
    }
    Remove-Item -LiteralPath $temporary -Recurse -Force
    return
}
$info = Get-Content (Join-Path $root 'backend/build/build-version.json') -Raw | ConvertFrom-Json
$version = [string]$info.version
$exe = Join-Path $root 'backend/dist/SAP-Lens.exe'
$approved = Get-Content (Join-Path $root 'backend/build/package-verification.json') -Raw | ConvertFrom-Json
if ((Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $approved.exe_sha256) { throw 'Portable executable changed after canonical verification.' }
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
Invoke-InstallerCompiler $exe $version ($info.file_version -join '.') $OutputDirectory $(if ($acceptance) { $acceptance.test_id } else { '' })
$installer = Join-Path $OutputDirectory 'SAP-Lens-Setup.exe'
$named = if ($acceptance) { Join-Path $OutputDirectory ("SAP-Lens-Acceptance-"+$acceptance.test_id+"-Setup.exe") } else { Join-Path $OutputDirectory ("SAP-Lens-Windows-Desktop-x64-$version-Setup.exe") }
Move-Item $installer $named
$hash = (Get-FileHash $named -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($named+'.sha256'),($hash+'  '+[IO.Path]::GetFileName($named)+"`n"),[Text.Encoding]::ASCII)
Copy-Item (Join-Path $toolRoot 'license.txt') (Join-Path $OutputDirectory 'LICENSE-Inno-Setup.txt')
$verificationArguments=@('--installer',$named)
if ($acceptance) { $verificationArguments+=@('--acceptance-id',$acceptance.test_id) }
& $python (Join-Path $root 'scripts/packaging/verify-desktop-installer.py') @verificationArguments
if ($LASTEXITCODE -ne 0) { throw 'Installer verification failed.' }
if ($acceptance) {
    $proof=@{schema=1;test_id=$acceptance.test_id;installer_sha256=$hash;production_installer_sha256=$acceptance.installer_sha256;payload_sha256=$approved.exe_sha256;recipe_sha256=$acceptance.recipe_sha256}
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'compiled-acceptance.json'),($proof | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
} else {
    & $python (Join-Path $root 'scripts/build_system/installer_acceptance.py') record-production --installer $named
    if ($LASTEXITCODE -ne 0) { throw 'Production installer/payload provenance could not be recorded.' }
}
Write-Host 'Unsigned per-user installer compiled and metadata verified. Native installation/lifecycle acceptance is separate.'
