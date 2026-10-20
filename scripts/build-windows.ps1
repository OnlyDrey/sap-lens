$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
function Assert-Success { if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" } }
python -m venv backend/build/python-env
Assert-Success
$buildPython = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
$originalBuildPath = $env:PATH
$env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:PATH
try {
    Push-Location frontend
    try {
        npm ci
        Assert-Success
        npm run build
        Assert-Success
    } finally { Pop-Location }
    & $buildPython -m pip install --upgrade pip
    Assert-Success
    & $buildPython -m pip install -r backend/requirements-desktop.txt -r backend/requirements-dev.txt
    Assert-Success
    & $buildPython -m pip check
    Assert-Success
    # Audit the isolated Windows build environment, including Windows-only runtime
    # dependencies. The audit tool itself is kept outside the packaged environment.
    & $buildPython -m venv backend/build/audit-env
    Assert-Success
    $auditPython = Join-Path $root 'backend/build/audit-env/Scripts/python.exe'
    & $auditPython -m pip install pip-audit
    Assert-Success
    $sitePackages = & $buildPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    Assert-Success
    & $auditPython -m pip_audit --path $sitePackages --vulnerability-service pypi --progress-spinner off
    Assert-Success
    & $buildPython -m unittest discover -s backend/tests -v
    Assert-Success
    Push-Location frontend
    try {
        npm audit --omit=dev
        Assert-Success
        npx playwright install chromium
        Assert-Success
        npm run test:browser
        Assert-Success
    } finally { Pop-Location }
    & $buildPython scripts/write-windows-metadata.py
    Assert-Success
    $icon = Join-Path $root 'assets/sap-lens.ico'
    $metadata = Join-Path $root 'backend/build/version-info.txt'
    $iconData = $icon + ';assets'
    $frontendDist = Join-Path $root 'frontend/dist'
    & $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name SAP-Lens --icon "$icon" --version-file "$metadata" --add-data "$iconData" --paths backend --add-data "$frontendDist;frontend/dist" --specpath backend --distpath backend/dist --workpath backend/build backend/desktop.py
    Assert-Success
    Write-Host 'Build complete: backend/dist/SAP-Lens.exe'
} finally {
    $env:PATH = $originalBuildPath
}
