<#
.SYNOPSIS
  Builds the AuthLens Desktop and Server installers (Inno Setup 6) from a verified Windows release folder. Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
  1. Verifies the release folder with verify-release.ps1 (every artifact against build-manifest.json and SHA256SUMS) and refuses a dirty or non-win-x64 build.
  2. Compiles installer\AuthLens-Desktop.iss and installer\AuthLens-Server.iss with the manifest's version and file version.
  3. Writes AuthLens-<version>-Setup.exe, AuthLens-Server-<version>-Setup.exe and installers-SHA256SUMS into -Output.
  Nothing is signed, uploaded, tagged or installed. Code signing is a separate, authorized release step.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-installers.ps1 -ReleasePath C:\AuthLens-Build\builds\AuthLens-2.0.0-alpha.1-...-win-x64 -Output C:\AuthLens-Build\installers
#>
param(
    [Parameter(Mandatory = $true)][string]$ReleasePath,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$Iscc = ''
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$installers = Join-Path (Split-Path -Parent $here) 'installer'

& (Join-Path $here 'verify-release.ps1') -ReleasePath $ReleasePath
if ($LASTEXITCODE -ne 0) { throw "verify-release.ps1 refused $ReleasePath; no installer was built." }
$release = (Resolve-Path -LiteralPath $ReleasePath).ProviderPath.TrimEnd('\')
$manifest = Get-Content -LiteralPath (Join-Path $release 'build-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.target_platform -ne 'win-x64') { throw "The release is $($manifest.target_platform), not win-x64." }
if ($manifest.PSObject.Properties.Name -contains 'source_dirty' -and $manifest.source_dirty) { throw 'The release was built from a modified checkout; installers are built from committed sources only.' }
$repository = Split-Path (Split-Path $here)
$head = (& git -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $manifest.source_sha -or @(& git -C $repository status --porcelain -- backend/scripts backend/installer).Count) { throw 'Installer helpers must be clean committed sources at the same commit as the verified release.' }
$version = [string]$manifest.version
$numeric = (@($manifest.file_version) | ForEach-Object { [string]$_ }) -join '.'
if ($numeric -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw "build-manifest.json file_version '$numeric' is not four numbers." }

if (-not $Iscc) {
    $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc)) { throw 'Inno Setup 6 (ISCC.exe) was not found; install it or pass -Iscc <path>.' }
New-Item -ItemType Directory -Force $Output | Out-Null
$Output = (Resolve-Path -LiteralPath $Output).ProviderPath
if (@(Get-ChildItem -LiteralPath $Output -Force).Count) { throw 'Installer output must be empty; previous packages and incomplete artifacts are never overwritten.' }
$packageName = Split-Path $release -Leaf
$tools = Join-Path $Output ('installer-tools-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $tools | Out-Null
$entries = foreach ($relative in @('Install-AuthLens.ps1','verify-release.ps1','deploy/AuthLens.Deploy.psm1','deploy/Deploy-AuthLens.ps1','deploy/AuthLens.Paths.ps1','deploy/AuthLens.Acl.ps1','deploy/AuthLens.Installer.ps1')) {
    $target = Join-Path $tools $relative
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $here $relative) -Destination $target
    [ordered]@{path=$relative;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[IO.File]::WriteAllText((Join-Path $tools 'installer-tools.json'),(@{schema=1;files=@($entries)} | ConvertTo-Json -Depth 5))

foreach ($script in 'AuthLens-Desktop.iss', 'AuthLens-Server.iss') {
    $ErrorActionPreference = 'Continue'
    & $Iscc '/Q' "/O$Output" "/DFullVersion=$version" "/DNumericVersion=$numeric" "/DReleaseDir=$release" "/DPackageName=$packageName" "/DToolsDir=$tools" (Join-Path $installers $script)
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw "ISCC failed for $script (exit $code)." }
}
$names = "AuthLens-$version-Setup.exe", "AuthLens-Server-$version-Setup.exe"
$lines = foreach ($name in $names) {
    $file = Join-Path $Output $name
    if (-not (Test-Path -LiteralPath $file)) { throw "Expected installer $name was not written." }
    '{0} *{1}' -f (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant(), $name
}
[System.IO.File]::WriteAllLines((Join-Path $Output 'installers-SHA256SUMS'), [string[]]$lines)
$lines | ForEach-Object { Write-Host $_ }
Write-Host "Installers complete: $Output (unsigned; source commit $($manifest.source_sha))"
