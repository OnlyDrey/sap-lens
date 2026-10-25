<# Shared native orchestration: desktop packaging stays in build-windows.ps1. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('Desktop','Service')][string]$Target,[string]$OutputDirectory='')
$ErrorActionPreference = 'Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location $root
function Checked([scriptblock]$Command) { & $Command; if ($LASTEXITCODE -ne 0) { throw 'Windows deployment packaging failed.' } }
Checked { python scripts/deployment-package.py require-inputs }
if (-not $OutputDirectory) { $OutputDirectory=Join-Path $root 'dist/deployment' }
if ($env:GITHUB_ACTIONS -eq 'true') {
    & ./scripts/build-windows.ps1 -Stage Environment
    & ./scripts/build-windows.ps1 -Stage Python
    & ./scripts/build-windows.ps1 -Stage Audit
} # Local receipt already binds this Windows dependency environment and audit.
$python=Join-Path $root 'backend/build/python-env/Scripts/python.exe'
foreach ($pattern in @('test_desktop.py','test_windows_package.py','test_server.py')) {
    Checked { & $python -W error::DeprecationWarning -m unittest discover -s backend/tests -p $pattern -v }
}
if ($Target -eq 'Desktop') {
    & ./scripts/build-windows.ps1 -Stage Package -ValidatedDeployment
    & ./scripts/build-windows.ps1 -Stage Verify
    & ./scripts/build-windows.ps1 -Stage Smoke
    # Desktop exact-file ZIP roundtrip is also checked by the canonical verifier.
    $info=Get-Content backend/build/build-version.json -Raw | ConvertFrom-Json
    $output=$OutputDirectory
    New-Item -ItemType Directory -Force $output | Out-Null
    $zip=Join-Path $output "SAP-Lens-Windows-Desktop-x64-$($info.version).zip"
    Compress-Archive -Path backend/dist/SAP-Lens.exe,backend/dist/SAP-Lens.exe.sha256 -DestinationPath $zip
    $hash=(Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($zip))" | Set-Content "$zip.sha256" -Encoding ascii
    $roundtrip=Join-Path $root ('backend/build/deployment-desktop-'+[guid]::NewGuid().ToString('N'))
    $download=Join-Path $roundtrip 'incoming'
    $verified=Join-Path $roundtrip 'verified'
    New-Item -ItemType Directory -Force $download | Out-Null
    Copy-Item $zip $download
    Checked { & $python scripts/verify-artifact-zip.py --download $download --destination $verified --expected-digest $hash }
    Checked { & $python scripts/verify-windows-package.py --distribution $verified }
} else {
    $wrapper=Join-Path $root 'backend/build/WinSW-x64.exe'
    Invoke-WebRequest 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe' -OutFile $wrapper
    $bundle=Join-Path $root ('backend/build/deployment-service-'+[guid]::NewGuid().ToString('N'))
    & ./scripts/build-server-windows.ps1 -WinSW $wrapper -ValidatedDeployment -OutputDirectory $bundle
    & ./scripts/test-server-service.ps1 -Bundle $bundle
    Checked { & $python scripts/deployment-package.py finish --directory $bundle --platform Windows-Service-x64 --output $OutputDirectory }
}
