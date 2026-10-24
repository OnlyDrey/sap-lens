<# CI orchestration only: all desktop packaging stays in build-windows.ps1. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('Desktop','Service')][string]$Target)
$ErrorActionPreference = 'Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
function Checked([scriptblock]$Command) { & $Command; if ($LASTEXITCODE -ne 0) { throw 'Windows deployment packaging failed.' } }
Checked { python scripts/deployment-package.py require-ci }
& ./scripts/build-windows.ps1 -Stage Environment
& ./scripts/build-windows.ps1 -Stage Python
& ./scripts/build-windows.ps1 -Stage Audit
$python=Join-Path $root 'backend/build/python-env/Scripts/python.exe'
foreach ($pattern in @('test_desktop.py','test_windows_package.py','test_server.py')) {
    Checked { & $python -W error::DeprecationWarning -m unittest discover -s backend/tests -p $pattern -v }
}
if ($Target -eq 'Desktop') {
    & ./scripts/build-windows.ps1 -Stage Package
    & ./scripts/build-windows.ps1 -Stage Verify
    & ./scripts/build-windows.ps1 -Stage Smoke
    # Desktop exact-file ZIP roundtrip is also checked by the canonical verifier.
    $info=Get-Content backend/build/build-version.json -Raw | ConvertFrom-Json
    $output=Join-Path $root 'dist/deployment'
    New-Item -ItemType Directory -Force $output | Out-Null
    $zip=Join-Path $output "SAP-Lens-Windows-Desktop-x64-$($info.version).zip"
    Compress-Archive -Path backend/dist/SAP-Lens.exe,backend/dist/SAP-Lens.exe.sha256 -DestinationPath $zip
    $hash=(Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($zip))" | Set-Content "$zip.sha256" -Encoding ascii
    $download=Join-Path $root 'backend/build/deployment-desktop-download'
    New-Item -ItemType Directory -Force $download | Out-Null
    Copy-Item $zip $download
    Checked { & $python scripts/verify-artifact-zip.py --download $download --destination backend/build/deployment-desktop-roundtrip --expected-digest $hash }
    Checked { & $python scripts/verify-windows-package.py --distribution backend/build/deployment-desktop-roundtrip }
} else {
    $wrapper=Join-Path $root 'backend/build/WinSW-x64.exe'
    Invoke-WebRequest 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe' -OutFile $wrapper
    & ./scripts/build-server-windows.ps1 -WinSW $wrapper -ValidatedCI
    $info=Get-Content backend/build/build-version.json -Raw | ConvertFrom-Json
    $bundle=Join-Path $root "dist/server/$($info.version)"
    & ./scripts/test-server-service.ps1 -Bundle $bundle
    Checked { & $python scripts/deployment-package.py finish --directory $bundle --platform Windows-Service-x64 }
}
