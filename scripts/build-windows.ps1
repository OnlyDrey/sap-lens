param(
    [ValidateSet('All', 'Environment', 'Frontend', 'Python', 'Audit', 'Backend', 'Browser', 'Package', 'Verify', 'Smoke')]
    [string]$Stage = 'All'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
function Assert-Success([string]$Stage) {
    if ($LASTEXITCODE -eq 0) { return }
    $message = "$Stage failed with exit code $LASTEXITCODE"
    if ($env:GITHUB_ACTIONS -eq 'true') { Write-Host "::error title=SAP Lens build::$message" }
    throw $message
}
$buildPython = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
# Keep audit tooling in the host interpreter, outside the isolated package environment.
$hostPython = (Get-Command python).Source
function Invoke-Stage([string]$Name, [scriptblock]$Action) {
    if ($Stage -ne 'All' -and $Stage -ne $Name) { return }
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $status = 'failed'
    Write-Host "::group::$Name"
    try { & $Action; $status = 'passed' } finally {
        $watch.Stop()
        $seconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
        Write-Host "TIMING $Name : $seconds seconds ($status)"
        Write-Host '::endgroup::'
        New-Item -ItemType Directory -Force backend/build | Out-Null
        @{ stage = $Name; seconds = $seconds; status = $status } | ConvertTo-Json -Compress |
            Add-Content backend/build/timings.jsonl -Encoding utf8
        if ($env:GITHUB_STEP_SUMMARY) {
            "| $Name | $seconds | $status |" | Add-Content $env:GITHUB_STEP_SUMMARY
        }
    }
}
if ($env:GITHUB_STEP_SUMMARY) {
    "`n| Build stage | Seconds | Result |`n|---|---:|---|" | Add-Content $env:GITHUB_STEP_SUMMARY
}
$originalBuildPath = $env:PATH
$env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:PATH
try {
    Invoke-Stage Environment {
        & $hostPython -m venv backend/build/python-env
        Assert-Success 'Create build environment'
    }
    Invoke-Stage Frontend {
    Push-Location frontend
    try {
        npm ci
        Assert-Success 'Install frontend dependencies'
        npm run build
        Assert-Success 'Build production frontend'
    } finally { Pop-Location }
    }
    Invoke-Stage Python {
    & $buildPython -m pip install -r backend/requirements-build.txt -r backend/requirements-dev.txt
    Assert-Success 'Install build and test dependencies'
    & $buildPython -m pip check
    Assert-Success 'Check Python dependencies'
    }
    Invoke-Stage Audit {
    # Audit the isolated Windows build environment, including Windows-only runtime
    # dependencies. The audit tool itself is kept outside the packaged environment.
    & $hostPython -m pip install -r scripts/requirements-audit.txt
    Assert-Success 'Install audit tooling'
    $sitePackages = & $buildPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    Assert-Success 'Locate build dependencies'
    & $hostPython -m pip_audit --path $sitePackages --vulnerability-service pypi --progress-spinner off
    Assert-Success 'Audit Windows dependencies'
    }
    Invoke-Stage Backend {
    & $buildPython -m unittest discover -s backend/tests -v
    Assert-Success 'Backend regression tests'
    }
    Invoke-Stage Browser {
    Push-Location frontend
    try {
        npm audit --omit=dev
        Assert-Success 'Audit production JavaScript dependencies'
        npx playwright install chromium --only-shell
        Assert-Success 'Install test browser'
        npm run test:browser
        Assert-Success 'Production browser regression tests'
    } finally { Pop-Location }
    }
    Invoke-Stage Package {
    & $buildPython scripts/write-windows-metadata.py
    Assert-Success 'Generate Windows metadata'
    $icon = Join-Path $root 'assets/sap-lens.ico'
    $metadata = Join-Path $root 'backend/build/version-info.txt'
    $iconData = $icon + ';assets'
    $frontendDist = Join-Path $root 'frontend/dist'
    & $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name SAP-Lens --icon "$icon" --version-file "$metadata" --add-data "$iconData" --paths backend --add-data "$frontendDist;frontend/dist" --specpath backend --distpath backend/dist --workpath backend/build backend/desktop.py
    Assert-Success 'Package Windows executable'
    }
    Invoke-Stage Verify {
    $hash = (Get-FileHash backend/dist/SAP-Lens.exe -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  SAP-Lens.exe" | Set-Content backend/dist/SAP-Lens.exe.sha256 -Encoding ascii
    & $buildPython scripts/verify-windows-package.py
    Assert-Success 'Verify Windows package assets and privacy'
    }
    Invoke-Stage Smoke { & (Join-Path $PSScriptRoot 'test-windows-exe.ps1') }
    Write-Host "Completed build stage: $Stage"
} finally {
    $env:PATH = $originalBuildPath
}
