$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
function Assert-Success([string]$Stage) {
    if ($LASTEXITCODE -eq 0) { return }
    $message = "$Stage failed with exit code $LASTEXITCODE"
    if ($env:GITHUB_ACTIONS -eq 'true') { Write-Host "::error title=SAP Lens build::$message" }
    throw $message
}
python -m venv backend/build/python-env
Assert-Success 'Create build environment'
$buildPython = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
$originalBuildPath = $env:PATH
$env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:PATH
try {
    Push-Location frontend
    try {
        npm ci
        Assert-Success 'Install frontend dependencies'
        npm run build
        Assert-Success 'Build production frontend'
    } finally { Pop-Location }
    & $buildPython -m pip install --upgrade pip
    Assert-Success 'Upgrade build pip'
    & $buildPython -m pip install -r backend/requirements-build.txt -r backend/requirements-dev.txt
    Assert-Success 'Install build and test dependencies'
    & $buildPython -m pip check
    Assert-Success 'Check Python dependencies'
    # Audit the isolated Windows build environment, including Windows-only runtime
    # dependencies. The audit tool itself is kept outside the packaged environment.
    & $buildPython -m venv backend/build/audit-env
    Assert-Success 'Create isolated audit environment'
    $auditPython = Join-Path $root 'backend/build/audit-env/Scripts/python.exe'
    & $auditPython -m pip install pip-audit
    Assert-Success 'Install audit tooling'
    $sitePackages = & $buildPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    Assert-Success 'Locate build dependencies'
    & $auditPython -m pip_audit --path $sitePackages --vulnerability-service pypi --progress-spinner off
    Assert-Success 'Audit Windows dependencies'
    & $buildPython -m unittest discover -s backend/tests -v
    Assert-Success 'Backend regression tests'
    Push-Location frontend
    try {
        npm audit --omit=dev
        Assert-Success 'Audit production JavaScript dependencies'
        npx playwright install chromium
        Assert-Success 'Install test browser'
        npm run test:browser
        Assert-Success 'Production browser regression tests'
    } finally { Pop-Location }
    & $buildPython scripts/write-windows-metadata.py
    Assert-Success 'Generate Windows metadata'
    $icon = Join-Path $root 'assets/sap-lens.ico'
    $metadata = Join-Path $root 'backend/build/version-info.txt'
    $iconData = $icon + ';assets'
    $frontendDist = Join-Path $root 'frontend/dist'
    & $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name SAP-Lens --icon "$icon" --version-file "$metadata" --add-data "$iconData" --paths backend --add-data "$frontendDist;frontend/dist" --specpath backend --distpath backend/dist --workpath backend/build backend/desktop.py
    Assert-Success 'Package Windows executable'
    Write-Host 'Build complete: backend/dist/SAP-Lens.exe'
} finally {
    $env:PATH = $originalBuildPath
}
