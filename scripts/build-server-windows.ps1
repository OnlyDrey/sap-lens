<# Local headless server bundle. The canonical desktop build remains unchanged. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WinSW,[string]$Version='0.1.0',[Alias('ValidatedCI')][switch]$ValidatedDeployment,[string]$OutputDirectory='')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Build the server bundle on x64 Windows.' }
$root=Split-Path $PSScriptRoot -Parent
$python=Join-Path $root 'backend/build/python-env/Scripts/python.exe'
if (-not (Test-Path $python)) { throw 'Run build-local.ps1 -Mode Validate -Version <version> first.' }
function Invoke-Checked([scriptblock]$Command) { & $Command; if ($LASTEXITCODE -ne 0) { throw 'Server build failed. No verified bundle was produced.' } }
Push-Location $root
try {
    Invoke-Checked { & $python scripts/local-build.py tools }
    if ($ValidatedDeployment) {
        Invoke-Checked { & $python scripts/deployment-package.py require-inputs }
        $Version=(Get-Content backend/build/build-version.json -Raw | ConvertFrom-Json).version
    } else { Invoke-Checked { & $python scripts/local-build.py check --version $Version } }
    if ((Get-FileHash $WinSW -Algorithm SHA256).Hash.ToLowerInvariant() -ne '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da') { throw 'WinSW SHA-256 does not match the official pinned v2.12.0 x64 release.' }
    $output=if ($OutputDirectory) { $OutputDirectory } else { Join-Path $root "dist/server/$Version" }
    if (Test-Path $output) { throw 'Output already exists. Use a new empty output directory/version after reviewing the previous build.' }
    Invoke-Checked { & $python scripts/write-windows-metadata.py }
    # Console bootloader is required for WinSW Ctrl+C shutdown. No WebView2 runtime hooks.
    Invoke-Checked { & $python -m PyInstaller --noconfirm --clean --onedir --console --noupx --name SAP-Lens --distpath "$output/app" --workpath backend/build/server --specpath backend/build/server --paths backend --icon assets/sap-lens.ico --version-file backend/build/version-info.txt --add-data 'frontend/dist;frontend/dist' --add-data 'assets/sap-lens.ico;assets' --add-data 'assets/sap-lens.png;assets' --add-data 'backend/build/build-version.json;.' --collect-data docx --collect-data reportlab --copy-metadata python-docx --copy-metadata reportlab --copy-metadata lxml --copy-metadata charset-normalizer --exclude-module webview --exclude-module pythonnet --exclude-module clr backend/server.py }
    Move-Item "$output/app/SAP-Lens/*" "$output/app/"
    Remove-Item "$output/app/SAP-Lens"
    Copy-Item $WinSW "$output/SAPLensService.exe"
    Copy-Item scripts/manage-server-service.ps1 $output
    Copy-Item deploy/windows/LICENSE-WinSW.txt $output
    Copy-Item LICENSE.md $output
    Copy-Item docs/deployment/WINDOWS_SERVICE.md (Join-Path $output 'README.md')
    Invoke-Checked { & $python scripts/deployment-package.py readme --document docs/deployment/WINDOWS_SERVICE.md --directory $output }
    Invoke-Checked { & $python scripts/verify-server-bundle.py $output }
    Write-Host "Verified headless server bundle: $output. Signing is disabled. Install/start and stop tests on the target Windows Server are still required."
} finally { Pop-Location }
